"""Quantity-based repair outcomes using the existing cards, request rows and movements."""

import frappe
from frappe import _
from frappe.utils import cint, flt

RESULT_FIELDS = {
	"Repaired": "repaired_qty",
	"No Fault Found": "no_fault_qty",
	"Not Repairable": "not_repairable_qty",
}


def whole_quantity(value, allow_zero=False):
	quantity = flt(value)
	if quantity != cint(quantity) or quantity < (0 if allow_zero else 1):
		frappe.throw(_("Repair quantities must be whole numbers and cannot be negative or empty."))
	return cint(quantity)


def validate_request_rows(request):
	for row in request.custom_repair_items:
		row.qty = whole_quantity(row.qty)
		row.has_serial_no = (
			frappe.db.get_value("Repair Unit", row.repair_unit, "has_serial_no")
			if row.repair_unit
			else frappe.get_cached_value("Item", row.item_code, "has_serial_no")
			if row.item_code
			else 0
		)
		if row.has_serial_no and row.qty != 1:
			frappe.throw(_("A serialized item must have its own repair row with quantity 1."))


def validate_distribution(doc, before=None):
	whole_quantity(doc.qty)
	if doc.has_serial_no and doc.qty != 1:
		frappe.throw(_("A serialized item must have its own repair row with quantity 1."))
	quantities = [whole_quantity(doc.get(field) or 0, allow_zero=True) for field in RESULT_FIELDS.values()]
	if sum(quantities) > doc.qty:
		frappe.throw(_("The total repair result quantity cannot exceed the repair quantity."))
	if (
		before
		and before.split_finalized
		and any(doc.get(field) != before.get(field) for field in ["outcome", *RESULT_FIELDS.values()])
	):
		frappe.throw(
			_("Distributed repair results are fixed. Continue delivery or disposal on the result rows.")
		)
	if doc.qty > 1 and not doc.split_finalized and doc.outcome:
		frappe.throw(_("Distribute the repair quantity between results instead of choosing a single result."))


def finalize(doc):
	"""Split once, retaining the original receipt and all work/cost history on the source card."""
	from erpnext.support.repair_units import internal_action
	from erpnext.support.service_repair import _lock

	_lock("Issue", doc.issue)
	request = frappe.get_doc("Issue", doc.issue)
	validate_distribution(doc)
	groups = [(outcome, cint(doc.get(field))) for outcome, field in RESULT_FIELDS.items() if doc.get(field)]
	if sum(qty for outcome, qty in groups) != doc.qty:
		frappe.throw(_("Distribute the entire repair quantity before marking the repair ready."))
	if not doc.work_done and any(outcome != "Not Repairable" for outcome, qty in groups):
		frappe.throw(_("Specify work done and the repair result before marking the unit ready."))
	row = next((row for row in request.custom_repair_items if row.name == doc.request_row), None)
	if not row or row.repair_unit != doc.name:
		frappe.throw(_("Cannot find the source request row for this repair."))
	template = frappe.copy_doc(doc)
	source_row = frappe.copy_doc(row)
	with internal_action():
		for index, (outcome, qty) in enumerate(groups):
			unit = doc if index == 0 else frappe.copy_doc(template)
			unit.qty = qty
			unit.outcome = outcome
			unit.split_finalized = 1
			unit.status = "Ready for Dispatch"
			unit.last_action = frappe.generate_hash(length=12)
			for result, field in RESULT_FIELDS.items():
				unit.set(field, qty if result == outcome else 0)
			if index:
				new_row = request.append("custom_repair_items", frappe.copy_doc(source_row))
				new_row.name = frappe.generate_hash(length=10)
				new_row.idx = len(request.custom_repair_items)
				new_row.qty = qty
				unit.request_row = new_row.name
				unit.split_from = doc.name
				unit.legacy_order_item = None
				for field in ("_assign", "_comments", "_liked_by", "_user_tags", "_seen"):
					unit.set(field, None)
				unit.set("work_log", [])
				unit.labor_cost = unit.parts_cost = unit.total_cost = 0
				unit.insert(ignore_permissions=True)
				new_row.repair_unit = unit.name
			else:
				row.qty = qty
				unit.save()
		request.save(ignore_permissions=True)
	return doc.name


def backfill():
	"""Preserve existing one-piece repairs without saving requests or sending notifications."""
	for doctype in ("Repair Unit", "Service Request Item", "Repair Movement Item", "Repair Shipment"):
		table = frappe.qb.DocType(doctype)
		frappe.qb.update(table).set(table.qty, 1).where(table.qty.isnull() | (table.qty == 0)).run()
	for doctype in ("Repair Unit", "Service Request Item"):
		for row in frappe.get_all(doctype, fields=["name", "item_code", "has_serial_no", "qty"]):
			serialized = (
				cint(frappe.get_cached_value("Item", row.item_code, "has_serial_no")) if row.item_code else 0
			)
			if serialized and not row.has_serial_no and row.qty == 1:
				frappe.db.set_value(doctype, row.name, "has_serial_no", serialized, update_modified=False)
	for row in frappe.get_all("Repair Movement Item", fields=["name", "repair_unit", "has_serial_no"]):
		serialized = cint(frappe.db.get_value("Repair Unit", row.repair_unit, "has_serial_no"))
		if serialized != cint(row.has_serial_no):
			frappe.db.set_value(
				"Repair Movement Item", row.name, "has_serial_no", serialized, update_modified=False
			)
