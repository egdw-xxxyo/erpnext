"""Workflow setup and invoice integration for recurring purchases."""

import frappe
from frappe import _

from erpnext.buying.doctype.recurring_purchase.recurring_purchase import DOCTYPE, check_active


def setup():
	from erpnext.buying.procurement_workflow import (
		WORKFLOW_DOCUMENT_STATES,
		WORKFLOW_TRANSITIONS,
		_child_table_matches,
		_ensure_workflow_actions,
		_ensure_workflow_states,
	)
	from erpnext.patches.setup_custom_fields import setup_recurring_purchase_fields

	setup_recurring_purchase_fields()
	_ensure_workflow_states()
	_ensure_workflow_actions()
	name = "Закупівлі: погодження регулярної закупівлі"
	doc = (
		frappe.get_doc("Workflow", name) if frappe.db.exists("Workflow", name) else frappe.new_doc("Workflow")
	)
	values = {
		"workflow_name": name,
		"document_type": DOCTYPE,
		"is_active": 1,
		"workflow_state_field": "workflow_state",
		"send_email_alert": 0,
		"override_status": 0,
	}
	changed = doc.is_new() or any(doc.get(k) != v for k, v in values.items())
	doc.update(values)
	for field, rows in (("states", WORKFLOW_DOCUMENT_STATES), ("transitions", WORKFLOW_TRANSITIONS)):
		if not _child_table_matches(doc.get(field), rows):
			doc.set(field, [dict(row) for row in rows])
			changed = True
	if changed:
		doc.save(ignore_permissions=True)


def validate_invoice(doc, method=None):
	before = doc.get_doc_before_save()
	if before and before.get("custom_recurring_purchase") != doc.get("custom_recurring_purchase"):
		frappe.throw(_("The recurring purchase reference cannot be changed after saving the invoice."))
	if not doc.get("custom_recurring_purchase"):
		return
	source = frappe.get_doc(DOCTYPE, doc.custom_recurring_purchase)
	source.check_permission("read")
	if source.docstatus != 1 or source.workflow_state != "Проведено":
		frappe.throw(_("Submit the approved recurring purchase before creating an invoice."))
	if doc.is_new() or getattr(doc, "_action", None) == "submit":
		check_active(source, doc.posting_date)
	if doc.get("custom_consolidated_purchase_order"):
		frappe.throw(_("An invoice cannot reference both a recurring and a consolidated purchase."))
	if any(doc.get(field) != source.get(field) for field in ("supplier", "company", "currency")):
		frappe.throw(_("Invoice supplier, company and currency must match the recurring purchase."))
	allowed = {row.item_code for row in source.items}
	if not doc.items or any(row.item_code not in allowed for row in doc.items):
		frappe.throw(_("Invoice items must belong to the approved recurring purchase."))
	if doc.update_stock:
		frappe.throw(_("Receive recurring purchase goods with a separate Purchase Receipt."))


class RecurringPurchaseInvoice:
	"""Use an approved recurring purchase instead of requiring a PO/receipt before invoicing.

	Only this validated route is exempt; global and supplier settings are never changed.
	Stock movement remains a separate Purchase Receipt created from the invoice.
	"""

	def po_required(self):
		if self.get("custom_recurring_purchase"):
			validate_invoice(self)
			return
		return super().po_required()

	def pr_required(self):
		if self.get("custom_recurring_purchase"):
			validate_invoice(self)
			return
		return super().pr_required()
