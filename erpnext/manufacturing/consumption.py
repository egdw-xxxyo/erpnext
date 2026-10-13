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

from erpnext.stock.stock_ledger import NegativeStockError

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


def find_consumption(source_doctype, source_name):
	"""Name of the live (draft or submitted) consumption entry posted for a document, if any."""
	return frappe.db.get_value(
		"Stock Entry",
		{
			"consumption_source_doctype": source_doctype,
			"consumption_source_name": source_name,
			"docstatus": ["<", 2],
		},
		"name",
	)


def consume(
	recipe,
	variables,
	source_doctype,
	source_name,
	warehouse=None,
	posting_date=None,
	on_shortage="block",
):
	"""Issue what `recipe` consumes for `variables` as one Material Issue.

	Idempotent per source document: a second call returns the entry the first one posted, so
	a retried or double-clicked step cannot issue the consumables twice. Returns `None` when
	the recipe comes to nothing for these variables.

	`on_shortage` decides what a lack of stock does: "block" raises and leaves nothing behind;
	"draft" keeps the entry as a draft for someone to complete once the stock is there, so the
	step that called is not stopped.
	"""
	if on_shortage not in ("block", "draft"):
		frappe.throw(_("{0} is not a valid way to handle a shortage").format(on_shortage))

	existing = find_consumption(source_doctype, source_name)
	if existing:
		return frappe.get_doc("Stock Entry", existing)

	recipe_doc = frappe.get_doc("Consumption Recipe", recipe)
	if not recipe_doc.is_active:
		frappe.throw(_("Consumption Recipe {0} is not active").format(recipe))

	rows = compute(recipe_doc.items, variables)
	if not rows:
		return None

	for row in rows:
		row["s_warehouse"] = row.pop("source_warehouse") or warehouse
		if not row["s_warehouse"]:
			frappe.throw(
				_("Item {0} has no source warehouse in the recipe and none was given").format(
					row["item_code"]
				)
			)

	from erpnext.stock.get_item_details import get_conversion_factor

	frappe.db.savepoint("consume_insert")
	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = "Material Issue"
	entry.purpose = "Material Issue"
	entry.company = frappe.get_cached_value("Warehouse", rows[0]["s_warehouse"], "company")
	if posting_date:
		entry.posting_date = posting_date
		entry.set_posting_time = 1
	entry.consumption_recipe = recipe
	entry.consumption_source_doctype = source_doctype
	entry.consumption_source_name = source_name
	for row in rows:
		entry.append(
			"items",
			{
				"item_code": row["item_code"],
				"qty": row["qty"],
				"uom": row["uom"],
				"conversion_factor": get_conversion_factor(row["item_code"], row["uom"])["conversion_factor"]
				if row["uom"]
				else 1,
				"s_warehouse": row["s_warehouse"],
				"description": row["notes"],
			},
		)
	entry.insert()

	frappe.db.savepoint("consume_submit")
	try:
		entry.submit()
	except NegativeStockError:
		if on_shortage == "block":
			frappe.db.rollback(save_point="consume_insert")
			raise
		frappe.db.rollback(save_point="consume_submit")
		entry.reload()
		frappe.msgprint(
			_("Not enough stock to issue the consumables; {0} is kept as a draft").format(entry.name),
			indicator="orange",
			alert=True,
		)
	return entry


def cancel_for_source(doc, method=None):
	"""`doc_events` hook: the consumption posted for a document goes back when the document does."""
	name = find_consumption(doc.doctype, doc.name)
	if not name:
		return
	entry = frappe.get_doc("Stock Entry", name)
	if entry.docstatus == 1:
		entry.cancel()
	else:
		frappe.delete_doc("Stock Entry", name, force=True)


@frappe.whitelist()
def preview_recipe(recipe, values):
	"""`preview` for a saved recipe, for forms that only point at one."""
	frappe.has_permission("Consumption Recipe", "read", doc=recipe, throw=True)
	items = frappe.get_all(
		"Consumption Recipe Item",
		filters={"parent": recipe, "parenttype": "Consumption Recipe"},
		fields=[
			"item_code",
			"item_name",
			"uom",
			"qty_formula",
			"condition",
			"source_warehouse",
			"notes",
			"idx",
		],
		order_by="idx",
	)
	return preview(items, values)
