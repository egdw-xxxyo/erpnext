import frappe

from erpnext.manufacturing.eskd_import import DOCUMENT_TYPES


def execute():
	"""Seed the ЄСКД document types used by the ESKD Document register."""
	for row in DOCUMENT_TYPES:
		if frappe.db.exists("ESKD Document Type", row["type_name"]):
			continue
		frappe.get_doc({"doctype": "ESKD Document Type", **row}).insert(ignore_permissions=True)
