import hashlib
import re
from difflib import SequenceMatcher

import frappe
from frappe.utils import cint, now_datetime, strip_html_tags

TYPE = "AI Error Type"
SOLUTION = "AI Error Solution"
MAX_ACTIVE = 5
MAX_PROMPT_ITEMS = 5
MAX_SOLUTION_CHARS = 700
MAX_TITLE_CHARS = 300
SIMILAR = 0.8

QUOTED = re.compile(r"\"[^\"]*\"|«[^»]*»|“[^”]*”|(?<!\w)'[^']*'(?!\w)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?")
DOCNAME = re.compile(r"\b[A-Za-zА-Яа-яІіЇїЄє]+(?:-[\w]+)*-\d[\w-]*\b")
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
SPACES = re.compile(r"\s+")


def normalize(message: str) -> str:
	"""Reduce an error message to its template: values, names and numbers become placeholders."""
	text = strip_html_tags(str(message or "")).strip()
	if "Traceback" in text:
		lines = [line.strip() for line in text.splitlines() if line.strip()]
		text = lines[-1] if lines else text
	text = QUOTED.sub('"…"', text)
	text = EMAIL.sub("…", text)
	text = DATE.sub("…", text)
	text = DOCNAME.sub("…", text)
	text = NUMBER.sub("#", text)
	return SPACES.sub(" ", text).strip()[:MAX_TITLE_CHARS]


def signature(doctype: str | None, message: str) -> tuple[str, str]:
	title = normalize(message)
	digest = hashlib.sha1(f"{doctype or ''}|{title.lower()}".encode()).hexdigest()[:16]
	return digest, title


def _score(row) -> int:
	return cint(row.get("helpful")) - cint(row.get("wrong"))


def _solutions(error_type: str, status: str | None = None) -> list[dict]:
	filters = {"parent": error_type, "parenttype": TYPE}
	if status:
		filters["status"] = status
	return frappe.get_all(
		SOLUTION,
		filters=filters,
		fields=["name", "solution", "status", "helpful", "wrong", "idx"],
		order_by="idx asc",
		parent_doctype=TYPE,
	)


def _bump(table: str, name: str, **increments):
	doctype = frappe.qb.DocType(table)
	query = frappe.qb.update(doctype)
	for field, amount in increments.items():
		query = query.set(doctype[field], doctype[field] + amount)
	query.where(doctype.name == name).run()


def touch(context: dict) -> dict | None:
	"""Find or create the error type of this error and count one more occurrence."""
	message = str(context.get("error") or "")
	if not message.strip():
		return None
	doctype = context.get("doctype") or None
	if doctype and not frappe.db.exists("DocType", doctype):
		doctype = None
	sig, title = signature(doctype, message)

	if not frappe.db.exists(TYPE, sig):
		try:
			frappe.get_doc(
				{
					"doctype": TYPE,
					"signature": sig,
					"title": title or message[:MAX_TITLE_CHARS],
					"reference_doctype": doctype,
					"sample_message": strip_html_tags(message)[:1000],
					"occurrences": 0,
				}
			).insert(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			frappe.clear_messages()
	_bump(TYPE, sig, occurrences=1)
	return {"name": sig, "title": title, "doctype": doctype}


def lookup(context: dict) -> dict:
	error_type = touch(context)
	if not error_type:
		return {"type": None, "solutions": []}
	solutions = sorted(_solutions(error_type["name"], "Active"), key=_score, reverse=True)
	return {
		"type": error_type["name"],
		"solutions": [{"name": s.name, "solution": s.solution} for s in solutions],
	}


def rate(error_type: str, solution: str, verdict: str):
	row = frappe.db.get_value(SOLUTION, solution, ["parent", "parenttype", "status"], as_dict=True)
	if not row or row.parent != error_type or row.parenttype != TYPE:
		frappe.throw(frappe._("Unknown solution"))
	if verdict == "helpful":
		_bump(SOLUTION, solution, helpful=1)
	elif verdict == "wrong":
		_bump(SOLUTION, solution, wrong=1)
		frappe.db.set_value(SOLUTION, solution, "status", "Wrong", update_modified=False)
	else:
		frappe.throw(frappe._("Unknown verdict"))


def clean_solution(text: str) -> str:
	return strip_html_tags(str(text or "")).strip()[:MAX_SOLUTION_CHARS]


def add_solution(error_type: str, text: str) -> str:
	"""Store a confirmed solution; a near-duplicate of an active one just earns a vote."""
	text = clean_solution(text)
	if not text:
		frappe.throw(frappe._("Empty solution"))
	active = _solutions(error_type, "Active")
	for row in active:
		if SequenceMatcher(None, row.solution.lower(), text.lower()).ratio() >= SIMILAR:
			_bump(SOLUTION, row.name, helpful=1)
			return row.name

	if len(active) >= MAX_ACTIVE:
		worst = min(active, key=_score)
		frappe.db.delete(SOLUTION, {"name": worst.name})

	doc = frappe.get_doc(TYPE, error_type)
	row = doc.append(
		"solutions",
		{
			"solution": text,
			"status": "Active",
			"helpful": 1,
			"created_from": frappe.session.user,
			"last_shown": now_datetime(),
		},
	)
	doc.save(ignore_permissions=True)
	return row.name


def _items(rows) -> str:
	return "\n".join(f"- {clean_solution(r.solution)}" for r in rows[:MAX_PROMPT_ITEMS])


def knowledge_block(error_type: str | None) -> str:
	"""Prompt text with the solutions already tried for this error type."""
	if not error_type or not frappe.db.exists(TYPE, error_type):
		return ""
	wrong = _solutions(error_type, "Wrong")
	active = sorted(_solutions(error_type, "Active"), key=_score, reverse=True)
	parts = []
	if wrong:
		parts.append(
			"Known WRONG solutions for this error, users rejected them. Do not suggest them:\n"
			+ _items(wrong)
		)
	if active:
		parts.append("Solutions users confirmed earlier (reuse or improve them):\n" + _items(active))
	return "\n\n".join(parts)
