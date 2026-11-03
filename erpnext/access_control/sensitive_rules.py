import re
from collections.abc import Mapping

from erpnext.access_control import denial_rules

PIN_PATTERN = re.compile(r"^\d{6}$")
DIGITS = "0123456789"

RESERVED_DOCTYPES = frozenset(
	{
		"User",
		"Role",
		"Role Profile",
		"Has Role",
		"DocType",
		"DocField",
		"DocPerm",
		"Custom DocPerm",
		"Custom Field",
		"Property Setter",
		"Module Def",
		"Page",
		"Report",
		"File",
		"System Settings",
		"Session Default Settings",
		"Access Request",
		"Sensitive Data PIN",
		"Sensitive Access Log",
	}
)

SETTINGS_DOCTYPE = "Sensitive Data Settings"

RUN_DOC_METHODS = frozenset({"run_doc_method", "frappe.handler.run_doc_method"})

RELOAD_METHODS = frozenset(
	{
		"frappe.desk.form.load.getdoc",
		"frappe.desk.form.load.getdoctype",
		"frappe.desk.desk_page.getpage",
		"frappe.desk.query_report.get_script",
		"frappe.desk.query_report.run",
		"frappe.desk.reportview.get",
		"frappe.desk.reportview.get_list",
		"frappe.desk.reportview.get_count",
		"frappe.desk.listview.get_list_settings",
	}
)


def pin_refusal(pin) -> str | None:
	if not isinstance(pin, str) or not PIN_PATTERN.match(pin):
		return "format"
	if len(set(pin)) == 1 or pin in DIGITS or pin in DIGITS[::-1]:
		return "weak"
	return None


def method_prefixes(objects: list[dict], module_paths: Mapping, hook_methods: Mapping) -> list[tuple]:
	derived = [
		(f"{module_paths[(row['object_type'], row['object_name'])]}.", row["object_type"], row["object_name"])
		for row in objects
		if module_paths.get((row["object_type"], row["object_name"]))
	]
	protected = {row["object_name"]: row["object_type"] for row in objects}
	declared = [
		(prefix, protected[name], name)
		for name, prefixes in hook_methods.items()
		if name in protected
		for prefix in prefixes
	]
	return sorted(derived + declared, key=lambda entry: -len(entry[0]))


def build_config(
	settings: Mapping, objects: list[dict], fields: list[dict], children: Mapping, extra
) -> dict:
	by_type = {
		kind: {
			row["object_name"]: row.get("unlock_minutes") or None
			for row in objects
			if row["object_type"] == kind
		}
		for kind in ("DocType", "Report", "Page")
	}
	doctypes = {**by_type["DocType"], SETTINGS_DOCTYPE: None}
	return {
		"enabled": bool(int(settings.get("enabled") or 0)),
		"unlock_minutes": int(settings.get("unlock_minutes") or 30),
		"idle_minutes": int(settings.get("idle_minutes") or 0),
		"max_attempts": int(settings.get("max_attempts") or 5),
		"doctypes": doctypes,
		"reports": by_type["Report"],
		"pages": by_type["Page"],
		"children": {
			child: parent
			for parent in doctypes
			for child in children.get(parent, ())
			if child not in doctypes
		},
		"fields": {
			doctype: sorted(row["fieldname"] for row in fields if row["document_type"] == doctype)
			for doctype in {row["document_type"] for row in fields}
		},
		"methods": [list(entry) for entry in extra.get("methods", [])],
		"api_users": sorted(extra.get("api_users", [])),
	}


def protected_doctype(config: Mapping, doctype) -> str | None:
	if not doctype or not isinstance(doctype, str):
		return None
	if doctype in config["doctypes"]:
		return doctype
	return config["children"].get(doctype)


def object_minutes(config: Mapping, target: tuple | None) -> int:
	if not target:
		return config["unlock_minutes"]
	kind, name = target
	table = {"DocType": "doctypes", "Report": "reports", "Page": "pages"}.get(kind)
	return (table and config[table].get(name)) or config["unlock_minutes"]


def method_target(config: Mapping, method) -> tuple | None:
	if not method:
		return None
	return next(
		((kind, name) for prefix, kind, name in config["methods"] if method.startswith(prefix)),
		None,
	)


def _run_doc_doctype(params: Mapping):
	docs = denial_rules.decode(params.get("docs"))
	if isinstance(docs, Mapping):
		return docs.get("doctype")
	return params.get("dt")


