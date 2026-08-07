"""Turn a desk-created (``custom = 1``) DocType into repo-owned code.

Prototyping new DocTypes in the desk UI is fine — they live only in the site
database though, so they never travel to another environment through the Docker
image and never reach git. This module is the graduation path: it reads such a
DocType (plus its child tables, Custom Fields, Property Setters and Client
Scripts) and renders the file set a code-owned DocType needs, together with a
migration patch that flips ``custom`` to 0 in every environment.

Nothing here writes to the database. The only side effect is files under
``out_dir``. The host-side driver is ``./codify`` in the repo root; it ships this
file into the target container, calls :func:`run_cli` and unpacks the result
into the working tree for review.

Flipping ``custom`` does not touch data: the table is ``tab<DocType>`` either
way, and fieldnames stay verbatim (they are the column names), so no column is
renamed or dropped by codifying.
"""

import base64
import io
import json
import os
import re
import shutil
import tarfile
from datetime import datetime

import frappe
from frappe.model import child_table_fields, default_fields
from frappe.modules import scrub

CYRILLIC = re.compile(r"[Ѐ-ӿ]")

#: Marker pair used to fish the payload out of ``bench execute`` stdout.
PAYLOAD_START = "<<<CODIFY_PAYLOAD_START>>>"
PAYLOAD_END = "<<<CODIFY_PAYLOAD_END>>>"

DF_TYPES = {
	"Attach": "DF.Attach",
	"Attach Image": "DF.AttachImage",
	"Autocomplete": "DF.Autocomplete",
	"Barcode": "DF.Barcode",
	"Check": "DF.Check",
	"Code": "DF.Code",
	"Color": "DF.Color",
	"Currency": "DF.Currency",
	"Data": "DF.Data",
	"Date": "DF.Date",
	"Datetime": "DF.Datetime",
	"Duration": "DF.Duration",
	"Dynamic Link": "DF.DynamicLink",
	"Float": "DF.Float",
	"Geolocation": "DF.Code",
	"HTML": "DF.Text",
	"HTML Editor": "DF.HTMLEditor",
	"Icon": "DF.Data",
	"Int": "DF.Int",
	"JSON": "DF.JSON",
	"Link": "DF.Link",
	"Long Text": "DF.LongText",
	"Markdown Editor": "DF.MarkdownEditor",
	"Password": "DF.Password",
	"Percent": "DF.Percent",
	"Phone": "DF.Phone",
	"Rating": "DF.Rating",
	"Read Only": "DF.ReadOnly",
	"Signature": "DF.Code",
	"Small Text": "DF.SmallText",
	"Text": "DF.Text",
	"Text Editor": "DF.TextEditor",
	"Time": "DF.Time",
}

#: Fieldtypes that hold no value and therefore get no annotation.
LAYOUT_FIELDTYPES = {
	"Section Break",
	"Column Break",
	"Tab Break",
	"Fold",
	"Heading",
	"Button",
	"Image",
}

#: Keys that must never end up in an exported DocType JSON.
DROP_DOCTYPE_KEYS = ("migration_hash", "_user_tags", "_comments", "_assign", "_liked_by")


# ---------------------------------------------------------------------------
# collect
# ---------------------------------------------------------------------------


def collect_bundle(doctype: str, seen: set | None = None) -> dict:
	"""Read ``doctype`` and everything attached to it, child tables included.

	Returns ``{"order": [names...], "records": {name: {...}}}`` where ``order``
	is child-tables-first, i.e. safe reload order for the generated patch.
	"""
	seen = seen if seen is not None else set()
	bundle = {"order": [], "records": {}}
	_collect(doctype, bundle, seen)
	return bundle


