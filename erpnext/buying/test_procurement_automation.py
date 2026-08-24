from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext.buying.procurement_automation import (
	_close_assignments_silently,
	_get_consolidated_item_rate,
	_notify_procurement_initiators,
	create_external_payment_purchase_receipt,
)


class TestProcurementAutomation(FrappeTestCase):
	@patch("erpnext.stock.get_item_details.get_price_list_rate_for")
	@patch("erpnext.buying.procurement_automation.frappe.get_cached_value")
	def test_consolidated_item_rate_falls_back_to_buying_price_list(
		self, get_cached_value, get_price_list_rate_for
	):
		get_cached_value.return_value = 0
		get_price_list_rate_for.return_value = 425

		rate = _get_consolidated_item_rate(
			frappe._dict(
				item_code="ITEM-1",
				base_rate=0,
				rate=0,
				uom="Nos",
				stock_uom="Nos",
				qty=2,
				conversion_factor=1,
			),
			frappe._dict(rate=0, price_list_rate=0, stock_uom="Nos", conversion_factor=1),
			frappe._dict(buying_price_list="Standard Buying", transaction_date="2026-08-24"),
			"SUPPLIER-1",
		)

		self.assertEqual(rate, 425)
		self.assertEqual(get_price_list_rate_for.call_args.args[0].supplier, "SUPPLIER-1")

	@patch("erpnext.stock.get_item_details.get_price_list_rate_for")
	def test_consolidated_item_rate_keeps_material_request_rate(self, get_price_list_rate_for):
		rate = _get_consolidated_item_rate(
			frappe._dict(item_code="ITEM-1", base_rate=0, rate=0),
			frappe._dict(rate=300, price_list_rate=300),
			frappe._dict(buying_price_list="Standard Buying"),
		)

		self.assertEqual(rate, 300)
		get_price_list_rate_for.assert_not_called()

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
