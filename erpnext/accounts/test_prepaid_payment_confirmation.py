"""Existing prepaid purchase evidence must not waive unrelated payment instructions."""

from unittest import TestCase
from unittest.mock import patch

import frappe

from erpnext.accounts.invoice_payment_route import _payment_progress, _prepaid_receipt
from erpnext.accounts.payment_fiscal_receipt import _update_payment_request_receipt_status


class TestPrepaidPaymentConfirmation(TestCase):
	def setUp(self):
		self.invoice = frappe._dict(
			doctype="Purchase Invoice",
			name="INV-A",
			docstatus=1,
			company="Company A",
			custom_consolidated_purchase_order="CPO-A",
			is_paid=1,
			outstanding_amount=0,
		)
		self.order = frappe._dict(
			docstatus=1,
			workflow_state="Проведено",
			company="Company A",
			items_already_purchased=1,
			items=[frappe._dict(material_request="MR-A")],
		)
		self.source = frappe._dict(
			name="MR-A",
			owner="actual-author",
			company="Company A",
			docstatus=1,
			material_request_type="Purchase",
			custom_items_already_purchased=1,
			custom_purchase_receipts=[frappe._dict(invoice_pdf="/private/files/receipt.pdf")],
		)
		self.request = frappe._dict(
			doctype="Payment Request",
			name="REQ-A",
			docstatus=0,
			status="Draft",
			reference_doctype="Purchase Invoice",
			reference_name="INV-A",
		)
		self.enterContext(
			patch(
				"frappe.get_doc",
				side_effect=lambda dt, name: {
					"Consolidated Purchase Order": self.order,
					"Material Request": self.source,
					"Purchase Invoice": self.invoice,
					"Payment Request": self.request,
				}[dt],
			)
		)
		self.enterContext(patch("frappe.db.get_value", side_effect=self.get_value))
		self.file_exists = self.enterContext(patch("frappe.db.exists", return_value=True))
		self.write = self.enterContext(patch("frappe.db.set_value"))
		self.entries = self.enterContext(patch("frappe.get_all", return_value=[]))
		self.enterContext(
			patch("erpnext.accounts.invoice_payment_route._user", side_effect=lambda user: {"user": user})
		)

	def get_value(self, dt, filters, *args, **kwargs):
		if dt == "Material Request":
			return self.source if all(self.source.get(k) == value for k, value in filters.items()) else None
		return self.request.status

	def test_receipt_completes_invoice_and_request_steps_without_payment_entries(self):
		for doc in (self.invoice, self.request):
			step = _payment_progress(doc, self.invoice)
			self.assertTrue(step["completed"])
			self.assertTrue(step["external_payment"])
			self.assertEqual(step["users"], [{"user": "actual-author"}])
		self.entries.assert_not_called()

	def test_request_links_existing_receipt_without_changing_accounting_status(self):
		_update_payment_request_receipt_status("REQ-A")
		self.assertEqual(
			self.write.call_args.args[2],
			{
				"custom_fiscal_receipt_status": "Додано",
				"custom_payment_instruction_url": "/private/files/receipt.pdf",
			},
		)
		self.assertEqual(self.request.status, "Draft")

	def test_plain_or_unpaid_invoice_and_return_do_not_qualify(self):
		for values in (
			{"custom_consolidated_purchase_order": None},
			{"docstatus": 0},
			{"docstatus": 2},
			{"is_paid": 0, "outstanding_amount": 100},
			{"is_return": 1},
		):
			with self.subTest(values=values), patch.dict(self.invoice, values):
				self.assertIsNone(_prepaid_receipt(self.invoice))

	def test_marking_cpo_paid_cannot_replace_paid_original_request(self):
		for values in ({"custom_items_already_purchased": 0}, {"docstatus": 0}, {"company": "Other"}):
			with self.subTest(values=values), patch.dict(self.source, values):
				self.assertIsNone(_prepaid_receipt(self.invoice))

	def test_missing_or_deleted_source_receipt_does_not_qualify(self):
		with patch.dict(self.source, {"custom_purchase_receipts": []}):
			self.assertIsNone(_prepaid_receipt(self.invoice))
		self.file_exists.return_value = False
		self.assertIsNone(_prepaid_receipt(self.invoice))

	def test_unapproved_or_nonprepaid_order_does_not_qualify(self):
		for values in ({"docstatus": 0}, {"items_already_purchased": 0}, {"company": "Other"}):
			with self.subTest(values=values), patch.dict(self.order, values):
				self.assertIsNone(_prepaid_receipt(self.invoice))

	def test_ordinary_paid_invoice_still_needs_its_own_instruction(self):
		self.invoice.custom_consolidated_purchase_order = None
		self.entries.side_effect = [["PAY-A"], [frappe._dict(owner="treasurer", custom_fiscal_receipt="")]]
		self.assertFalse(_payment_progress(self.invoice, self.invoice)["completed"])
