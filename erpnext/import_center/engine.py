"""Рушій імпорту: файл → розпізнавання скрипту → розбір і план змін → застосування.

Уся логіка конкретного імпорту живе в документі «Import Script» (код, маркери, права, поля,
макет попереднього перегляду), тож новий тип файлу додається без змін у коді.
Скрипт виконується через exec від імені користувача: це довірений код, який редагує лише
System Manager; кожен запис іде через doc.save() із перевіркою прав.
"""

import csv
import hashlib
import json
import re

import frappe
from frappe import _
from frappe.utils import cint

PROGRESS_EVENT = "import_center_progress"
HEAD_ROWS = 20
HEAD_PAGES = 2


class ImportContext:
	def __init__(self, run, file_path):
		self.run = run
		self.file_path = file_path
		self.user = frappe.session.user
		self.stage = "parse"

	def progress(self, percent, message=""):
		_publish(self.run, self.stage, percent, message)


def _publish(run, stage, percent, message=""):
	frappe.db.set_value(
		"Import Run",
		run,
		{"progress": percent, "progress_stage": message},
		update_modified=False,
	)
	frappe.db.commit()
	frappe.publish_realtime(
		PROGRESS_EVENT,
		{"run": run, "stage": stage, "percent": percent, "message": message},
		user=frappe.session.user,
	)


def _norm(text):
	return re.sub(r"\s+", " ", text or "").strip().lower()


def _file_path(file_url):
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	return file_doc.get_full_path()


def _head(path, ext):
	"""Текст початку файлу — на ньому перевіряємо маркери."""
	if ext == "pdf":
		import pdfplumber

		with pdfplumber.open(path) as pdf:
			return "\n".join((page.extract_text() or "") for page in pdf.pages[:HEAD_PAGES])

	if ext == "xlsx":
		from openpyxl import load_workbook

		book = load_workbook(path, read_only=True, data_only=True)
		lines = []

		for index, row in enumerate(book.worksheets[0].iter_rows(values_only=True)):
			if index >= HEAD_ROWS:
				break

			lines.append(" | ".join(str(c) for c in row if c is not None))

		return "\n".join(lines)

	with open(path, encoding="utf-8-sig", errors="replace", newline="") as handle:
		return "\n".join(
			" | ".join(row) for _i, row in zip(range(HEAD_ROWS), csv.reader(handle), strict=False)
		)


def _marker_matches(marker, head, filename):
	subject = filename if marker.where == "Filename" else head

	if marker.kind == "Regex":
		return re.search(marker.value, subject or "", re.IGNORECASE) is not None

	return _norm(marker.value) in _norm(subject)


def detect(path, filename):
	ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
	scripts = frappe.get_all(
		"Import Script",
		filters={"enabled": 1, "file_types": ext},
		fields=["name", "priority"],
		order_by="priority desc, name asc",
	)

	if not scripts:
		return []

	head = _head(path, ext)
	found = []

	for row in scripts:
		doc = frappe.get_doc("Import Script", row.name)

		if doc.markers and all(_marker_matches(m, head, filename) for m in doc.markers):
			found.append(doc.name)

	return found


def missing_permissions(script):
	missing = []

	for row in script.required_permissions:
		if not frappe.has_permission(row.reference_doctype, row.ptype):
			missing.append({"doctype": row.reference_doctype, "ptype": row.ptype})

	return missing


def _script_info(script_name):
	script = frappe.get_doc("Import Script", script_name)

	return {
		"name": script.name,
		"title": script.title,
		"description": script.description,
		"change_fields": [
			{
				"doctype": r.reference_doctype,
				"fieldname": r.fieldname,
				"label": r.label or r.fieldname,
				"mode": r.mode,
			}
			for r in script.change_fields
		],
		"required_permissions": [
			{"doctype": r.reference_doctype, "ptype": r.ptype} for r in script.required_permissions
		],
		"missing_permissions": missing_permissions(script),
		"preview_config": frappe.parse_json(script.preview_config) if script.preview_config else {},
	}


@frappe.whitelist()
def register_upload(file_url, script=None):
	"""Файл завантажено: розпізнаємо скрипт і заводимо запуск."""
	filename = file_url.rsplit("/", 1)[-1]
	path = _file_path(file_url)
	candidates = detect(path, filename)

	if script:
		if script not in candidates:
			frappe.throw(_("The file does not match the selected script."))

		candidates = [script]

	if not candidates:
		return {
			"candidates": [],
			"message": _("The file type is not recognised: no import script matches it."),
		}

	if len(candidates) > 1:
		return {"candidates": [_script_info(name) for name in candidates], "file_url": file_url}

	info = _script_info(candidates[0])
	run = frappe.get_doc(
		{
			"doctype": "Import Run",
			"import_script": candidates[0],
			"file": file_url,
			"file_name": filename,
			"status": "Uploaded",
		}
	).insert()

	return {"candidates": [info], "run": run.name, "script": info}


