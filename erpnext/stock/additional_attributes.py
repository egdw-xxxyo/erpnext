# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Generic validation for the reusable ``Additional Attribute Row`` child table.

Any DocType can carry per-record key/value metadata by adding a Table Custom Field with
``options = "Additional Attribute Row"``. This module keeps those rows consistent:
the picked value must belong to the picked attribute, and neither may be disabled.

Wired in hooks.py as ``doc_events["*"]["validate"]`` — it exits immediately for documents
that have no such table.
"""

import frappe
from frappe import _

ROW_DOCTYPE = "Additional Attribute Row"


def validate_additional_attributes(doc, method=None):
	if doc.doctype in (ROW_DOCTYPE, "Additional Attribute", "Additional Attribute Value"):
		return

	rows = []
	for df in doc.meta.get_table_fields():
		if df.options == ROW_DOCTYPE:
			rows.extend(doc.get(df.fieldname) or [])

	if not rows:
		return

	for row in rows:
		if not row.attribute or not row.value:
			continue

		value = frappe.db.get_value(
			"Additional Attribute Value", row.value, ["attribute", "disabled"], as_dict=True
		)
		if not value:
			frappe.throw(
				_("Row {0}: Additional Attribute Value {1} does not exist").format(
					row.idx, frappe.bold(row.value)
				)
			)

		if value.attribute != row.attribute:
			frappe.throw(
				_("Row {0}: Value {1} belongs to attribute {2}, not {3}").format(
					row.idx, frappe.bold(row.value), frappe.bold(value.attribute), frappe.bold(row.attribute)
				)
			)

		if value.disabled:
			frappe.throw(_("Row {0}: Value {1} is disabled").format(row.idx, frappe.bold(row.value)))

		if frappe.db.get_value("Additional Attribute", row.attribute, "disabled"):
			frappe.throw(_("Row {0}: Attribute {1} is disabled").format(row.idx, frappe.bold(row.attribute)))
