import re

import frappe

LENGTH_ATTRIBUTE = "Довжина намотки"


def item_attributes(item_code):
	"""The variant's attributes as {attribute: value}, numeric ones as floats.

	Values carry their unit ("25 км"), so a leading number is read as the value.
	"""
	if not item_code:
		return {}

	rows = frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": item_code},
		fields=["attribute", "attribute_value"],
	)
	attributes = {}
	for row in rows:
		value = row.attribute_value
		match = re.match(r"\s*([-+]?\d+(?:[.,]\d+)?)\s*\D*$", str(value or ""))
		attributes[row.attribute] = float(match.group(1).replace(",", ".")) if match else value
	return attributes


class InspectionFormulaContext:
	"""Gives Quality Inspection acceptance formulas the item they are grading.

	On top of the stock `reading_1..10` and `mean`, a formula can use `attr` (the item's
	variant attributes, e.g. `attr["Тип волокна"]`), `length_km` (the winding length),
	`item_code` and `variant_of`, so one template row can carry per-length / per-type limits.
	"""

	def get_formula_evaluation_data(self, reading):
		data = super().get_formula_evaluation_data(reading)
		attributes = item_attributes(self.item_code)
		length = attributes.get(LENGTH_ATTRIBUTE)
		data["attr"] = attributes
		data["length_km"] = length if isinstance(length, float) else 0.0
		data["item_code"] = self.item_code
		data["variant_of"] = frappe.db.get_value("Item", self.item_code, "variant_of") or ""
		return data
