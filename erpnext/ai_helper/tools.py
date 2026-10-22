import inspect
import json

import frappe
from frappe import _

MAX_ROWS = 50
MAX_RESULT_CHARS = 20000
DENIED_DOCTYPES = {
	"File",
	"Chat Thread",
	"Chat Message",
	"AI Helper Settings",
	"AI Helper Company Key",
	"AI Error Type",
	"AI Error Solution",
}
MAX_SOURCE_CHARS = 6000
LOGIC_METHODS = (
	"autoname",
	"before_validate",
	"validate",
	"before_save",
	"before_insert",
	"before_submit",
	"on_update",
	"on_submit",
	"before_cancel",
	"on_cancel",
	"on_trash",
	"before_update_after_submit",
)
LOGIC_PACKAGES = ("erpnext", "frappe", "hrms")
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
		"description": (
			"List fields of a DocType (fieldname, label, type, options, mandatory, depends_on, "
			"mandatory_depends_on, read_only, unique)."
		),
		"input_schema": {
			"type": "object",
			"properties": {"doctype": {"type": "string"}},
			"required": ["doctype"],
		},
	},
	{
		"name": "get_doctype_logic",
		"description": (
			"Show the validation logic of a DocType: Python controller methods (validate, on_submit, ...), "
			"doc_events handlers from hooks, and Server/Client Scripts when the user may read them. "
			"Use it to find which check raised an error."
		),
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
			"depends_on": df.depends_on,
			"mandatory_depends_on": df.mandatory_depends_on,
			"read_only": df.read_only,
			"unique": df.unique,
		}
		for df in _readable_fields(frappe.get_meta(doctype)).values()
		if df.fieldtype not in frappe.model.layout_fields
	]


def _in_logic_package(obj) -> bool:
	module = getattr(obj, "__module__", "") or ""
	return module.split(".")[0] in LOGIC_PACKAGES


def _source(obj) -> str | None:
	try:
		return inspect.getsource(obj)[:MAX_SOURCE_CHARS]
	except (OSError, TypeError):
		return None


def _controller_logic(doctype: str) -> dict:
	from frappe.model.base_document import get_controller

	controller = get_controller(doctype)
	methods = {}
	for name in LOGIC_METHODS:
		method = getattr(controller, name, None)
		if not callable(method) or not _in_logic_package(method):
			continue
		if getattr(method, "__qualname__", "").startswith("Document."):
			continue
		source = _source(method)
		if source:
			methods[name] = source
	return methods


def _hook_logic(doctype: str) -> dict:
	events = {}
	for key in (doctype, "*"):
		for event, handlers in (frappe.get_hooks("doc_events").get(key) or {}).items():
			if isinstance(handlers, str):
				handlers = [handlers]
			for path in handlers:
				try:
					source = _source(frappe.get_attr(path))
				except Exception:
					source = None
				events.setdefault(f"{key}.{event}", []).append({"handler": path, "source": source})
	return events


def _readable_scripts(script_doctype: str, filters: dict) -> list[dict] | str:
	if not frappe.has_permission(script_doctype, "read"):
		return "not permitted"
	rows = frappe.get_list(script_doctype, filters=filters, fields=["name", "script"], limit=MAX_ROWS)
	return [{"name": r.name, "script": (r.script or "")[:MAX_SOURCE_CHARS]} for r in rows]


def get_doctype_logic(doctype: str) -> dict:
	_check_readable(doctype)
	return {
		"controller": _controller_logic(doctype),
		"doc_events": _hook_logic(doctype),
		"server_scripts": _readable_scripts(
			"Server Script",
			{"script_type": "DocType Event", "reference_doctype": doctype, "disabled": 0},
		),
		"client_scripts": _readable_scripts("Client Script", {"dt": doctype, "enabled": 1}),
	}


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
	"get_doctype_logic": get_doctype_logic,
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
