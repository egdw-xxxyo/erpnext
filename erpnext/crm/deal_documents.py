# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Deal documents: files attached to an Opportunity are surfaced read-through on
its linked Quotation and Sales Order so they are never duplicated by hand."""

import frappe


def get_opportunity_for(doctype, docname):
	"""Resolve the deal (Opportunity) that owns this document."""
	if doctype == "Opportunity":
		return docname
	if doctype == "Quotation":
		return frappe.db.get_value("Quotation", docname, "opportunity")
	if doctype == "Sales Order":
		quotations = frappe.get_all(
			"Sales Order Item",
			filters={"parent": docname, "prevdoc_docname": ["is", "set"]},
			pluck="prevdoc_docname",
		)
		for q in quotations:
			opp = frappe.db.get_value("Quotation", q, "opportunity")
			if opp:
				return opp
	return None


@frappe.whitelist()
def get_deal_documents(doctype, docname):
	"""Return the Opportunity and its File attachments for the given CRM document."""
	opportunity = get_opportunity_for(doctype, docname)
	if not opportunity:
		return {"opportunity": None, "files": []}

	files = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Opportunity", "attached_to_name": opportunity},
		fields=["name", "file_name", "file_url", "is_private"],
		order_by="creation desc",
	)
	return {"opportunity": opportunity, "files": files}