def _collect(doctype: str, bundle: dict, seen: set) -> None:
	if doctype in seen:
		return
	seen.add(doctype)

	if not frappe.db.exists("DocType", doctype):
		frappe.throw(f"DocType {doctype} does not exist on this site")

	doc = frappe.get_doc("DocType", doctype)

	# Child tables first, so the patch reloads them before the parent.
	for df in doc.fields:
		if df.fieldtype in ("Table", "Table MultiSelect") and df.options:
			child = df.options
			if frappe.db.get_value("DocType", child, "custom"):
				_collect(child, bundle, seen)
			else:
				bundle.setdefault("stock_children", []).append(child)

	docdict = doc.as_dict(no_nulls=True)
	doc.run_method("before_export", docdict)

	field_names = {df.fieldname for df in doc.fields}

	custom_fields = frappe.get_all(
		"Custom Field",
		filters={"dt": doctype},
		fields=["*"],
		order_by="idx asc, creation asc",
	)
	property_setters = frappe.get_all(
		"Property Setter",
		filters={"doc_type": doctype},
		fields=["name", "doctype_or_field", "field_name", "property", "value", "property_type"],
	)
	client_scripts = frappe.get_all(
		"Client Script",
		filters={"dt": doctype},
		fields=["name", "view", "enabled", "script"],
		order_by="creation asc",
	)
	server_scripts = frappe.get_all(
		"Server Script",
		filters={"reference_doctype": doctype},
		fields=["name", "script_type", "doctype_event", "api_method", "disabled", "script"],
	)
	# API scripts rarely set reference_doctype; catch the ones that mention the
	# DocType in their body so they at least show up in the report.
	for row in frappe.get_all(
		"Server Script",
		filters={"script_type": "API"},
		fields=["name", "script_type", "doctype_event", "api_method", "disabled", "script"],
	):
		if doctype in (row.script or "") and row.name not in [s.name for s in server_scripts]:
			server_scripts.append(row)

	bundle["records"][doctype] = {
		"docdict": docdict,
		"field_names": sorted(field_names),
		"custom_fields": custom_fields,
		"property_setters": property_setters,
		"client_scripts": client_scripts,
		"server_scripts": server_scripts,
		"count": frappe.db.count(doctype),
	}
	bundle["order"].append(doctype)


# ---------------------------------------------------------------------------
# fold
# ---------------------------------------------------------------------------


def fold(record: dict, module: str) -> dict:
	"""Merge Custom Fields and Property Setters into a code-owned DocType dict."""
	docdict = frappe.parse_json(frappe.as_json(record["docdict"]))
	warnings = []
	translations = []

	for key in DROP_DOCTYPE_KEYS:
		docdict.pop(key, None)

	docdict["custom"] = 0
	docdict["module"] = module
	docdict["owner"] = "Administrator"
	docdict["modified_by"] = "Administrator"
	docdict.pop("is_calendar_and_gantt", None)

	fields = docdict.get("fields") or []
	for df in fields:
		for key in default_fields + child_table_fields:
			df.pop(key, None)

	# --- Custom Fields -----------------------------------------------------
	docfield_keys = {df.fieldname for df in frappe.get_meta("DocField").fields}
	for cf in record["custom_fields"]:
		new_field = {k: v for k, v in cf.items() if k in docfield_keys and v not in (None, "")}
		new_field["fieldname"] = cf["fieldname"]
		new_field["fieldtype"] = cf["fieldtype"]
		if any(df.get("fieldname") == cf["fieldname"] for df in fields):
			warnings.append(f"custom field {cf['fieldname']} already present as a DocField — skipped")
			continue
		insert_at = len(fields)
		if cf.get("insert_after"):
			for idx, df in enumerate(fields):
				if df.get("fieldname") == cf["insert_after"]:
					insert_at = idx + 1
					break
			else:
				warnings.append(
					f"custom field {cf['fieldname']}: insert_after '{cf['insert_after']}' not found — appended last"
				)
		fields.insert(insert_at, new_field)

	# --- Property Setters --------------------------------------------------
	by_fieldname = {df.get("fieldname"): df for df in fields}
	for ps in record["property_setters"]:
		value = _cast(ps.get("value"), ps.get("property_type"))
		if ps.get("doctype_or_field") == "DocType":
			docdict[ps["property"]] = value
			continue
		target = by_fieldname.get(ps.get("field_name"))
		if not target:
			warnings.append(
				f"orphan property setter {ps['name']}: field '{ps.get('field_name')}' does not exist — dropped"
			)
			continue
		target[ps["property"]] = value

	fields = [df for df in fields if df.get("fieldname")]
	docdict["fields"] = fields
	docdict["field_order"] = [df["fieldname"] for df in fields]

	# --- sanity checks -----------------------------------------------------
	for df in fields:
		if CYRILLIC.search(df["fieldname"]):
			warnings.append(
				f"field '{df['fieldname']}' has a Cyrillic fieldname — it is the DB column name, "
				"keep it verbatim or rename it with frappe.model.rename_field in the patch"
			)
		if df.get("label") and CYRILLIC.search(df["label"]):
			translations.append(df["label"])
		if df.get("fieldtype") == "Select" and df.get("options"):
			opts = [o for o in str(df["options"]).split("\n") if o.strip()]
			if len(opts) == 1:
				warnings.append(f"field '{df['fieldname']}' is a Select with a single option: {opts[0]!r}")

	if CYRILLIC.search(docdict.get("autoname") or ""):
		warnings.append(f"autoname references a Cyrillic fieldname: {docdict['autoname']}")

	return {"docdict": docdict, "warnings": warnings, "translations": sorted(set(translations))}


