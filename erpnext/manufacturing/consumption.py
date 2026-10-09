"""Work out what a step consumes from a `Consumption Recipe`.

A recipe row says "this item, this many, when this holds", where the quantity and the
condition are formulas over what the step handles: `units` for packing (the serials actually
in the box), `qty` for an operation. `compute` is the one place that turns a recipe into
numbers, so the calculator on the form and whatever posts stock later cannot disagree.

Formulas run through `frappe.safe_eval`, so they cannot reach anything but the variables and
the helpers below.
"""

import json
import math

import frappe
from frappe import _
from frappe.utils import cint, flt
from frappe.utils.safe_exec import safe_eval

FORMULA_HELPERS = {"ceil": math.ceil, "floor": math.floor, "min": min, "max": max, "abs": abs}
SAMPLE_VARIABLES = {"units": 1, "qty": 1}
MAX_PREVIEW_VALUES = 12


def evaluate(expression, variables):
	return safe_eval(expression, dict(FORMULA_HELPERS), dict(variables))


def _whole_number_uom(uom):
	return bool(uom) and bool(cint(frappe.get_cached_value("UOM", uom, "must_be_whole_number")))


def _round_quantity(qty, uom):
	"""A formula like `units / 2` can give 1.5 of something that comes in whole pieces.

	Rounding up is deliberate: under-consuming leaves a box that was really used with no stock
	movement, over-consuming by one is visible at the next count.
	"""
	if _whole_number_uom(uom):
		return math.ceil(qty - 1e-9)
	return flt(qty, 3)


def compute(items, variables):
	"""The consumables for one step, as `[{item_code, item_name, uom, qty, source_warehouse, notes}]`.

	`items` is the recipe's rows — documents or dicts. Rows whose condition is false, or that
	come to nothing, are left out.
	"""
	rows = []
	for idx, row in enumerate(items, start=1):
		row = frappe._dict(row)
		try:
			if row.condition and not evaluate(row.condition, variables):
				continue
			qty = flt(evaluate(row.qty_formula or "1", variables))
		except Exception as e:
			frappe.throw(_("Row {0}: {1}").format(row.get("idx") or idx, str(e)))

		qty = _round_quantity(qty, row.uom)
		if qty <= 0:
			continue

		rows.append(
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"uom": row.uom,
				"qty": qty,
				"source_warehouse": row.source_warehouse,
				"notes": row.notes,
			}
		)
	return rows


@frappe.whitelist()
def preview(items, values):
	"""What a recipe would consume for each of several quantities — the calculator on the form.

	Takes the rows as they are on screen, so a recipe can be tried before it is saved.
	"""
	frappe.has_permission("Consumption Recipe", "read", throw=True)

	items = json.loads(items) if isinstance(items, str) else items
	if isinstance(values, str):
		values = [v.strip() for v in values.replace(";", ",").split(",") if v.strip()]

	quantities = []
	for value in values:
		try:
			quantity = cint(value)
		except Exception:
			frappe.throw(_("{0} is not a whole number").format(value))
		if quantity > 0 and quantity not in quantities:
			quantities.append(quantity)
	quantities = quantities[:MAX_PREVIEW_VALUES]
	if not quantities:
		frappe.throw(_("Enter at least one quantity greater than zero"))

	table = {}
	for quantity in quantities:
		for row in compute(items, {"units": quantity, "qty": quantity}):
			entry = table.setdefault(
				(row["item_code"], row["uom"]),
				{"item_code": row["item_code"], "item_name": row["item_name"], "uom": row["uom"], "qty": {}},
			)
			entry["qty"][quantity] = entry["qty"].get(quantity, 0) + row["qty"]

	return {"values": quantities, "rows": list(table.values())}
