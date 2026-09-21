# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""Which attributes a modification may carry, and what a valid value for one looks like.

The type and the subtype declare the keys; the modification holds the values. That split
is what makes the attribute search in the modification list worth anything: if a value
lived on the type, every modification of that type would answer the same, and the search
would be a second way of filtering by type.

A subtype adds to its type rather than replacing it — a «Батарея / Літієва» carries both
what every battery has and what only a lithium one has — so the declared set is the union
of the two, with the type's own row winning when both name the same attribute. Nothing is
copied onto the modification: change the type's list and every modification of that type
answers the new question, which is the reason the declaration is not just free rows on
each card.
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Cast_

from erpnext.technical_documentation.constants import ATTRIBUTE_DOCTYPE, MODIFICATION_DOCTYPE

SUBTYPE_DOCTYPE = "Product Subtype"
TYPE_DOCTYPE = "Product Type"
ATTRIBUTE_ROW_DOCTYPE = "Product Modification Attribute"
SUMMARY_LENGTH = 140
CONTAINS = "like"
STARTS = "starts"
AT_LEAST = ">="
AT_MOST = "<="
BETWEEN = "between"
NUMERIC_MATCHES = (AT_LEAST, AT_MOST, BETWEEN)
NUMBER_TYPE = "decimal(20,6)"


@frappe.whitelist()
def get_attributes(product_type: str | None = None, product_subtype: str | None = None) -> list[dict]:
	"""The attributes declared for this type and subtype, with the values each one allows."""
	frappe.has_permission(ATTRIBUTE_DOCTYPE, throw=True)

	declared = declared_attributes(product_type, product_subtype)
	if not declared:
		return []

	definitions = attribute_definitions(declared.keys())

	return [
		{
			"attribute": name,
			"mandatory": row.get("mandatory"),
			"declared_by": row.get("declared_by"),
			"note": row.get("note"),
			**definitions.get(name, {}),
		}
		for name, row in declared.items()
		if name in definitions
	]


@frappe.whitelist()
def search_modifications(conditions: str | list) -> list[str]:
	"""The modifications that carry every one of these attribute values.

	Several attributes cannot be asked for in the list filter row: the child table is joined
	once, so two conditions have to hold for the same row, and a modification that carries
	«Оптика» in one row and «915» in another matches neither pair. Intersecting the answers
	per condition here is what makes "optical and 915 MHz" a question the register can
	answer at all.

	A condition asks for the exact value unless it says otherwise; the loose ones differ only
	in where the wildcard goes. The wildcards are put around the text here rather than taken
	from it, so a value that itself contains a `%` still searches for that character.
	"""
	frappe.has_permission(MODIFICATION_DOCTYPE, throw=True)

	return matching_names(frappe.parse_json(conditions) or [])


@frappe.whitelist()
def count_modifications(
	conditions: str | list, product_type: str | None = None, product_subtype: str | None = None
) -> int:
	"""How many modifications the conditions gathered so far leave.

	Asked while the conditions are still being collected, because the useful thing to know
	about a condition is what it did to the answer — one that changes nothing is noise, and
	one that empties the answer is a typo, and both are worth seeing before the search runs
	rather than after it, when the conditions are gone from the screen.

	Counted the way the search is run, the type and subtype the dialog narrows by included,
	so the number cannot promise a row the search then does not show. Counting through the
	permitted list rather than the child table is part of that: a modification someone may
	not read is not in the list either.
	"""
	frappe.has_permission(MODIFICATION_DOCTYPE, throw=True)

	filters = {}
	if product_type:
		filters["product_type"] = product_type
	if product_subtype:
		filters["product_subtype"] = product_subtype

	parsed = frappe.parse_json(conditions) or []
	if parsed:
		names = matching_names(parsed)
		if not names:
			return 0

		filters["name"] = ("in", names)

	return len(frappe.get_all(MODIFICATION_DOCTYPE, filters=filters, pluck="name", limit=0))


def matching_names(conditions):
	matched = None
	for condition in conditions:
		rows = matching_modifications(condition)

		matched = set(rows) if matched is None else matched & set(rows)
		if not matched:
			return []

	return sorted(matched or [])


def matching_modifications(condition):
	row = frappe.qb.DocType(ATTRIBUTE_ROW_DOCTYPE)

	query = (
		frappe.qb.from_(row)
		.select(row.parent)
		.where(row.parenttype == MODIFICATION_DOCTYPE)
		.where(row.attribute == condition.get("attribute"))
		.where(value_condition(row, condition))
	)

	return [entry[0] for entry in query.run()]


def value_condition(row, condition):
	"""What the stored value has to look like for this condition to hold.

	The value is a `Data` column whatever the attribute is, so a numeric condition compares a
	cast, not the text: «9» is not larger than «10» as text, and a range asked for in a search
	that answered like that would be worse than no range at all. Which comparison a condition
	gets is decided by the condition itself rather than by the attribute, because the attribute
	is already what the dialog uses to decide which conditions it may offer.
	"""
	match = condition.get("match")

	if match in NUMERIC_MATCHES:
		number = Cast_(row.attribute_value, NUMBER_TYPE)

		if match == AT_LEAST:
			return number >= as_number(condition, "value")
		if match == AT_MOST:
			return number <= as_number(condition, "value")

		return number.between(as_number(condition, "value"), as_number(condition, "value_to"))

	text = escape_wildcards(condition.get("value"))

	if match == CONTAINS:
		return row.attribute_value.like(f"%{text}%")
	if match == STARTS:
		return row.attribute_value.like(f"{text}%")

	return row.attribute_value == condition.get("value")


