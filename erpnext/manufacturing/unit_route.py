"""The route a unit takes, read from the operations of its BOM.

One operation of a BOM may carry `enters_stock`: the step after which the unit is a stock item.
Everything up to and including it is a Job Card of the Work Order, as always. Everything listed
after it (packing, re-completing) happens to a unit that is already in stock, so it must not be
an operation of the Work Order: `Stock Entry.check_if_operations_completed` would refuse the
Manufacture entry while such an operation is open.

A BOM with no marked operation behaves as before: every operation is before stock.
"""

import frappe
from frappe import _


def route(bom):
	"""The BOM's operations in order, each with `after_stock` and the warehouse the step lands in."""
	rows = frappe.get_all(
		"BOM Operation",
		filters={"parent": bom, "parenttype": "BOM"},
		fields=["name", "idx", "operation", "workstation", "enters_stock", "unit_target_warehouse"],
		order_by="idx",
	)
	marked = next((row.idx for row in rows if row.enters_stock), None)
	for row in rows:
		row["after_stock"] = marked is not None and row.idx > marked
	return rows


def stock_step(bom):
	"""The operation after which the unit enters stock, or `None` when the BOM does not say."""
	return next((row for row in route(bom) if row.enters_stock), None)


def validate_bom(doc, method=None):
	"""`doc_events` hook on BOM: at most one step can be the one that puts the unit into stock."""
	marked = [row for row in doc.get("operations") or [] if row.get("enters_stock")]
	if len(marked) > 1:
		frappe.throw(
			_("Only one operation can put the unit into stock, but rows {0} are all marked").format(
				", ".join(str(row.idx) for row in marked)
			)
		)


def drop_after_stock_operations(doc, method=None):
	"""`doc_events` hook on Work Order: leave out the steps that happen after the unit is in stock."""
	if doc.docstatus != 0 or not doc.bom_no or not doc.get("operations"):
		return

	after = {row.operation for row in route(doc.bom_no) if row.after_stock}
	if not after:
		return

	doc.set(
		"operations",
		[row for row in doc.operations if not (row.operation in after and row.bom in (None, "", doc.bom_no))],
	)
	for idx, row in enumerate(doc.operations, start=1):
		row.idx = idx