def _cast(value, property_type):
	if property_type in ("Check", "Int"):
		try:
			return int(value)
		except (TypeError, ValueError):
			return 0
	if property_type in ("Float", "Currency", "Percent"):
		try:
			return float(value)
		except (TypeError, ValueError):
			return 0.0
	return value


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def _class_name(doctype: str) -> str:
	return re.sub(r"[^A-Za-z0-9]", "", doctype.title())


def render_controller(doctype: str, docdict: dict, module_dir: str) -> str:
	"""Controller stub with the ``TYPE_CHECKING`` DF annotations frappe expects."""
	class_name = _class_name(doctype)
	annotations = []
	imports = []
	for df in docdict.get("fields") or []:
		fieldtype = df.get("fieldtype")
		if fieldtype in LAYOUT_FIELDTYPES:
			continue
		fieldname = df["fieldname"]
		if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", fieldname):
			# Cyrillic / punctuated fieldnames are valid columns but not valid
			# Python identifiers — they cannot be annotated.
			continue
		if fieldtype in ("Table", "Table MultiSelect"):
			child = df.get("options") or ""
			child_class = _class_name(child)
			child_snake = scrub(child)
			imports.append(
				f"from erpnext.{module_dir}.doctype.{child_snake}.{child_snake} import {child_class}"
			)
			annotations.append(f"\t\t{fieldname}: DF.Table[{child_class}]")
			continue
		if fieldtype == "Select":
			options = [o for o in str(df.get("options") or "").split("\n")]
			literal = ", ".join(f'"{o}"' for o in options)
			annotations.append(
				f"\t\t{fieldname}: DF.Literal[{literal}]" if literal else f"\t\t{fieldname}: DF.Data"
			)
			continue
		df_type = DF_TYPES.get(fieldtype, "DF.Data")
		if df.get("reqd") or fieldtype == "Check":
			annotations.append(f"\t\t{fieldname}: {df_type}")
		else:
			annotations.append(f"\t\t{fieldname}: {df_type} | None")

	annotations.sort(key=lambda line: line.strip())
	import_block = "\n".join(f"\t\t{line}" for line in sorted(set(imports)))
	body = "\n".join(annotations) or "\t\tpass"

	return f"""# Copyright (c) {datetime.now().year}, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class {class_name}(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

{import_block}

{body}
	# end: auto-generated types

	pass
"""


