import frappe

PAYMENT_REQUEST_DOCTYPE = "Payment Request"
PURCHASE_INVOICE_DOCTYPE = "Purchase Invoice"
CONSOLIDATED_PURCHASE_ORDER_DOCTYPE = "Consolidated Purchase Order"
APPROVED_FIELD = "custom_procurement_approved"


def set_procurement_approval_route(doc, method=None):
	"""Mark requests whose purchasing approval was completed upstream."""
	doc.set(APPROVED_FIELD, int(_has_approved_procurement_source(doc)))


def _has_approved_procurement_source(doc):
	if doc.reference_doctype != PURCHASE_INVOICE_DOCTYPE or not doc.reference_name:
		return False

	invoice = frappe.db.get_value(
		PURCHASE_INVOICE_DOCTYPE,
		doc.reference_name,
		["docstatus", "custom_consolidated_purchase_order"],
		as_dict=True,
	)
	if not invoice or invoice.docstatus != 1 or not invoice.custom_consolidated_purchase_order:
		return False

	consolidated_order = frappe.db.get_value(
		CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
		invoice.custom_consolidated_purchase_order,
		["docstatus", "workflow_state"],
		as_dict=True,
	)
	return bool(
		consolidated_order
		and consolidated_order.docstatus == 1
		and consolidated_order.workflow_state == "Проведено"
	)
