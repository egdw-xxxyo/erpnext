import frappe
from frappe.tests import IntegrationTestCase

from erpnext.hr.average_pay import ledger_tenure


class TestInsuranceLedger(IntegrationTestCase):
	def test_full_months_and_remainder_days(self):
		rows = [
			frappe._dict(period_start="2024-01-01", days=31),
			frappe._dict(period_start="2024-02-01", days=29),
			frappe._dict(period_start="2024-03-01", days=17),
			frappe._dict(period_start="2024-04-01", days=18),
		]

		self.assertEqual(ledger_tenure(rows), 3)

	def test_empty_gap_month_is_not_counted(self):
		rows = [
			frappe._dict(period_start="2021-09-01", days=30),
			frappe._dict(period_start="2021-11-01", days=28),
		]

		self.assertEqual(ledger_tenure(rows), 1)
