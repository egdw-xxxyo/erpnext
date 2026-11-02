import re

import frappe
from frappe import _

LENGTH_ATTRIBUTE = "Довжина намотки"


RESERVED_NAMES = {"mean", "attr", "length_km", "item_code", "variant_of", "reading_value"}


def _variant_attribute_rows(item_code):
	if not item_code:
		return []
	return frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": item_code},
		fields=["attribute", "attribute_value"],
	)


def item_attributes(item_code):
	"""The variant's attributes as {attribute: value}, numeric ones as floats.

	Values carry their unit ("25 км"), so a leading number is read as the value.
	"""
	attributes = {}
	for row in _variant_attribute_rows(item_code):
		value = row.attribute_value
		match = re.match(r"\s*([-+]?\d+(?:[.,]\d+)?)\s*\D*$", str(value or ""))
		attributes[row.attribute] = float(match.group(1).replace(",", ".")) if match else value
	return attributes


def template_variables(template, item_code, variant_of=None):
	"""The template's variables resolved for one item, as {name: value or None}.

	A row with no Item / Attribute is the default; one that names an item (or its template)
	and/or an attribute value only applies to matching items. The row naming the most
	matchers wins, so `max_loss` can have a general row and one per winding length.
	"""
	if not template:
		return {}

	rows = frappe.get_all(
		"QI Template Variable",
		filters={"parent": template, "parenttype": "Quality Inspection Template"},
		fields=["variable", "value", "item", "attribute", "attribute_value"],
		order_by="idx asc",
	)
	held = {(r.attribute, str(r.attribute_value or "").strip()) for r in _variant_attribute_rows(item_code)}

	resolved = {}
	specificity = {}
	for row in rows:
		name = (row.variable or "").strip()
		score = 0
		if row.item:
			if row.item not in (item_code, variant_of):
				continue
			score += 1
		if row.attribute:
			if (row.attribute, (row.attribute_value or "").strip()) not in held:
				continue
			score += 1
		resolved.setdefault(name, None)
		if specificity.get(name, -1) < score:
			specificity[name] = score
			resolved[name] = row.value
	return resolved


def validate_template_variables(doc, method=None):
	for row in doc.get("variables") or []:
		name = (row.variable or "").strip()
		if not name.isidentifier() or name in RESERVED_NAMES or re.fullmatch(r"reading_\d+", name):
			frappe.throw(
				_("Row #{0}: {1} cannot be used as a variable name.").format(row.idx, frappe.bold(name)),
				title=_("Invalid Variable"),
			)


class InspectionFormulaContext:
	"""Gives Quality Inspection acceptance formulas the item they are grading.

	On top of the stock `reading_1..10` and `mean`, a formula can use `attr` (the item's
	variant attributes, e.g. `attr["Тип волокна"]`), `length_km` (the winding length),
	`item_code` and `variant_of`, so one template row can carry per-length / per-type limits.
	Every variable of the template's Variables table is also a name (None where no row
	matches the item), so limits are edited in the table instead of inside the formula.
	"""

	def get_formula_evaluation_data(self, reading):
		data = super().get_formula_evaluation_data(reading)
		variant_of = frappe.db.get_value("Item", self.item_code, "variant_of") or ""
		data.update(template_variables(self.quality_inspection_template, self.item_code, variant_of))
		attributes = item_attributes(self.item_code)
		length = attributes.get(LENGTH_ATTRIBUTE)
		data["attr"] = attributes
		data["length_km"] = length if isinstance(length, float) else 0.0
		data["item_code"] = self.item_code
		data["variant_of"] = variant_of
		return data
