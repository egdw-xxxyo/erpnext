from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext.buying.procurement_automation import (
	_close_assignments_silently,
	_notify_procurement_initiators,
	create_external_payment_purchase_receipt,
)


class TestProcurementAutomation(FrappeTestCase):
	@patch("erpnext.buying.procurement_automation._get_primary_procurement_initiator")
	@patch("erpnext.buying.procurement_automation.frappe.db.exists")
	@patch("erpnext.buying.procurement_automation.frappe.db.get_value")
	@patch("erpnext.accounts.doctype.purchase_invoice.purchase_invoice.make_purchase_receipt")
	def test_prepaid_invoice_creates_and_submits_receipt(
		self, make_purchase_receipt, get_value, exists, get_initiator
	):
		invoice = frappe._dict(
			docstatus=1,
			name="PINV-TEST",
			custom_paid_outside_company=1,
			custom_consolidated_purchase_order="CPO-TEST",
			update_stock=0,
			is_return=0,
		)
		receipt = MagicMock()
		receipt.get.return_value = [frappe._dict(item_code="ITEM-1")]
		make_purchase_receipt.return_value = receipt
		get_value.return_value = 1
		exists.return_value = False
		get_initiator.return_value = None

		create_external_payment_purchase_receipt(invoice)

		make_purchase_receipt.assert_called_once_with(invoice.name)
		receipt.insert.assert_called_once_with(ignore_permissions=True)
		receipt.submit.assert_called_once_with()

	@patch("erpnext.buying.procurement_automation.enqueue_create_notification")
	@patch("erpnext.buying.procurement_automation._get_procurement_initiators")
	def test_final_notification_is_deduplicated(self, get_initiators, enqueue):
		get_initiators.return_value = ["initiator@example.invalid"]

		_notify_procurement_initiators("CPO-TEST", "completed")

		enqueue.assert_called_once()
		self.assertEqual(
			enqueue.call_args.kwargs["dedupe_on"],
			["document_type", "document_name", "subject"],
		)
		self.assertIn("завершено", enqueue.call_args.args[1]["subject"])

	@patch("frappe.desk.form.assign_to.notify_assignment")
	@patch("erpnext.buying.procurement_automation.frappe.get_doc")
	@patch("erpnext.buying.procurement_automation.frappe.get_all")
	def test_stage_assignment_is_closed_without_cancellation_notification(
		self, get_all, get_doc, notify_assignment
	):
		get_all.return_value = ["TODO-TEST"]
		todo = MagicMock(status="Open")
		get_doc.return_value = todo

		_close_assignments_silently("Purchase Order", "PO-TEST")

		self.assertEqual(todo.status, "Closed")
		todo.save.assert_called_once_with(ignore_permissions=True)
		notify_assignment.assert_not_called()
