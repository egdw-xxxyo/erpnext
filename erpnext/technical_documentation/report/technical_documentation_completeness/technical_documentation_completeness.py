# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""Completeness of every documentation package at once, recomputed on each run.

The register keeps no completeness column, so this report cannot read one. It calls the
same `get_completeness` the document form calls, once per document, which is why a
figure here and a figure on the card can never disagree — the alternative, a faster query
over a stored percentage, is precisely the mirror table that drifted on dev.

Only types marked `requires_completeness` are listed: for a contract or an order there is
no package to be complete. Within those, a document with no template attached is listed
rather than skipped, with the missing template named as its problem — an unmeasured
specification is a gap in the register, and a report that quietly drops it would hide the
one thing worth seeing.

Rows come from `frappe.get_list`, so section access applies: two people run the report
and see the documents they may see. The percentage of a document they may see is whole,
because `get_completeness` deliberately reads the related documents permissions aside.
"""

import frappe
from frappe import _

from erpnext.technical_documentation.completeness import get_completeness
from erpnext.technical_documentation.constants import (
	COMPLETENESS_PRESENT,
	DOCUMENT_DOCTYPE,
	SECTION_DOCTYPE,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{
			"label": _("Document"),
			"fieldname": "document",
			"fieldtype": "Link",
			"options": DOCUMENT_DOCTYPE,
			"width": 160,
		},
		{"label": _("Title"), "fieldname": "document_title", "fieldtype": "Data", "width": 260},
		{
			"label": _("Document Type"),
			"fieldname": "document_type",
			"fieldtype": "Link",
			"options": "Technical Document Type",
			"width": 160,
		},
		{
			"label": _("Section"),
			"fieldname": "section",
			"fieldtype": "Link",
			"options": SECTION_DOCTYPE,
			"width": 140,
		},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 110},
		{
			"label": _("Responsible"),
			"fieldname": "responsible",
			"fieldtype": "Link",
			"options": "User",
			"width": 160,
		},
		{"label": _("Mandatory documents"), "fieldname": "required", "fieldtype": "Int", "width": 130},
		{"label": _("Documents present"), "fieldname": "present", "fieldtype": "Int", "width": 130},
		{
			"label": _("Completeness"),
			"fieldname": "completeness",
			"fieldtype": "Percent",
			"width": 120,
		},
		{"label": _("Problems"), "fieldname": "issues", "fieldtype": "Small Text", "width": 340},
	]


def get_data(filters):
	rows = [build_row(document) for document in get_documents(filters)]

	if filters.only_incomplete:
		return [row for row in rows if row["completeness"] < 100]

	return rows


def get_documents(filters):
	document_types = measurable_types(filters.document_type)
	if not document_types:
		return []

	conditions = {"document_type": ("in", document_types)}
	for field in ("section", "status", "responsible"):
		if filters.get(field):
			conditions[field] = filters[field]

	return frappe.get_list(
		DOCUMENT_DOCTYPE,
		filters=conditions,
		fields=[
			"name",
			"document_title",
			"document_type",
			"section",
			"status",
			"responsible",
			"requirement_template",
		],
		order_by="section asc, name asc",
		limit_page_length=0,
	)


def measurable_types(document_type):
	"""A package exists only for types that declare one; a filtered type still has to be one."""
	types = frappe.get_all("Technical Document Type", filters={"requires_completeness": 1}, pluck="name")

	if not document_type:
		return types

	return [document_type] if document_type in types else []


def build_row(document):
	row = {
		"document": document.name,
		"document_title": document.document_title,
		"document_type": document.document_type,
		"section": document.section,
		"status": document.status,
		"responsible": document.responsible,
		"required": 0,
		"present": 0,
		"completeness": 0,
	}

	if not document.requirement_template:
		return {**row, "issues": _("Completeness template is not set")}

	result = get_completeness(document.name)
	required, present = result["required"], result["present"]

	return {
		**row,
		"required": required,
		"present": present,
		"completeness": 100 if not required else round(present * 100 / required, 1),
		"issues": describe_issues(result["rows"]),
	}


def describe_issues(rows):
	return "; ".join(
		f"{row['document_type']} — {row['state']}"
		for row in rows
		if row["mandatory"] and row["state"] != COMPLETENESS_PRESENT
	)
