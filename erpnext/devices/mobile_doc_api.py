# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Document card for the mobile app: any document as a ready-to-draw view model.

A notification on the phone points at a document of an arbitrary doctype. Shipping the doctype
schema and the raw document would make the app re-implement Frappe's formatters, permission
levels and translations in Kotlin, and drift from them with every doctype change. So the server
does all of that here and hands back plain labelled strings grouped the way the form groups
them; the app draws blocks and knows nothing about any doctype. A new or changed doctype works
on the builds already installed.

Read-only. The `actions` list is reserved for workflow / submit buttons.

A doctype whose automatic card reads badly can register a shaper in hooks:

    mobile_document_card = {"Material Request": "erpnext.stock.mobile_cards.material_request"}

It is called as `fn(doc, card)` after the card is built and may edit it in place or return a
replacement.
"""

import html
import re

import frappe
from frappe import _
from frappe.model import display_fieldtypes, no_value_fields
from frappe.model.workflow import get_workflow_name, get_workflow_state_field
from frappe.utils import cint, cstr, get_url, get_url_to_form, strip_html_tags

MAX_TABLE_ROWS = 50
MAX_TABLE_COLUMNS = 6
MAX_TEXT = 2000

SKIPPED_FIELDTYPES = {
	*display_fieldtypes,
	*no_value_fields,
	"Password",
	"Code",
	"JSON",
	"HTML Editor",
	"Signature",
	"Geolocation",
	"Icon",
}
LONG_TEXT_FIELDTYPES = {"Text", "Small Text", "Long Text", "Text Editor", "Markdown Editor"}
TABLE_FIELDTYPES = {"Table", "Table MultiSelect"}

DOCSTATUS_LABELS = {0: ("Draft", "red"), 1: ("Submitted", "blue"), 2: ("Cancelled", "red")}
WORKFLOW_STYLE_COLORS = {
	"Primary": "blue",
	"Info": "blue",
	"Success": "green",
	"Warning": "orange",
	"Danger": "red",
	"Inverse": "gray",
}
STATUS_COLORS = (
	("green", ("completed", "paid", "received", "delivered", "approved", "ordered", "closed", "active")),
	("red", ("cancel", "reject", "overdue", "lost", "failed", "stopped", "expired")),
	("orange", ("pending", "partial", "open", "to ", "hold", "progress", "unpaid", "draft")),
)


@frappe.whitelist()
def get_document_card(doctype: str, name: str, full: int | str = 0):
	"""Everything the app needs to show one document. `full=1` lifts the "important fields
	only" filter; the card says through `has_more` whether that would add anything."""
	if not frappe.db.exists("DocType", doctype):
		frappe.throw(_("Unknown document type {0}").format(doctype), frappe.DoesNotExistError)

	meta = frappe.get_meta(doctype)
	if meta.istable:
		frappe.throw(_("{0} cannot be opened on its own").format(_(doctype)), frappe.PermissionError)

	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	doc.apply_fieldlevel_read_permissions()

	full = bool(cint(full))
	sections, tables, has_more = _body(doc, meta, full)
	card = {
		"doctype": doctype,
		"doctype_label": _(doctype),
		"name": doc.name,
		"title": _plain(doc.get_title()) or cstr(doc.name),
		"status": _status(doc, meta),
		"modified": frappe.format_value(doc.modified, "Datetime"),
		"web_url": get_url_to_form(doctype, doc.name),
		"full": full,
		"has_more": has_more,
		"sections": sections,
		"tables": tables,
		"actions": [],
	}

	for shaper in frappe.get_hooks("mobile_document_card", {}).get(doctype, []):
		card = frappe.get_attr(shaper)(doc, card) or card
	return card


def _plain(value) -> str:
	"""Formatter output as text: tags dropped, line breaks kept, runs of blanks collapsed."""
	text = cstr(value)
	if "<" in text:
		text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", text)
		text = strip_html_tags(text)
	text = html.unescape(text)
	text = re.sub(r"[ \t\r\f\v]+", " ", text)
	text = re.sub(r"\s*\n\s*", "\n", text).strip()
	return text[:MAX_TEXT]


def _important(df, meta, status_field) -> bool:
	return bool(
		df.reqd
		or df.in_list_view
		or df.in_standard_filter
		or df.bold
		or df.fieldname in (meta.title_field, status_field, "status")
	)


def _can_open(doctype: str | None) -> bool:
	"""Whether a link to this doctype is worth a tap. The card itself re-checks the document."""
	if not doctype or not frappe.db.exists("DocType", doctype):
		return False
	target = frappe.get_meta(doctype)
	return not target.istable and not target.issingle and frappe.has_permission(doctype, "read")


def _link_target(df, doc) -> str | None:
	return doc.get(df.options) if df.fieldtype == "Dynamic Link" else df.options