PATCH_TEMPLATE = '''"""Take ownership of the `{doctype}` DocType in code.

Generated by ./codify — it was created through the desk UI (``custom = 1``) and
lived only in the site database. This patch flips it to a code-owned DocType so
`{snake}.json` in the repo becomes the single source of truth. Data is
untouched: the table is `tab{doctype}` either way and no fieldname changes.
"""

import frappe

# (doctype, module directory, file name) — child tables first.
TARGETS = {targets}

MODULE = "{module}"

# Folded into the DocType JSON, so the DB rows are now redundant.
DROP_CUSTOM_FIELDS = {drop_custom_fields}
DROP_PROPERTY_SETTERS = {drop_property_setters}

# Superseded by the exported {snake}.js — disabled rather than deleted so the
# original body stays recoverable from the site.
DISABLE_CLIENT_SCRIPTS = {disable_client_scripts}


def execute():
	if DROP_CUSTOM_FIELDS:
		for name in frappe.get_all("Custom Field", filters={{"name": ("in", DROP_CUSTOM_FIELDS)}}, pluck="name"):
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)

	if DROP_PROPERTY_SETTERS:
		for name in frappe.get_all(
			"Property Setter", filters={{"name": ("in", DROP_PROPERTY_SETTERS)}}, pluck="name"
		):
			frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)

	for name in DISABLE_CLIENT_SCRIPTS:
		if frappe.db.exists("Client Script", name):
			frappe.db.set_value("Client Script", name, "enabled", 0, update_modified=False)

	for doctype, module_dir, file_name in TARGETS:
		if frappe.db.exists("DocType", doctype):
			frappe.db.set_value(
				"DocType",
				doctype,
				{{"custom": 0, "module": MODULE}},
				update_modified=False,
			)

		frappe.reload_doc(module_dir, "doctype", file_name, force=True)
		frappe.clear_cache(doctype=doctype)

	frappe.db.commit()
'''


def render_patch(bundle: dict, module: str, module_dir: str) -> str:
	targets = [(dt, module_dir, scrub(dt)) for dt in bundle["order"]]
	drop_custom_fields = []
	drop_property_setters = []
	disable_client_scripts = []
	for dt in bundle["order"]:
		record = bundle["records"][dt]
		drop_custom_fields += [cf["name"] for cf in record["custom_fields"]]
		drop_property_setters += [ps["name"] for ps in record["property_setters"]]
		disable_client_scripts += [cs["name"] for cs in record["client_scripts"] if cs.get("enabled")]

	root = bundle["order"][-1]
	return PATCH_TEMPLATE.format(
		doctype=root,
		snake=scrub(root),
		module=module,
		targets=_pyliteral(targets),
		drop_custom_fields=_pyliteral(drop_custom_fields),
		drop_property_setters=_pyliteral(drop_property_setters),
		disable_client_scripts=_pyliteral(disable_client_scripts),
	)


