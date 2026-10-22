import json

import frappe
from frappe import _

MAX_ROWS = 50
MAX_RESULT_CHARS = 20000
DENIED_DOCTYPES = {"File", "Chat Thread", "Chat Message", "AI Helper Settings", "AI Helper Company Key"}
SECRET_FIELDTYPES = {"Password"}
STANDARD_FIELDS = {"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx"}

TOOL_SCHEMAS = [
	{
		"name": "get_doctypes",
		"description": "Find DocTypes the user can read, by part of the name.",
		"input_schema": {
			"type": "object",
			"properties": {"search": {"type": "string"}},
			"required": [],
		},
	},
	{
		"name": "get_doctype_fields",
		"description": "List fields of a DocType (fieldname, label, type, options, mandatory).",
		"input_schema": {
			"type": "object",
			"properties": {"doctype": {"type": "string"}},
			"required": ["doctype"],
		},
	},
	{
		"name": "get_documents",
		"description": (
			f"Read documents of a DocType with the user's own permissions. At most {MAX_ROWS} rows. "
			'filters is a dict like {"status": "Open"} or {"qty": [">", 5]}.'
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"filters": {"type": "object"},
				"fields": {"type": "array", "items": {"type": "string"}},
				"order_by": {"type": "string"},
				"limit": {"type": "integer"},
			},
			"required": ["doctype"],
		},
	},
	{
		"name": "run_report",
		"description": f"Run a report with the user's permissions. At most {MAX_ROWS} rows are returned.",
		"input_schema": {
			"type": "object",
			"properties": {"report_name": {"type": "string"}, "filters": {"type": "object"}},
			"required": ["report_name"],
		},
	},
]


def _check_readable(doctype: str):
	if doctype in DENIED_DOCTYPES or not frappe.db.exists("DocType", doctype):
		frappe.throw(_("DocType {0} is not available").format(doctype), frappe.PermissionError)
	frappe.has_permission(doctype, "read", throw=True)


def _readable_fields(meta) -> dict:
	return {df.fieldname: df for df in meta.fields if df.fieldtype not in SECRET_FIELDTYPES}


def get_doctypes(search: str = "") -> list[str]:
	names = frappe.get_list(
		"DocType",
		filters={"istable": 0, "issingle": 0, "name": ["like", f"%{search}%"]},
		pluck="name",
		limit=200,
	)
	allowed = [n for n in names if n not in DENIED_DOCTYPES and frappe.has_permission(n, "read")]
	return allowed[:MAX_ROWS]


def get_doctype_fields(doctype: str) -> list[dict]:
	_check_readable(doctype)
	return [
		{
			"fieldname": df.fieldname,
			"label": df.label,
			"fieldtype": df.fieldtype,
			"options": df.options,
			"reqd": df.reqd,
		}
		for df in _readable_fields(frappe.get_meta(doctype)).values()
		if df.fieldtype not in frappe.model.layout_fields
	]


def get_documents(
	doctype: str,
	filters: dict | None = None,
	fields: list[str] | None = None,
	order_by: str | None = None,
	limit: int = 20,
) -> list[dict]:
	_check_readable(doctype)
	allowed = set(_readable_fields(frappe.get_meta(doctype))) | STANDARD_FIELDS
	fields = [f for f in (fields or ["name"]) if f in allowed] or ["name"]
	return frappe.get_list(
		doctype,
		filters=filters or {},
		fields=fields,
		order_by=order_by or "modified desc",
		limit=max(1, min(int(limit or 20), MAX_ROWS)),
	)


def run_report(report_name: str, filters: dict | None = None) -> dict:
	from frappe.desk.query_report import run

	result = run(report_name, filters=filters or {}, ignore_prepared_report=True)
	columns = [c.get("label") if isinstance(c, dict) else c for c in result.get("columns", [])]
	return {"columns": columns, "rows": (result.get("result") or [])[:MAX_ROWS]}


HANDLERS = {
	"get_doctypes": get_doctypes,
	"get_doctype_fields": get_doctype_fields,
	"get_documents": get_documents,
	"run_report": run_report,
}


def execute(name: str, arguments: dict) -> tuple[str, bool]:
	handler = HANDLERS.get(name)
	if not handler:
		return f"Unknown tool {name}", True
	try:
		output = json.dumps(handler(**arguments), default=str, ensure_ascii=False)
	except Exception as e:
		frappe.clear_messages()
		return f"{type(e).__name__}: {e}", True
	return output[:MAX_RESULT_CHARS], False