def _link_title(doctype: str, name) -> str:
	meta = frappe.get_meta(doctype)
	if not meta.show_title_field_in_link or not meta.title_field:
		return cstr(name)
	return cstr(frappe.db.get_value(doctype, name, meta.title_field) or name)


def _field(df, doc) -> dict | None:
	"""One labelled value, or None when there is nothing to show."""
	value = doc.get(df.fieldname)
	if value in (None, "", 0, 0.0) or (df.fieldtype == "Check" and not cint(value)):
		return None

	entry = {"label": _(df.label or df.fieldname), "type": "text"}

	if df.fieldtype in ("Link", "Dynamic Link"):
		target = _link_target(df, doc)
		if target and frappe.db.exists("DocType", target):
			entry["value"] = _plain(_link_title(target, value))
			if _can_open(target):
				entry["type"] = "link"
				entry["link"] = {"doctype": target, "name": cstr(value)}
		else:
			entry["value"] = _plain(value)
	elif df.fieldtype == "Check":
		entry["type"] = "check"
		entry["value"] = _("Yes")
	elif df.fieldtype in ("Attach", "Attach Image"):
		entry["type"] = "image" if df.fieldtype == "Attach Image" else "attachment"
		entry["value"] = cstr(value).rsplit("/", 1)[-1]
		entry["url"] = get_url(cstr(value)) if cstr(value).startswith("/") else cstr(value)
	elif df.fieldtype == "Select":
		entry["value"] = _plain(_(cstr(value)))
	else:
		if df.fieldtype in LONG_TEXT_FIELDTYPES:
			entry["type"] = "long_text"
		entry["value"] = _plain(frappe.format_value(value, df, doc))

	return entry if entry["value"] else None


def _table(df, doc) -> dict | None:
	rows = doc.get(df.fieldname) or []
	if not rows:
		return None

	child_meta = frappe.get_meta(df.options)
	columns = [
		col
		for col in child_meta.fields
		if col.fieldtype not in SKIPPED_FIELDTYPES and not col.hidden and col.in_list_view
	][:MAX_TABLE_COLUMNS]
	if not columns:
		return None

	body = []
	for row in rows[:MAX_TABLE_ROWS]:
		cells = [_field(col, row) for col in columns]
		body.append([cell["value"] if cell else "" for cell in cells])

	return {
		"label": _(df.label or df.fieldname),
		"columns": [_(col.label or col.fieldname) for col in columns],
		"rows": body,
		"total": len(rows),
	}


def _body(doc, meta, full: bool):
	"""Sections and tables in form order. Compact mode keeps the fields the doctype itself
	marks as important and one table; whatever it leaves out raises `has_more`."""
	workflow = get_workflow_name(meta.name)
	status_field = get_workflow_state_field(workflow) if workflow else None

	sections, tables, skipped_tables = [], [], []
	current = {"label": "", "fields": []}
	has_more = False

	for df in meta.fields:
		if df.fieldtype in ("Section Break", "Tab Break"):
			if current["fields"]:
				sections.append(current)
			current = {"label": _(df.label) if df.label else "", "fields": []}
			continue
		if df.hidden:
			continue

		if df.fieldtype in TABLE_FIELDTYPES:
			table = _table(df, doc)
			if not table:
				continue
			if full or df.reqd:
				tables.append(table)
			else:
				skipped_tables.append(table)
			continue

		if df.fieldtype in SKIPPED_FIELDTYPES:
			continue
		entry = _field(df, doc)
		if not entry:
			continue
		if full or _important(df, meta, status_field):
			current["fields"].append(entry)
		else:
			has_more = True

	if current["fields"]:
		sections.append(current)

	if skipped_tables and not tables:
		tables.append(skipped_tables.pop(0))
	return sections, tables, has_more or bool(skipped_tables)


def _status(doc, meta) -> dict:
	"""The one word the form's indicator pill shows: workflow state, else `status`, else
	docstatus."""
	workflow = get_workflow_name(meta.name)
	if workflow:
		state = doc.get(get_workflow_state_field(workflow))
		if state:
			style = frappe.db.get_value("Workflow State", state, "style")
			return {"label": _(state), "color": WORKFLOW_STYLE_COLORS.get(style, "gray")}

	status = doc.get("status") if meta.has_field("status") else None
	if status:
		lowered = cstr(status).lower()
		color = next((c for c, words in STATUS_COLORS if any(w in lowered for w in words)), "gray")
		return {"label": _(cstr(status)), "color": color}

	if meta.is_submittable:
		label, color = DOCSTATUS_LABELS.get(cint(doc.docstatus), DOCSTATUS_LABELS[0])
		return {"label": _(label), "color": color}
	return {}