def _pyliteral(value) -> str:
	"""Render a list/tuple literal the way ruff-format wants it."""
	if not value:
		return "[]"
	if isinstance(value[0], tuple):
		rows = ",\n".join(f"\t({', '.join(repr(v) for v in row)})" for row in value)
		return f"[\n{rows},\n]"
	rows = ",\n".join(f"\t{v!r}" for v in value)
	return f"[\n{rows},\n]"


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def export(doctype: str, module: str, out_dir: str) -> dict:
	"""Render every file for ``doctype`` under ``out_dir``; return the report.

	``out_dir/files`` mirrors the ``erpnext/`` subtree, so the host driver only
	has to copy it over the repo's ``erpnext/`` directory.
	"""
	module_dir = scrub(module)
	if not frappe.db.exists("Module Def", module):
		frappe.throw(f"Module Def {module} does not exist — pick an existing stock module")

	bundle = collect_bundle(doctype)
	report = {
		"doctype": doctype,
		"module": module,
		"module_dir": module_dir,
		"order": bundle["order"],
		"stock_children": sorted(set(bundle.get("stock_children") or [])),
		"doctypes": [],
		"warnings": [],
		"translations": [],
		"server_scripts": [],
		"files": [],
	}

	files_root = os.path.join(out_dir, "files")
	os.makedirs(files_root, exist_ok=True)

	for dt in bundle["order"]:
		record = bundle["records"][dt]
		result = fold(record, module)
		docdict = result["docdict"]
		snake = scrub(dt)
		folder = os.path.join(files_root, module_dir, "doctype", snake)
		os.makedirs(folder, exist_ok=True)

		_write(report, files_root, folder, "__init__.py", "")
		_write(report, files_root, folder, f"{snake}.json", frappe.as_json(docdict))
		_write(report, files_root, folder, f"{snake}.py", render_controller(dt, docdict, module_dir))

		enabled = [cs for cs in record["client_scripts"] if cs.get("enabled") and cs.get("view") == "Form"]
		disabled = [cs for cs in record["client_scripts"] if not cs.get("enabled")]
		if enabled:
			blocks = [f"// from Client Script: {cs['name']}\n{cs['script']}" for cs in enabled]
			_write(report, files_root, folder, f"{snake}.js", "\n\n".join(blocks) + "\n")
		for cs in disabled:
			_write(report, files_root, folder, f"{scrub(cs['name'])}.js.disabled", cs["script"] or "")

		if record["server_scripts"]:
			blocks = []
			for ss in record["server_scripts"]:
				blocks.append(
					f"# Server Script: {ss['name']} ({ss['script_type']}"
					f"{'/' + ss['doctype_event'] if ss.get('doctype_event') else ''}"
					f"{', disabled' if ss.get('disabled') else ''})\n"
					f"# api_method: {ss.get('api_method') or '-'}\n"
					f"{ss['script']}"
				)
			_write(report, files_root, folder, "_server_scripts.py.txt", "\n\n\n".join(blocks) + "\n")
			report["server_scripts"] += [ss["name"] for ss in record["server_scripts"]]

		report["doctypes"].append(
			{
				"name": dt,
				"istable": docdict.get("istable") or 0,
				"documents": record["count"],
				"fields": len(docdict.get("fields") or []),
				"custom_fields": [cf["name"] for cf in record["custom_fields"]],
				"property_setters": [ps["name"] for ps in record["property_setters"]],
				"client_scripts": [
					f"{cs['name']} ({'enabled' if cs.get('enabled') else 'disabled'})"
					for cs in record["client_scripts"]
				],
			}
		)
		report["warnings"] += [f"{dt}: {w}" for w in result["warnings"]]
		report["translations"] += result["translations"]

	patches_dir = os.path.join(files_root, "patches", "v15_0")
	os.makedirs(patches_dir, exist_ok=True)
	patch_name = f"codify_{scrub(doctype)}"
	_write(report, files_root, patches_dir, f"{patch_name}.py", render_patch(bundle, module, module_dir))
	report["patch"] = f"erpnext.patches.v15_0.{patch_name}"
	report["translations"] = sorted(set(report["translations"]))

	with open(os.path.join(out_dir, "report.json"), "w") as fh:  # nosemgrep
		fh.write(json.dumps(report, indent=2, ensure_ascii=False, default=str))

	return report


def _write(report: dict, files_root: str, folder: str, name: str, content: str) -> None:
	path = os.path.join(folder, name)
	with open(path, "w") as fh:  # nosemgrep
		fh.write(content)
	report["files"].append(os.path.relpath(path, files_root))


# ---------------------------------------------------------------------------
# CLI bridge
# ---------------------------------------------------------------------------


def run_cli(doctype: str, module: str) -> None:
	"""Export into a temp dir and print a base64 tar.gz between markers.

	Used by ``./codify``: the container filesystem is throwaway, so the payload
	travels back over stdout instead of being fetched from disk.
	"""
	out_dir = frappe.utils.get_bench_path() + f"/sites/codify-{frappe.generate_hash(length=8)}"
	os.makedirs(out_dir, exist_ok=True)
	try:
		report = export(doctype, module, out_dir)
		buf = io.BytesIO()
		with tarfile.open(fileobj=buf, mode="w:gz") as tar:
			tar.add(out_dir, arcname=".")
		print(PAYLOAD_START)
		print(base64.b64encode(buf.getvalue()).decode())
		print(PAYLOAD_END)
		print(f"codify: {len(report['files'])} files, {len(report['warnings'])} warnings")
	finally:
		shutil.rmtree(out_dir, ignore_errors=True)
