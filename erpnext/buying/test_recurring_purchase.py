"""Regression tests for validity dates and approval-route boundaries (no database writes)."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe

from erpnext.buying import recurring_purchase as integration
from erpnext.buying.doctype.recurring_purchase import recurring_purchase as controller


class Record(SimpleNamespace):
	def get(self, key, default=None):
		return getattr(self, key, default)

	def check_permission(self, permission):
		pass


class TestRecurringPurchase(TestCase):
	def setUp(self):
		self.source = Record(
			docstatus=1,
			workflow_state="Проведено",
			valid_from="2026-01-01",
			valid_until="2026-12-31",
			supplier="Supplier A",
			company="Company A",
			currency="UAH",
			items=[Record(item_code="STOCK"), Record(item_code="SERVICE")],
		)
		self.invoice = Record(
			custom_recurring_purchase="REG-1",
			supplier="Supplier A",
			company="Company A",
			currency="UAH",
			posting_date="2026-06-01",
			update_stock=0,
			items=[Record(item_code="STOCK", qty=1000, rate=9999)],
			_action="save",
		)
		self.invoice.is_new = lambda: True
		self.invoice.get_doc_before_save = lambda: None
		self.enterContext(patch.object(controller, "today", return_value="2026-06-01"))
		self.enterContext(patch.object(controller, "_", side_effect=lambda text: text))
		self.enterContext(patch.object(integration, "_", side_effect=lambda text: text))
		self.enterContext(patch.object(frappe, "throw", side_effect=frappe.ValidationError))
		self.enterContext(patch.object(frappe, "get_doc", return_value=self.source))

	def test_validity_includes_both_boundaries(self):
		for date in ("2026-01-01", "2026-12-31"):
			with patch.object(controller, "today", return_value=date):
				controller.check_active(self.source, date)

	def test_backdating_cannot_bypass_expiry(self):
		with patch.object(controller, "today", return_value="2027-01-01"):
			with self.assertRaises(frappe.ValidationError):
				controller.check_active(self.source, "2026-06-01")

	def test_outside_posting_date_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			controller.check_active(self.source, "2027-01-01")

	def test_draft_and_cancelled_sources_are_rejected(self):
		for status in (0, 2):
			self.source.docstatus = status
			with self.assertRaises(frappe.ValidationError):
				integration.validate_invoice(self.invoice)

	def test_stock_and_services_are_allowed_without_quantity_or_price_limits(self):
		integration.validate_invoice(self.invoice)
		self.invoice.items = [Record(item_code="SERVICE", qty=2, rate=50000)]
		integration.validate_invoice(self.invoice)

	def test_unapproved_item_is_rejected(self):
		self.invoice.items = [Record(item_code="OTHER")]
		with self.assertRaises(frappe.ValidationError):
			integration.validate_invoice(self.invoice)

	def test_supplier_company_and_currency_cannot_be_swapped(self):
		for field in ("supplier", "company", "currency"):
			with patch.object(self.invoice, field, "OTHER"):
				with self.assertRaises(frappe.ValidationError):
					integration.validate_invoice(self.invoice)

	def test_stock_is_received_separately(self):
		self.invoice.update_stock = 1
		with self.assertRaises(frappe.ValidationError):
			integration.validate_invoice(self.invoice)

	def test_submitting_old_draft_rechecks_validity(self):
		self.invoice.is_new = lambda: False
		self.invoice._action = "submit"
		with patch.object(controller, "today", return_value="2027-01-01"):
			with self.assertRaises(frappe.ValidationError):
				integration.validate_invoice(self.invoice)

	def test_source_cannot_be_removed_after_first_save(self):
		self.invoice.get_doc_before_save = lambda: Record(custom_recurring_purchase="REG-1")
		self.invoice.custom_recurring_purchase = None
		with self.assertRaises(frappe.ValidationError):
			integration.validate_invoice(self.invoice)

	def test_existing_invoice_can_be_paid_after_expiry(self):
		from erpnext.accounts.payment_procurement_route import _has_approved_procurement_source

		request = Record(reference_doctype="Purchase Invoice", reference_name="INV-1")
		with patch.object(
			frappe.db,
			"get_value",
			side_effect=[
				Record(docstatus=1, custom_recurring_purchase="REG-1"),
				self.source,
			],
		):
			self.assertTrue(_has_approved_procurement_source(request))

	def test_draft_invoice_cannot_bypass_payment_approval(self):
		from erpnext.accounts.payment_procurement_route import _has_approved_procurement_source

		request = Record(reference_doctype="Purchase Invoice", reference_name="INV-1")
		with patch.object(frappe.db, "get_value", return_value=Record(docstatus=0)):
			self.assertFalse(_has_approved_procurement_source(request))
