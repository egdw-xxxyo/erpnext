# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""What the document form shows about everything that hangs off the document.

The prototype assembled these panels in the browser out of four generic `frappe.client`
calls and joined them there. Moving the assembly to the server is not a performance
preference: the panels have to agree with the rules the register enforces, and the only
way to keep them in agreement is to read them from the same place those rules live —
completeness in particular is computed by the module that the report also calls, never
recomputed in JavaScript.

Each panel is read with `frappe.get_list`, never `get_all`: `get_all` skips permissions
entirely, which would make these panels the one place in the register where section access
does not apply. With `get_list` the delegating rules run, and a user who may not see a
revision does not see it here either — the panel shrinks instead of leaking a row the list
view would have hidden.

Relations are returned in both directions. A methodology referenced from three
specifications has to be reachable from the methodology's own card, and the relation rows
only ever record one side.
"""

import frappe

from erpnext.technical_documentation.completeness import get_completeness
from erpnext.technical_documentation.constants import (
	DOCUMENT_DOCTYPE,
	MODIFICATION_DOCTYPE,
	RELATION_DOCTYPE,
	REVISION_DOCTYPE,
	REVISION_EFFECTIVE,
)

RELATED_FIELDS = (
	"name",
	"document_code",
	"document_title",
	"document_type",
	"status",
	"current_revision",
	"current_revision_effective_date",
)


@frappe.whitelist()
def get_panels(document: str) -> dict:
	frappe.has_permission(DOCUMENT_DOCTYPE, doc=document, throw=True)

	return {
		"revisions": get_revisions(document),
		"relations": get_relations(document),
		"modifications": get_modifications(document),
		"completeness": get_completeness(document),
	}


def get_revisions(document):
	revisions = frappe.get_list(
		REVISION_DOCTYPE,
		filters={"technical_document": document},
		fields=[
			"name",
			"revision_number",
			"revision_title",
			"revision_status",
			"docstatus",
			"creation_date",
			"effective_date",
			"end_date",
			"change_basis",
			"change_description",
			"word_file",
			"pdf_file",
			"signed_scan",
			"additional_attachment",
		],
		order_by="effective_date desc, creation_date desc, name desc",
		limit_page_length=0,
	)

	current = frappe.db.get_value(DOCUMENT_DOCTYPE, document, "current_revision")
	for revision in revisions:
		revision["is_current"] = revision.name == current

	return {
		"rows": revisions,
		"total": len(revisions),
		"effective": sum(1 for row in revisions if row.revision_status == REVISION_EFFECTIVE),
		"current": current,
	}


def get_relations(document):
	return {
		"outgoing": read_relations("main_document", "related_document", document),
		"incoming": read_relations("related_document", "main_document", document),
	}


def read_relations(own_field, other_field, document):
	rows = frappe.get_list(
		RELATION_DOCTYPE,
		filters={own_field: document},
		fields=["name", other_field, "relation_type", "note"],
		order_by="relation_type, creation",
		limit_page_length=0,
	)
	if not rows:
		return []

	documents = {
		row.name: row
		for row in frappe.get_list(
			DOCUMENT_DOCTYPE,
			filters={"name": ("in", [row.get(other_field) for row in rows])},
			fields=RELATED_FIELDS,
			limit_page_length=0,
		)
	}

	related = []
	for row in rows:
		document_row = documents.get(row.get(other_field))
		if not document_row:
			continue

		related.append(
			{"relation": row.name, "relation_type": row.relation_type, "note": row.note, **document_row}
		)

	return related


def get_modifications(document):
	modifications = frappe.get_list(
		MODIFICATION_DOCTYPE,
		filters={"technical_document": document},
		fields=[
			"name",
			"modification_code",
			"full_name",
			"status",
			"product_type",
			"product_subtype",
			"nsn_code",
			"nsn_date",
		],
		order_by="modification_code",
		limit_page_length=0,
	)

	attributes = read_attributes([row.name for row in modifications])
	for row in modifications:
		row["attributes"] = attributes.get(row.name, [])

	return {
		"rows": modifications,
		"total": len(modifications),
		"codified": sum(1 for row in modifications if row.nsn_code),
	}


def read_attributes(modifications):
	"""The attribute values of several modifications, read in one query and grouped."""
	if not modifications:
		return {}

	grouped = {}
	for row in frappe.get_all(
		"Product Modification Attribute",
		filters={"parenttype": MODIFICATION_DOCTYPE, "parent": ("in", modifications)},
		fields=["parent", "attribute", "attribute_value"],
		order_by="parent, idx",
	):
		grouped.setdefault(row.parent, []).append({"attribute": row.attribute, "value": row.attribute_value})

	return grouped
