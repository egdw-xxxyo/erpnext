import json
import re
from collections.abc import Mapping

DOCTYPE_METHODS = {
	"frappe.desk.form.load.getdoc": "read",
	"frappe.desk.form.load.getdoctype": "read",
	"frappe.desk.form.load.get_docinfo": "read",
	"frappe.client.get": "read",
	"frappe.client.get_value": "read",
	"frappe.client.get_list": "read",
	"frappe.client.get_count": "read",
	"frappe.desk.reportview.get": "read",
	"frappe.desk.reportview.get_list": "read",
	"frappe.desk.reportview.get_count": "read",
	"frappe.desk.reportview.get_sidebar_stats": "read",
	"frappe.desk.listview.get_list_settings": "read",
	"frappe.desk.search.search_link": "select",
	"frappe.desk.search.search_widget": "select",
	"frappe.desk.reportview.export_query": "export",
	"frappe.client.set_value": "write",
	"frappe.client.delete": "delete",
	"frappe.desk.reportview.delete_items": "delete",
	"frappe.desk.form.save.cancel": "cancel",
	"frappe.client.cancel": "cancel",
	"frappe.client.submit": "submit",
	"frappe.share.add": "share",
	"frappe.core.doctype.communication.email.make": "email",
}

SAVE_ACTIONS = {"Save": "write", "Update": "write", "Submit": "submit", "Cancel": "cancel"}

REPORT_METHODS = frozenset(
	{
		"frappe.desk.query_report.get_script",
		"frappe.desk.query_report.run",
		"frappe.desk.query_report.export_query",
	}
)

SPECIAL_METHODS = frozenset(
	{
		"frappe.desk.form.save.savedocs",
		"frappe.client.save",
		"frappe.client.insert",
		"frappe.desk.desk_page.getpage",
		"frappe.www.printview.get_html_and_style",
	}
)

KNOWN_METHODS = frozenset(DOCTYPE_METHODS) | REPORT_METHODS | SPECIAL_METHODS

RESOURCE_PTYPES = {"GET": "read", "PUT": "write", "PATCH": "write", "DELETE": "delete", "POST": "create"}

METHOD_PATH = re.compile(r"^/api/(?:v\d+/)?method/([\w.]+)")
RESOURCE_PATH = re.compile(r"^/api/(?:resource|v\d+/document)/([^/]+)(?:/([^/]+))?")


def decode(value):
	if isinstance(value, str) and value[:1] in ("{", "["):
		try:
			return json.loads(value)
		except ValueError:
			return value
	return value


def doctype_context(doctype, name, ptype: str) -> dict | None:
	if not doctype or not isinstance(doctype, str):
		return None
	return {
		"kind": "doctype",
		"doctype": doctype,
		"name": name if isinstance(name, str) and name else None,
		"ptype": ptype,
	}


def _saved_doc_context(doc, action: str | None) -> dict | None:
	if not isinstance(doc, Mapping):
		return None
	is_new = bool(doc.get("__islocal")) or not doc.get("name")
	ptype = "create" if is_new else SAVE_ACTIONS.get(action or "Save", "write")
	return doctype_context(doc.get("doctype"), None if is_new else doc.get("name"), ptype)


def _first_item(items):
	decoded = decode(items)
	return decoded[0] if isinstance(decoded, list) and decoded else None


def method_context(method: str, params: Mapping) -> dict | None:
	if method in ("frappe.desk.form.save.savedocs", "frappe.client.save", "frappe.client.insert"):
		action = params.get("action") if method == "frappe.desk.form.save.savedocs" else None
		return _saved_doc_context(decode(params.get("doc")), action)
	if method == "frappe.desk.desk_page.getpage":
		return {"kind": "page_or_doctype", "slug": params.get("name")} if params.get("name") else None
	if method in REPORT_METHODS:
		report = params.get("report_name")
		return {"kind": "report", "report": report} if report else None
	if method == "frappe.www.printview.get_html_and_style":
		return doctype_context(params.get("doc"), params.get("name"), "print")
	if method == "frappe.desk.reportview.delete_items":
		return doctype_context(params.get("doctype"), _first_item(params.get("items")), "delete")
	ptype = DOCTYPE_METHODS.get(method, "read")
	name = params.get("name") or params.get("docname")
	return doctype_context(params.get("doctype"), name, ptype)


def denial_context(path: str, http_method: str, params: Mapping) -> dict | None:
	params = params or {}
	method_match = METHOD_PATH.match(path or "")
	method = method_match.group(1) if method_match else params.get("cmd")
	if method:
		context = method_context(method, params)
		return {**context, "method": method} if context else {"kind": "other", "method": method}
	resource_match = RESOURCE_PATH.match(path or "")
	if resource_match:
		doctype, name = resource_match.groups()
		return doctype_context(doctype, name, RESOURCE_PTYPES.get((http_method or "GET").upper(), "read"))
	return None


def with_raised(context: dict | None, raised: dict | None) -> dict | None:
	method = (context or {}).get("method")
	if not raised or (context and (not method or method in KNOWN_METHODS)):
		return context
	return {**raised, "method": method} if method else raised


def slug_to_name(slug: str) -> str:
	return (slug or "").replace("-", " ")