def context_target(config: Mapping, context: Mapping | None) -> tuple | None:
	if not context:
		return None
	kind = context.get("kind")
	if kind == "doctype":
		doctype = protected_doctype(config, context.get("doctype"))
		return ("DocType", doctype) if doctype else None
	if kind == "report":
		return ("Report", context["report"]) if context.get("report") in config["reports"] else None
	if kind == "page":
		return ("Page", context["page"]) if context.get("page") in config["pages"] else None
	if kind == "page_or_doctype":
		slug = context.get("slug") or ""
		if slug in config["pages"]:
			return ("Page", slug)
		doctype = protected_doctype(config, doctype_by_slug(config, slug))
		return ("DocType", doctype) if doctype else None
	return None


def slug(name: str) -> str:
	return name.lower().replace(" ", "-")


def doctype_by_slug(config: Mapping, value: str) -> str | None:
	names = [*config["doctypes"], *config["children"]]
	return next((name for name in names if slug(name) == value), None)


def request_target(config: Mapping, path: str, http_method: str, params: Mapping) -> tuple | None:
	context = denial_rules.denial_context(path, http_method, params)
	method = (context or {}).get("method")
	if method in RUN_DOC_METHODS:
		doctype = protected_doctype(config, _run_doc_doctype(params or {}))
		return ("DocType", doctype) if doctype else None
	return context_target(config, context) or method_target(config, method)


def retry_mode(path: str, params: Mapping) -> str:
	context = denial_rules.denial_context(path, "GET", params or {}) or {}
	return "reload" if context.get("method") in RELOAD_METHODS else "repeat"


def unlock_end(state: Mapping, minutes: int, idle_minutes: int) -> tuple[float, str]:
	by_time = state["since"] + minutes * 60
	by_idle = state["seen"] + idle_minutes * 60 if idle_minutes else None
	return (by_idle, "idle") if by_idle is not None and by_idle < by_time else (by_time, "time")


def unlocked_until(state: Mapping | None, now: float, minutes: int, idle_minutes: int) -> float | None:
	if not state:
		return None
	until, _reason = unlock_end(state, minutes, idle_minutes)
	return until if until > now else None


def longest_minutes(config: Mapping) -> int:
	return max(
		[config["unlock_minutes"]]
		+ [
			minutes
			for table in ("doctypes", "reports", "pages")
			for minutes in config[table].values()
			if minutes
		]
	)


SETTING_FIELDS = ("enabled", "unlock_minutes", "idle_minutes", "max_attempts")
SETTING_TABLES = {
	"objects": ("object_type", "object_name"),
	"fields": ("document_type", "fieldname"),
	"api_users": ("user",),
}


def _table_rows(doc: Mapping, table: str) -> dict:
	key = SETTING_TABLES[table]
	return {tuple(row.get(part) for part in key): row for row in doc.get(table) or ()}


def _entry(row: Mapping, table: str) -> dict:
	return {part: row.get(part) for part in (*SETTING_TABLES[table], "label")}


def settings_delta(before: Mapping | None, after: Mapping) -> dict:
	before = before or {}
	delta = {
		field: [before.get(field), after.get(field)]
		for field in SETTING_FIELDS
		if (before.get(field) or 0) != (after.get(field) or 0)
	}
	for table in SETTING_TABLES:
		old, new = _table_rows(before, table), _table_rows(after, table)
		added = [_entry(new[key], table) for key in sorted(new.keys() - old.keys())]
		removed = [_entry(old[key], table) for key in sorted(old.keys() - new.keys())]
		if added:
			delta[f"{table}_added"] = added
		if removed:
			delta[f"{table}_removed"] = removed
	old_objects = _table_rows(before, "objects")
	minutes = [
		{
			**_entry(row, "objects"),
			"was": old_objects[key].get("unlock_minutes"),
			"now": row.get("unlock_minutes"),
		}
		for key, row in _table_rows(after, "objects").items()
		if key in old_objects
		and (old_objects[key].get("unlock_minutes") or 0) != (row.get("unlock_minutes") or 0)
	]
	if minutes:
		delta["objects_minutes"] = minutes
	return delta


def after_failure(failed: int, max_attempts: int) -> tuple[int, bool]:
	failed = (failed or 0) + 1
	return failed, bool(max_attempts) and failed >= max_attempts
