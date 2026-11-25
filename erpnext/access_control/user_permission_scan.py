import frappe
from frappe import _
from frappe.permissions import get_user_permissions

from erpnext.access_control import permission_rules as rules

PREVIEW_LIMIT = 5000


def _restricted_fields(doctype: str, allows) -> list:
	return [
		field
		for field in frappe.get_meta(doctype).get_link_fields()
		if field.options in allows and not field.ignore_user_permissions
	]


def _row_links(row, table: str | None) -> list[dict]:
	return [
		{
			"allow": field.options,
			"value": row.get(field.fieldname),
			"field": _(field.label or field.fieldname),
			"table": table,
			"row": row.idx if table else None,
		}
		for field in frappe.get_meta(row.doctype).get_link_fields()
		if field.options and not field.ignore_user_permissions
	]


def document_links(doc) -> list[dict]:
	tables = {field.fieldname: _(field.label or field.fieldname) for field in doc.meta.get_table_fields()}
	return [
		{"allow": doc.doctype, "value": doc.name, "field": _(doc.doctype), "table": None, "row": None},
		*_row_links(doc, None),
		*(link for row in doc.get_all_children() for link in _row_links(row, tables.get(row.parentfield))),
	]


def allowed_for(user: str, doctype: str) -> dict[str, list[str]]:
	allowed = {
		allow: rules.allowed_values(entries, doctype) for allow, entries in get_user_permissions(user).items()
	}
	return {allow: values for allow, values in allowed.items() if values}


def blocks(doc, user: str) -> list[dict]:
	return rules.user_permission_blocks(document_links(doc), allowed_for(user, doc.doctype))


def _parent_values(doctype: str, names: list[str], allows) -> list[tuple[str, str, str]]:
	fields = _restricted_fields(doctype, allows)
	if not fields:
		return []
	rows = frappe.get_all(
		doctype,
		filters={"name": ["in", names]},
		fields=["name", *(field.fieldname for field in fields)],
	)
	return [
		(row.name, field.options, row.get(field.fieldname))
		for row in rows
		for field in fields
		if row.get(field.fieldname)
	]


def _child_values(doctype: str, names: list[str], allows) -> list[tuple[str, str, str]]:
	return [
		(row.parent, field.options, row.get(field.fieldname))
		for table in frappe.get_meta(doctype).get_table_fields()
		for fields in (_restricted_fields(table.options, allows),)
		if fields
		for row in frappe.get_all(
			table.options,
			filters={"parenttype": doctype, "parentfield": table.fieldname, "parent": ["in", names]},
			fields=["parent", *(field.fieldname for field in fields)],
		)
		for field in fields
		if row.get(field.fieldname)
	]


def doctype_values(doctype: str, allows) -> tuple[dict[str, set[tuple[str, str]]], bool]:
	names = frappe.get_all(
		doctype,
		filters={"docstatus": ["!=", 2]},
		order_by="modified desc",
		limit=PREVIEW_LIMIT + 1,
		pluck="name",
	)
	limited = len(names) > PREVIEW_LIMIT
	names = names[:PREVIEW_LIMIT]
	documents = {name: {(doctype, name)} if doctype in allows else set() for name in names}
	if names:
		for name, allow, value in [
			*_parent_values(doctype, names, allows),
			*_child_values(doctype, names, allows),
		]:
			documents[name].add((allow, value))
	return documents, limited


def preview(doctype: str, user: str, granted) -> dict:
	allowed = allowed_for(user, doctype)
	if not allowed:
		return {"total": 0, "blocked_now": 0, "blocked_after": 0, "remaining": [], "limited": False}
	documents, limited = doctype_values(doctype, set(allowed))
	return {**rules.user_permission_preview(documents, allowed, granted), "limited": limited}