def _load(script_name, code):
	namespace = {"frappe": frappe, "json": json, "__name__": f"import_script_{script_name}"}
	exec(compile(code, script_name, "exec"), namespace)

	for fn in ("parse", "plan", "apply"):
		if not callable(namespace.get(fn)):
			frappe.throw(_("The script must define {0}().").format(fn + "(...)"))

	return namespace


def _own_run(run):
	doc = frappe.get_doc("Import Run", run)

	if doc.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw(_("This import run belongs to another user."), frappe.PermissionError)

	return doc


def _enqueue(job, run, **kwargs):
	from frappe.utils.background_jobs import is_job_enqueued

	job_id = f"import_center::{job.__name__}::{run}"

	if not is_job_enqueued(job_id):
		frappe.enqueue(job, queue="long", timeout=3600, job_id=job_id, run=run, now=frappe.in_test, **kwargs)


@frappe.whitelist()
def start_parse(run):
	doc = _own_run(run)
	script = frappe.get_doc("Import Script", doc.import_script)
	missing = missing_permissions(script)

	if missing:
		frappe.throw(_("You cannot import this file: missing permissions."), frappe.PermissionError)

	frappe.db.set_value("Import Run", run, {"status": "Parsing", "progress": 0, "error": ""})
	frappe.db.commit()
	_enqueue(_parse_job, run)


def _parse_job(run):
	doc = frappe.get_doc("Import Run", run)

	try:
		script = frappe.get_doc("Import Script", doc.import_script)
		namespace = _load(script.name, script.code)
		ctx = ImportContext(run, _file_path(doc.file))
		ctx.stage = "parse"
		ctx.progress(5, _("Reading the file"))
		parsed = namespace["parse"](ctx)
		ctx.progress(96, _("Building the list of changes"))
		plan = namespace["plan"](ctx, parsed) or []
		doc.db_set(
			{
				"parsed_payload": json.dumps(parsed, default=str, ensure_ascii=False),
				"plan": json.dumps(plan, default=str, ensure_ascii=False),
				"status": "Parsed",
				"progress": 100,
				"progress_stage": _("Ready to import"),
			}
		)
		frappe.db.commit()
		frappe.publish_realtime(
			PROGRESS_EVENT,
			{"run": run, "stage": "parse", "percent": 100, "message": "", "done": True},
			user=frappe.session.user,
		)
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(title=f"Import Center parse {run}")
		doc.db_set({"status": "Failed", "error": str(e)[:1000]})
		frappe.db.commit()
		frappe.publish_realtime(
			PROGRESS_EVENT,
			{"run": run, "stage": "parse", "failed": True, "message": str(e)},
			user=frappe.session.user,
		)


@frappe.whitelist()
def start_import(run, plan_hash=None):
	doc = _own_run(run)

	if doc.status != "Parsed":
		frappe.throw(_("The file has to be parsed first."))

	script = frappe.get_doc("Import Script", doc.import_script)

	if missing_permissions(script):
		frappe.throw(_("You cannot import this file: missing permissions."), frappe.PermissionError)

	if plan_hash and plan_hash != _hash(doc.plan):
		frappe.throw(_("The plan has changed, parse the file again."))

	frappe.db.set_value("Import Run", run, {"status": "Importing", "progress": 0})
	frappe.db.commit()
	_enqueue(_import_job, run)


def _hash(text):
	return hashlib.sha1((text or "").encode()).hexdigest()


def _import_job(run):
	doc = frappe.get_doc("Import Run", run)

	try:
		script = frappe.get_doc("Import Script", doc.import_script)
		namespace = _load(script.name, script.code)
		ctx = ImportContext(run, _file_path(doc.file))
		ctx.stage = "import"
		parsed = json.loads(doc.parsed_payload)
		plan = json.loads(doc.plan)
		stats = namespace["apply"](ctx, parsed, plan) or {}
		doc.db_set(
			{
				"stats": json.dumps(stats, default=str, ensure_ascii=False),
				"status": "Done",
				"progress": 100,
				"progress_stage": _("Done"),
			}
		)
		frappe.db.commit()
		frappe.publish_realtime(
			PROGRESS_EVENT,
			{"run": run, "stage": "import", "percent": 100, "done": True, "stats": stats},
			user=frappe.session.user,
		)
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(title=f"Import Center import {run}")
		doc.db_set({"status": "Failed", "error": str(e)[:1000]})
		frappe.db.commit()
		frappe.publish_realtime(
			PROGRESS_EVENT,
			{"run": run, "stage": "import", "failed": True, "message": str(e)},
			user=frappe.session.user,
		)


