import frappe
from frappe import _
from frappe.utils import flt, now


def _require_manager():
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only System Manager can link existing purchase receipts."), frappe.PermissionError)


def _validate_order(order):
	order.check_permission("read")
	if order.docstatus != 1 or order.status in ("Closed", "On Hold"):
		frappe.throw(_("Select a submitted, open Purchase Order."))


def _eligible_receipt(receipt, order):
	return (
		receipt.docstatus == 1
		and not receipt.is_return
		and receipt.supplier == order.supplier
		and receipt.company == order.company
		and receipt.currency == order.currency
		and all(not row.purchase_order or row.purchase_order == order.name for row in receipt.items)
		and all(
			not row.purchase_order_item or row.purchase_order_item in {r.name for r in order.items}
			for row in receipt.items
		)
	)


def _matches(source, target):
	return (
		source.item_code == target.item_code
		and source.uom == target.uom
		and (source.project or "") == (target.project or "")
		and flt(source.conversion_factor) == flt(target.conversion_factor)
		and (not source.material_request or source.material_request == target.material_request)
		and (not source.material_request_item or source.material_request_item == target.material_request_item)
		and not target.delivered_by_supplier
		and not flt(source.rejected_qty)
		and flt(source.qty) > 0
	)


@frappe.whitelist()
def get_candidates(order_name):
	_require_manager()
	order = frappe.get_doc("Purchase Order", order_name)
	_validate_order(order)
	targets = [row for row in order.items if flt(row.qty) > flt(row.received_qty)]
	rows = []
	for name in frappe.get_list(
		"Purchase Receipt",
		filters=[
			["Purchase Receipt", "supplier", "=", order.supplier],
			["Purchase Receipt", "company", "=", order.company],
			["Purchase Receipt", "currency", "=", order.currency],
			["Purchase Receipt", "docstatus", "=", 1],
			["Purchase Receipt", "is_return", "=", 0],
			["Purchase Receipt Item", "purchase_order", "is", "not set"],
			["Purchase Receipt Item", "purchase_order_item", "is", "not set"],
		],
		distinct=True,
		pluck="name",
		limit_page_length=100,
		order_by="posting_date desc",
	):
		receipt = frappe.get_doc("Purchase Receipt", name)
		if not _eligible_receipt(receipt, order):
			continue
		for source in receipt.items:
			if source.purchase_order or source.purchase_order_item:
				continue
			matches = [
				target.name
				for target in targets
				if _matches(source, target)
				and flt(source.qty) <= flt(target.qty) - flt(target.received_qty) + 0.000001
			]
			if matches:
				rows.append(
					{
						"receipt": name,
						"receipt_row": source.name,
						"row_number": source.idx,
						"item_name": source.item_name,
						"description": source.description,
						"qty": source.qty,
						"uom": source.uom,
						"posting_date": receipt.posting_date,
						"matches": matches,
					}
				)
	return {
		"rows": rows,
		"order_rows": [
			{
				"name": row.name,
				"idx": row.idx,
				"item_name": row.item_name,
				"description": row.description,
				"qty": flt(row.qty) - flt(row.received_qty),
				"uom": row.uom,
			}
			for row in targets
		],
	}


@frappe.whitelist(methods=["POST"])
def link_receipts(order_name, mappings):
	_require_manager()
	mappings = frappe.parse_json(mappings) or []
	if not mappings or len(mappings) > 200:
		frappe.throw(_("Select receipt rows to link."))
	order = frappe.get_doc("Purchase Order", order_name, for_update=True)
	_validate_order(order)
	targets = {row.name: row for row in order.items}
	pending = {row.name: flt(row.qty) - flt(row.received_qty) for row in order.items}
	receipts = {
		name: frappe.get_doc("Purchase Receipt", name, for_update=True)
		for name in sorted({m["receipt"] for m in mappings})
	}
	seen = set()
	for mapping in mappings:
		receipt = receipts[mapping["receipt"]]
		receipt.check_permission("read")
		if not _eligible_receipt(receipt, order):
			frappe.throw(
				_("The receipt must match the supplier and company and must not be linked to another order.")
			)
		source = next((r for r in receipt.items if r.name == mapping.get("receipt_row")), None)
		target = targets.get(mapping.get("order_row"))
		if (
			not source
			or not target
			or source.name in seen
			or source.purchase_order
			or source.purchase_order_item
			or not _matches(source, target)
		):
			frappe.throw(_("Receipt rows no longer match the selected order. Refresh the candidates."))
		seen.add(source.name)
		pending[target.name] -= flt(source.qty)
		if pending[target.name] < -0.000001:
			frappe.throw(_("The selected receipts exceed the outstanding order quantity."))
		source.purchase_order = order.name
		source.purchase_order_item = target.name
		source.material_request = target.material_request or source.material_request
		source.material_request_item = target.material_request_item or source.material_request_item
	for receipt in receipts.values():
		receipt.validate_with_previous_doc()
	for receipt in receipts.values():
		for row in receipt.items:
			if row.name in seen:
				frappe.db.set_value(
					"Purchase Receipt Item",
					row.name,
					{
						"purchase_order": order.name,
						"purchase_order_item": row.purchase_order_item,
						"material_request": row.material_request,
						"material_request_item": row.material_request_item,
					},
					update_modified=False,
				)
		# Only references change; never resubmit the receipt or replay stock entries.
		receipt.update_prevdoc_status()
		frappe.db.set_value(
			"Purchase Receipt",
			receipt.name,
			{"modified": now(), "modified_by": frappe.session.user},
			update_modified=False,
		)
		receipt.add_comment("Info", _("Linked to Purchase Order {0} by System Manager.").format(order.name))
		frappe.clear_document_cache("Purchase Receipt", receipt.name)
	order.add_comment("Info", _("Linked existing Purchase Receipts: {0}").format(", ".join(receipts)))
	from erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order import (
		sync_linked_consolidated_purchase_order_progress,
	)

	for receipt in receipts.values():
		sync_linked_consolidated_purchase_order_progress(receipt)
	frappe.clear_document_cache("Purchase Order", order.name)
	return {"receipts": list(receipts)}
