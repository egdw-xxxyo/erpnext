# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ItemSpecification(Document):
	def validate(self):
		seen = set()
		for row in self.parameters:
			if row.parameter in seen:
				frappe.throw(f"Duplicate parameter: {row.parameter}. Each parameter can only appear once.")
			seen.add(row.parameter)


@frappe.whitelist()
def get_spec_for_item(item_code):
	"""Return spec parameters as dict for label/print template use.
	Reads from the Item's own item_spec_parameters child table."""
	params = frappe.get_all(
		"Item Specification Parameter",
		filters={"parent": item_code, "parenttype": "Item", "parentfield": "item_spec_parameters"},
		fields=["parameter", "value", "calculated_value", "uom"],
		order_by="idx asc",
	)

	result = {}
	for p in params:
		result[p.parameter] = {
			"value": p.value,
			"calculated_value": p.calculated_value,
			"uom": p.uom,
		}
	return result
