"""Regression tests for validity dates and approval-route boundaries (no database writes)."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

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

	def pricing_document(self):
		doc = Record(
			workflow_state="Чернетка",
			supplier="Supplier A",
			company="Company A",
			currency="UAH",
			conversion_rate=999,
			valid_from="2026-01-01",
			valid_until="2026-12-31",
			taxes_and_charges="Old template",
			submitted_by="forged@example.com",
			items=[Record(item_code="STOCK", qty=3, rate=120, warehouse=None)],
		)
		doc.get_doc_before_save = lambda: None
		doc.precision = lambda field: 2
		self.enterContext(patch.object(controller, "capture_final_approvers"))
		self.enterContext(patch.object(controller, "get_approval_threshold", return_value=5000))
		self.enterContext(
			patch.object(
				frappe,
				"get_cached_doc",
				return_value=Record(disabled=0, is_purchase_item=1, item_name="Stock"),
			)
		)
		self.exchange_rate = self.enterContext(patch("erpnext.setup.utils.get_exchange_rate", return_value=1))
		return doc

	def test_payer_prices_include_vat_and_hidden_exchange_rate_is_automatic(self):
		doc = self.pricing_document()
		with patch.object(frappe, "get_cached_value", side_effect=["UAH", 1]):
			controller.RecurringPurchase.validate(doc)
		self.assertEqual((doc.grand_total, doc.net_total), (360, 300))
		self.assertEqual(doc.items[0].amount, 360)
		self.assertEqual(doc.conversion_rate, 1)
		self.assertIsNone(doc.taxes_and_charges)
		self.assertIsNone(doc.submitted_by)
		self.exchange_rate.assert_called_once_with("UAH", "UAH", "2026-06-01", "for_buying")

	def test_nonpayer_has_no_vat_deduction(self):
		doc = self.pricing_document()
		with patch.object(frappe, "get_cached_value", side_effect=["UAH", 0]):
			controller.RecurringPurchase.validate(doc)
		self.assertEqual((doc.grand_total, doc.net_total), (360, 360))

	def test_approved_legacy_prices_and_actor_are_preserved(self):
		doc = self.pricing_document()
		doc.workflow_state = "Погоджено"
		before = Record(**vars(doc))
		before.net_total, before.grand_total = 360, 432
		before.ceo_approval_threshold = 5000
		before.department_approved_by = "head@example.com"
		before.submitted_by = "actual@example.com"
		doc.get_doc_before_save = lambda: before
		controller.RecurringPurchase.validate(doc)
		self.assertEqual((doc.net_total, doc.grand_total), (360, 432))
		self.assertEqual(doc.taxes_and_charges, "Old template")
		self.assertEqual(doc.submitted_by, "actual@example.com")
		self.exchange_rate.assert_not_called()

	def test_submit_records_current_user_instead_of_owner(self):
		doc = Record(owner="buyer@example.com")
		with patch.dict(frappe.session, {"user": "submitter@example.com"}):
			controller.RecurringPurchase.before_submit(doc)
		self.assertEqual(doc.submitted_by, "submitter@example.com")

	def test_gross_prices_do_not_receive_default_vat_a_second_time(self):
		source = self.source
		source.name = "REG-1"
		source.conversion_rate = 1
		source.taxes_and_charges = None
		source.supplier_vat_pricing = 1
		source.items = [Record(item_code="STOCK", qty=3, rate=120)]
		invoice = MagicMock()
		invoice.items = [Record(rate=999, item_tax_template="Default VAT")]
		with patch.object(frappe, "new_doc", return_value=invoice):
			controller.build_invoice(source)
		invoice.set.assert_called_once_with("taxes", [])
		self.assertIsNone(invoice.items[0].item_tax_template)
		self.assertEqual(invoice.items[0].rate, 120)
		invoice.calculate_taxes_and_totals.assert_called_once()
