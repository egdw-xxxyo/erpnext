# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""Writes the attribute line onto modifications that were saved before the field existed.

The field is derived on save, so without this pass the column stays empty for every
modification already in the register until someone opens and saves it one by one.
"""

import frappe

from erpnext.technical_documentation.attributes import ATTRIBUTE_ROW_DOCTYPE, build_summary
from erpnext.technical_documentation.constants import MODIFICATION_DOCTYPE


def execute():
	grouped = {}
	for row in frappe.get_all(
		ATTRIBUTE_ROW_DOCTYPE,
		filters={"parenttype": MODIFICATION_DOCTYPE},
		fields=["parent", "attribute", "attribute_value"],
		order_by="parent, idx",
	):
		grouped.setdefault(row.parent, []).append(row)

	for name in frappe.get_all(MODIFICATION_DOCTYPE, pluck="name"):
		frappe.db.set_value(
			MODIFICATION_DOCTYPE,
			name,
			"attribute_summary",
			build_summary(grouped.get(name, [])),
			update_modified=False,
		)
