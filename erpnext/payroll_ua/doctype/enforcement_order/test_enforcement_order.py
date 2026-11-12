from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.payroll_ua import enforcement


def order(name, kind="Child Alimony", method="Percent", percent=0, fixed=0, carry=0, debt=0, withheld=0):
	return frappe._dict(
		name=name,
		kind=kind,
		method=method,
		percent=percent,
		fixed_amount=fixed,
		fixed_carry=carry,
		debt_total=debt,
		withheld_total=withheld,
		end_date=None,
	)


class TestEnforcement(IntegrationTestCase):
	def calculate(self, orders, base, monthly=False):
		with patch.object(enforcement, "active_orders", return_value=orders):
			return enforcement.calculate("_T", "_C", base, "2026-11-30", monthly=monthly)

	def test_percent_of_net(self):
		# офіційно 26 000, на руки 20 020 — 50% аліментів = 10 010
		self.assertEqual(self.calculate([order("A", percent=50)], 20020), [("A", 10010.0)])

	def test_limit_without_child_alimony(self):
		items = self.calculate(
			[order("D1", kind="Other Debt", percent=40), order("D2", kind="Other Debt", percent=40)], 10000
		)

		self.assertEqual(items, [("D1", 4000.0), ("D2", 1000.0)])

	def test_child_alimony_first_and_70_percent(self):
		items = self.calculate([order("A", percent=50), order("D", kind="Other Debt", percent=50)], 10000)

		self.assertEqual(items, [("A", 5000.0), ("D", 2000.0)])

	def test_fixed_only_monthly_with_carry(self):
		orders = [order("F", method="Fixed", fixed=3000, carry=500)]

		self.assertEqual(self.calculate(orders, 10000), [])
		self.assertEqual(self.calculate(orders, 10000, monthly=True), [("F", 3500.0)])

	def test_debt_total_stops(self):
		items = self.calculate([order("D", kind="Other Debt", percent=20, debt=1000, withheld=900)], 10000)

		self.assertEqual(items, [("D", 100.0)])

	def test_encode_roundtrip(self):
		items = [("EO-1", 100.5), ("EO-2", 20.0)]

		self.assertEqual(enforcement.decode(enforcement.encode(items)), items)