def as_number(condition, key):
	try:
		return float(condition.get(key))
	except (TypeError, ValueError):
		frappe.throw(
			_("Attribute {0} is compared with a number, and {1} is not one").format(
				frappe.bold(condition.get("attribute")), frappe.bold(condition.get(key))
			)
		)


def escape_wildcards(value):
	"""`%` and `_` typed by a person are characters they are looking for, not wildcards."""
	return (value or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def declared_attributes(product_type, product_subtype):
	declared = {}

	for doctype, parent in ((SUBTYPE_DOCTYPE, product_subtype), (TYPE_DOCTYPE, product_type)):
		if not parent:
			continue

		for row in frappe.get_all(
			"Product Attribute Assignment",
			filters={"parenttype": doctype, "parent": parent},
			fields=["attribute", "mandatory", "note"],
			order_by="idx",
		):
			declared[row.attribute] = {**row, "declared_by": parent}

	return declared


def attribute_definitions(names):
	names = list(names)
	if not names:
		return {}

	definitions = {
		row.name: {
			"numeric_values": row.numeric_values,
			"from_range": row.from_range,
			"to_range": row.to_range,
			"increment": row.increment,
			"values": [],
		}
		for row in frappe.get_all(
			ATTRIBUTE_DOCTYPE,
			filters={"name": ("in", names), "disabled": 0},
			fields=["name", "numeric_values", "from_range", "to_range", "increment"],
		)
	}

	for row in frappe.get_all(
		"Product Attribute Value",
		filters={"parenttype": ATTRIBUTE_DOCTYPE, "parent": ("in", list(definitions))},
		fields=["parent", "attribute_value"],
		order_by="idx",
	):
		definitions[row.parent]["values"].append(row.attribute_value)

	return definitions


def build_summary(rows):
	"""The attribute rows of one modification as a single line.

	The list view reads columns from the table it lists, and the values sit in a child
	table it never joins, so the only way to put them in front of someone scanning the
	list is a field derived from the rows. Nothing reads it back: the search still asks
	the child table, and this line exists to be looked at.
	"""
	summary = ", ".join(f"{row.attribute}: {row.attribute_value}" for row in rows if row.attribute_value)

	return summary if len(summary) <= SUMMARY_LENGTH else summary[: SUMMARY_LENGTH - 1] + "…"


def validate_attribute_rows(rows, product_type, product_subtype):
	"""Every row names a declared attribute exactly once and carries a value it allows."""
	declared = get_attributes(product_type, product_subtype)
	by_name = {row["attribute"]: row for row in declared}
	seen = set()

	for row in rows:
		definition = by_name.get(row.attribute)
		if not definition:
			frappe.throw(
				_("Attribute {0} is not declared by the product type or subtype").format(
					frappe.bold(row.attribute)
				)
			)

		if row.attribute in seen:
			frappe.throw(_("Attribute {0} is filled in twice").format(frappe.bold(row.attribute)))

		seen.add(row.attribute)
		validate_value(row, definition)

	missing = [row["attribute"] for row in declared if row["mandatory"] and row["attribute"] not in seen]
	if missing:
		frappe.throw(
			_("These attributes are mandatory for this product type: {0}").format(
				frappe.bold(", ".join(missing))
			)
		)


def validate_value(row, definition):
	value = (row.attribute_value or "").strip()
	row.attribute_value = value

	if definition["numeric_values"]:
		validate_numeric_value(row.attribute, value, definition)
		return

	if definition["values"] and value not in definition["values"]:
		frappe.throw(
			_("Attribute {0} has no value {1}. Allowed: {2}").format(
				frappe.bold(row.attribute), frappe.bold(value), ", ".join(definition["values"])
			)
		)


def validate_numeric_value(attribute, value, definition):
	try:
		number = float(value)
	except ValueError:
		frappe.throw(_("Attribute {0} takes a number").format(frappe.bold(attribute)))

	validate_range(attribute, number, definition)
	validate_step(attribute, number, definition)


# An upper bound of zero is not a range, it is an unanswered question: the field defaults to
# zero, so a numeric attribute whose author filled in nothing would otherwise accept nothing
# but zero itself and explain that it «takes a value between 0 and 0». A lower bound of zero
# is a real floor and stays one — mass does not go negative.
def validate_range(attribute, number, definition):
	lower = definition["from_range"]
	upper = definition["to_range"]

	if upper and not lower <= number <= upper:
		frappe.throw(
			_("Attribute {0} takes a value between {1} and {2}").format(frappe.bold(attribute), lower, upper)
		)

	if not upper and number < lower:
		frappe.throw(_("Attribute {0} takes a value of {1} or more").format(frappe.bold(attribute), lower))


# The step is counted, not taken as a remainder. `(7.3 - 0) % 0.1` is 0.0999… rather than
# zero, because neither 7.3 nor 0.1 is a binary fraction, so the plain remainder rejects the
# values that sit exactly on the step for every step that is not a power of two. What is
# asked instead is how many steps away the number is, and whether that count is a whole one
# to within a tolerance far smaller than any step the register is given.
def validate_step(attribute, number, definition):
	step = definition["increment"]
	if not step:
		return

	steps = (number - definition["from_range"]) / step
	if abs(steps - round(steps)) > 1e-9:
		frappe.throw(_("Attribute {0} changes in steps of {1}").format(frappe.bold(attribute), step))