@frappe.whitelist()
def get_run(run):
	doc = _own_run(run)
	script = _script_info(doc.import_script)

	return {
		"run": doc.name,
		"status": doc.status,
		"progress": doc.progress,
		"stage": doc.progress_stage,
		"error": doc.error,
		"script": script,
		"parsed": json.loads(doc.parsed_payload) if doc.parsed_payload else None,
		"plan": json.loads(doc.plan) if doc.plan else None,
		"plan_hash": _hash(doc.plan),
		"stats": json.loads(doc.stats) if doc.stats else None,
	}


def purge_old_runs():
	"""Scheduler: запуски старші за 30 днів зникають разом із файлом."""
	cutoff = frappe.utils.add_days(frappe.utils.nowdate(), -30)

	for name in frappe.get_all("Import Run", filters={"creation": ("<", cutoff)}, pluck="name"):
		frappe.delete_doc("Import Run", name, ignore_permissions=True, force=True)


class _TestContext:
	"""Контекст пробного запуску: прогрес збирається в список, у базу й realtime нічого не йде."""

	def __init__(self, file_path):
		self.run = "TEST"
		self.file_path = file_path
		self.user = frappe.session.user
		self.stage = "parse"
		self.log = []

	def progress(self, percent, message=""):
		self.log.append({"stage": self.stage, "percent": percent, "message": str(message)})


def _marker_report(script, head, filename):
	return [
		{
			"where": m.where,
			"kind": m.kind,
			"value": m.value,
			"matched": bool(_marker_matches(m, head, filename)),
		}
		for m in script.markers
	]


@frappe.whitelist()
def test_import(file_url, script=None, code=None, run_apply=0):
	"""Пробний імпорт для розробки скрипту: повний вивід розпізнавання, розбору, плану й (за бажанням)
	застосування. Застосування виконується в транзакції, яку завжди відкочуємо, — у базі нічого не лишається.
	`code` — чернетка скрипту без збереження."""
	import traceback

	frappe.only_for("System Manager")
	filename = file_url.rsplit("/", 1)[-1]
	ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
	path = _file_path(file_url)
	head = _head(path, ext)
	report = {"file": filename, "head_text": head[:3000], "detection": [], "stage": "detect"}

	for name in frappe.get_all("Import Script", filters={"file_types": ext}, pluck="name"):
		doc = frappe.get_doc("Import Script", name)
		markers = _marker_report(doc, head, filename)
		report["detection"].append(
			{
				"script": name,
				"enabled": bool(doc.enabled),
				"priority": doc.priority,
				"matched": bool(markers) and all(m["matched"] for m in markers),
				"markers": markers,
			}
		)

	chosen = script or next(
		(
			d["script"]
			for d in sorted(report["detection"], key=lambda d: -(d["priority"] or 0))
			if d["matched"] and d["enabled"]
		),
		None,
	)
	report["chosen_script"] = chosen

	if not chosen:
		report["error"] = "No script matches this file (see detection.markers); pass `script` to force one."
		return report

	script_doc = frappe.get_doc("Import Script", chosen)
	report["missing_permissions"] = missing_permissions(script_doc)
	report["required_permissions"] = [
		{"doctype": r.reference_doctype, "ptype": r.ptype} for r in script_doc.required_permissions
	]
	report["change_fields"] = [
		{"doctype": r.reference_doctype, "fieldname": r.fieldname, "mode": r.mode}
		for r in script_doc.change_fields
	]
	report["code_source"] = "draft (unsaved)" if code else f"saved v{script_doc.version}"
	ctx = _TestContext(path)

	try:
		namespace = _load(chosen, code or script_doc.code)
		report["stage"] = "parse"
		parsed = namespace["parse"](ctx)
		report["parsed"] = frappe.parse_json(json.dumps(parsed, default=str))
		report["stage"] = "plan"
		plan = namespace["plan"](ctx, parsed) or []
		report["plan"] = frappe.parse_json(json.dumps(plan, default=str))
		report["plan_summary"] = {
			"items": len(plan),
			"changes": sum(len(i.get("changes") or []) for i in plan),
			"problems": [i.get("problem") for i in plan if i.get("problem")],
		}

		if cint(run_apply):
			report["stage"] = "apply"
			ctx.stage = "import"
			real_commit = frappe.db.commit
			frappe.db.savepoint("import_center_test")
			frappe.db.commit = lambda *a, **k: None

			try:
				report["apply_result"] = frappe.parse_json(
					json.dumps(namespace["apply"](ctx, parsed, plan) or {}, default=str)
				)
			finally:
				frappe.db.commit = real_commit
				frappe.db.rollback(save_point="import_center_test")

			report["apply_rolled_back"] = True

		report["stage"] = "done"
	except Exception as e:
		report["error"] = f"{type(e).__name__}: {e}"
		report["traceback"] = traceback.format_exc()
		frappe.db.rollback()

	report["progress_log"] = ctx.log
	return report
