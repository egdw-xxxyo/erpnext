from unittest import TestCase
from unittest.mock import patch

import frappe

from erpnext.accounts.supplier_vat_display import (
	_item_values,
	get_supplier_paid_vat,
	invoice_breakdown,
	payment_breakdown,
	split_amount,
)


class TestSupplierVATDisplay(TestCase):
	def test_payment_advance_partial_allocation_and_refund(self):
		doc = frappe._dict(
			payment_type="Pay",
			received_amount=180,
			references=[
				frappe._dict(
					name="ROW",
					allocated_amount=120,
					reference_doctype="Purchase Invoice",
					reference_name="INV",
				)
			],
		)
		totals, rows = payment_breakdown(doc, True, lambda *_: 1 / 6)
		self.assertEqual(totals["vat"], 30)
		self.assertEqual(rows["ROW"]["vat"], 20)
		doc.payment_type = "Receive"
		doc.paid_amount = 60
		doc.references = []
		self.assertEqual(payment_breakdown(doc, True, lambda *_: 0)[0]["vat"], 10)
		self.assertEqual(payment_breakdown(doc, False, lambda *_: 0)[0]["vat"], 0)
		doc.references = [
			frappe._dict(
				name="RETURN",
				allocated_amount=-60,
				reference_doctype="Purchase Invoice",
				reference_name="RETURN",
			)
		]
		self.assertEqual(payment_breakdown(doc, False, lambda *_: 1 / 6)[0]["vat"], 10)

	def test_paid_vat_recalculates_old_payments_from_current_supplier_flag(self):
		party = frappe._dict(custom_is_vat_payer=0, check_permission=lambda *_: None)
		payment = frappe._dict(
			company="COMPANY", payment_type="Pay", received_amount=120, target_exchange_rate=2, references=[]
		)
		with patch(
			"frappe.get_doc", side_effect=lambda doctype, name: party if doctype == "Supplier" else payment
		), patch("frappe.get_list", return_value=[frappe._dict(name="OLD-PAYMENT")]), patch(
			"frappe.get_cached_value", return_value="UAH"
		):
			self.assertEqual(get_supplier_paid_vat("SUPPLIER")["groups"][0]["vat"], 0)
			party.custom_is_vat_payer = 1
			self.assertEqual(get_supplier_paid_vat("SUPPLIER")["groups"][0]["vat"], 40)
			payment.payment_type = "Receive"
			payment.paid_amount = 120
			payment.source_exchange_rate = 2
			self.assertEqual(get_supplier_paid_vat("SUPPLIER")["groups"][0]["vat"], -40)

	def test_fixed_native_vat_and_zero_total_are_preserved(self):
		tax = frappe._dict(rate=0, account_head="VAT", tax_amount=5)
		doc = frappe._dict(
			grand_total=105,
			taxes=[tax],
			items=[frappe._dict(name="ROW", qty=1, net_rate=100, net_amount=100)],
		)
		self.assertEqual(_item_values(doc, True, [tax])["ROW"]["gross_rate"], 105)
		doc.grand_total = 0
		self.assertEqual(invoice_breakdown(doc, True)[0], {"gross": 0, "net": -5, "vat": 5})

	def test_gross_workflow_extracts_vat_without_adding_it_again(self):
		doc = frappe._dict(grand_total=8496, taxes=[], items=[frappe._dict(name="ROW", qty=5, rate=207.6)])
		totals, ratio, taxes = invoice_breakdown(doc, True)
		self.assertEqual(totals, {"gross": 8496, "vat": 1416, "net": 7080})
		self.assertEqual(
			_item_values(doc, True, taxes)["ROW"],
			{"net_rate": 173, "gross_rate": 207.6, "gross_amount": 1038},
		)
		self.assertEqual(split_amount(120, ratio), {"gross": 120, "net": 100, "vat": 20})
		self.assertEqual(invoice_breakdown(doc, False)[0]["vat"], 0)

	def test_native_taxes_use_accounting_amounts_and_ignore_freight_tax_row(self):
		vat = frappe._dict(rate=20, tax_amount=20, account_head="VAT", item_wise_tax_detail='{"A":[20,20]}')
		freight = frappe._dict(rate=0, tax_amount=10, charge_type="Actual", account_head="Freight")
		doc = frappe._dict(
			grand_total=130,
			taxes=[vat, freight],
			items=[frappe._dict(name="ROW", item_code="A", qty=1, net_rate=100, net_amount=100, rate=100)],
		)
		totals, _, taxes = invoice_breakdown(doc, True)
		self.assertEqual(totals, {"gross": 130, "net": 110, "vat": 20})
		self.assertEqual(_item_values(doc, True, taxes)["ROW"]["gross_rate"], 120)
		self.assertEqual(invoice_breakdown(doc, False)[0]["vat"], 20)

	def test_repeated_items_and_discount_do_not_duplicate_native_vat(self):
		vat = frappe._dict(
			rate=20, tax_amount=30, tax_amount_after_discount_amount=24, item_wise_tax_detail='{"A":[20,30]}'
		)
		doc = frappe._dict(
			taxes=[vat],
			items=[
				frappe._dict(name=name, item_code="A", qty=1, net_rate=value, net_amount=value)
				for name, value in (("ONE", 100), ("TWO", 50))
			],
		)
		rows = _item_values(doc, True, [vat])
		self.assertEqual(rows["ONE"]["gross_rate"], 116)
		self.assertEqual(rows["TWO"]["gross_rate"], 58)
		self.assertEqual(split_amount(-120, 1 / 6), {"gross": -120, "net": -100, "vat": -20})
		self.assertEqual(split_amount(0, 0)["vat"], 0)
