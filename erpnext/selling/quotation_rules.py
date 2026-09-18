# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""«Угода» rules layered on the stock Quotation through hooks.

The Quotation controller is left alone — everything here is wired in erpnext/hooks.py
(`doc_events`). The approval route itself is a Workflow, created in
erpnext/patches/setup_custom_fields.py."""

import frappe
from frappe import _
from frappe.utils import flt

#: The only workflow state in which a Quotation may be edited.
DRAFT_STATE = "Опрацьовується"

#: Changing any of these is a change of the agreement, so it is blocked once the approval
#: route has started. The document has to be sent back for rework first.
LOCKED_FIELDS = (
	"items",
	"fulfilment_type",
	"valid_till",
	"transaction_date",
	"party_name",
	"quotation_to",
	"currency",
	"selling_price_list",
	"payment_terms_template",
	"taxes",
	"discount_amount",
	"additional_discount_percentage",
)


def validate(doc, method=None):
	validate_fulfilment_type(doc)
	validate_locked_fields(doc)


def validate_fulfilment_type(doc):
	"""The route cannot be picked once the document has left the manager's hands."""
	state = doc.get("workflow_state")
	if not state or state == DRAFT_STATE:
		if doc.docstatus == 1 and not doc.get("fulfilment_type"):
			frappe.throw(
				_("{0} is mandatory").format(frappe.bold(_("Fulfilment Type"))),
				title=_("Missing Value"),
			)
		return

	if doc.has_value_changed("fulfilment_type"):
		frappe.throw(
			_("{0} can only be changed while the Quotation is in state {1}").format(
				frappe.bold(_("Fulfilment Type")), frappe.bold(_(DRAFT_STATE))
			)
		)


def validate_locked_fields(doc):
	"""Once the Workflow has started the Quotation is read-only for everyone.

	Workflow state transitions themselves are allowed — only the terms are frozen."""
	state = doc.get("workflow_state")
	if not state or state == DRAFT_STATE or doc.is_new():
		return

	before = doc.get_doc_before_save()
	if not before:
		return

	# Going back for rework unlocks the document; that transition is not a content change.
	if before.get("workflow_state") != state:
		return

	for fieldname in LOCKED_FIELDS:
		if not doc.has_value_changed(fieldname):
			continue

		frappe.throw(
			_(
				"{0} cannot be changed while the Quotation is being approved. Return it for rework first."
			).format(frappe.bold(_(doc.meta.get_label(fieldname)))),
			title=_("Quotation Locked"),
		)


def before_cancel(doc, method=None):
	if not doc.get("cancellation_reason") or not doc.get("cancellation_comment"):
		frappe.throw(
			_("{0} and {1} are mandatory to cancel a Quotation").format(
				frappe.bold(_("Cancellation Reason")), frappe.bold(_("Cancellation Comment"))
			),
			title=_("Missing Value"),
		)


def validate_sales_order_against_quotation(doc, method=None):
	"""Keep every Sales Order inside the quantity its Quotation approved."""
	for item in doc.get("items", []):
		if item.get("prevdoc_doctype") != "Quotation" or not item.get("prevdoc_docname"):
			continue

		approved = _approved_row(item)
		if not approved:
			frappe.throw(
				_("Row #{0}: Item {1} is not part of Quotation {2}").format(
					item.idx, frappe.bold(item.item_code), frappe.bold(item.prevdoc_docname)
				)
			)

		# Quotation Item.ordered_qty is maintained by the StatusUpdater and, on a resave of an
		# already submitted Sales Order, includes this order's own quantity. Counting the
		# other orders directly keeps the check correct in both cases.
		remaining = flt(approved.qty) - _consumed_by_other_orders(item, doc.name)

		if flt(item.qty) > remaining + 0.001:
			frappe.throw(
				_("Row #{0}: only {1} of {2} is left to order on Quotation {3}").format(
					item.idx,
					frappe.bold(flt(remaining)),
					frappe.bold(item.item_code),
					frappe.bold(item.prevdoc_docname),
				),
				title=_("Quantity Exceeded"),
			)


def _consumed_by_other_orders(item, sales_order):
	"""Quantity of this Quotation row already taken by other submitted Sales Orders."""
	rows = frappe.get_all(
		"Sales Order Item",
		filters={
			"prevdoc_docname": item.prevdoc_docname,
			"item_code": item.item_code,
			"docstatus": 1,
			"parent": ["!=", sales_order],
		},
		pluck="qty",
	)

	return sum(flt(qty) for qty in rows)


def _approved_row(item):
	if item.get("quotation_item"):
		row = frappe.db.get_value(
			"Quotation Item",
			item.quotation_item,
			["item_code", "qty", "ordered_qty"],
			as_dict=True,
		)
		if row and row.item_code == item.item_code:
			return row

	return frappe.db.get_value(
		"Quotation Item",
		{"parent": item.prevdoc_docname, "item_code": item.item_code},
		["item_code", "qty", "ordered_qty"],
		as_dict=True,
	)


@frappe.whitelist()
def get_fulfilment_summary(quotation: str):
	"""Approved vs ordered quantity, plus the Sales Orders that consumed it."""
	frappe.has_permission("Quotation", "read", doc=quotation, throw=True)

	rows = frappe.get_all(
		"Quotation Item",
		filters={"parent": quotation, "parenttype": "Quotation"},
		fields=["item_code", "item_name", "qty", "ordered_qty", "uom"],
		order_by="idx asc",
	)
	for row in rows:
		row["remaining_qty"] = flt(row["qty"]) - flt(row["ordered_qty"])

	orders = frappe.get_all(
		"Sales Order Item",
		filters={"prevdoc_docname": quotation, "docstatus": ["<", 2]},
		fields=["parent", "item_code", "qty"],
	)

	sales_orders = {}
	for order in orders:
		entry = sales_orders.setdefault(order["parent"], {"qty": 0.0})
		entry["qty"] += flt(order["qty"])

	for name, entry in sales_orders.items():
		entry["status"] = frappe.db.get_value("Sales Order", name, "status")

	return {"items": rows, "sales_orders": sales_orders}
