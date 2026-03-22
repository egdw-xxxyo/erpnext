# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ItemSpecification(Document):
	def validate(self):
		seen = set()
		for row in self.parameters:
			if row.parameter in seen:
				frappe.throw(
					f"Duplicate parameter: {row.parameter}. Each parameter can only appear once."
				)
			seen.add(row.parameter)


@frappe.whitelist()
def get_spec_for_item(item_code):
	"""Return spec parameters as dict for label/print template use."""
	spec_name = frappe.get_cached_value("Item", item_code, "item_specification")
	if not spec_name:
		return {}

	params = frappe.get_all(
		"Item Specification Parameter",
		filters={"parent": spec_name},
		fields=["parameter", "value", "numeric", "min_value", "max_value", "uom", "display_value"],
		order_by="idx asc",
	)

	result = {}
	for p in params:
		result[p.parameter] = {
			"value": p.value,
			"numeric": p.numeric,
			"min_value": p.min_value,
			"max_value": p.max_value,
			"uom": p.uom,
			"display_value": p.display_value,
		}
	return result
