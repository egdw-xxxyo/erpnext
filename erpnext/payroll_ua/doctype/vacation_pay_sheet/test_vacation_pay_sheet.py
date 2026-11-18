from unittest.mock import patch

from frappe.tests import IntegrationTestCase
from frappe.utils import getdate

from erpnext.payroll_ua import vacation_rules


class TestVacationRules(IntegrationTestCase):
	def test_unpaid_days_are_the_newest(self):
		days = [getdate(f"2026-03-{day:02d}") for day in range(1, 15)]

		self.assertEqual(vacation_rules.split_unpaid(days, 5), days[5:])
		self.assertEqual(vacation_rules.split_unpaid(days, 0), days)
		self.assertEqual(vacation_rules.split_unpaid(days, 20), [])

	def test_due_date_follows_the_setting(self):
		with patch.object(vacation_rules.payroll_tax, "_setting", return_value=None):
			self.assertEqual(getdate(vacation_rules.due_date("2026-03-10")), getdate("2026-03-09"))

		with patch.object(vacation_rules.payroll_tax, "_setting", return_value=3):
			self.assertEqual(getdate(vacation_rules.due_date("2026-03-10")), getdate("2026-03-07"))

	def test_entitled_days_two_per_full_month(self):
		self.assertEqual(vacation_rules.entitled_days("2026-01-01", "2026-03-31"), 6)
		self.assertEqual(vacation_rules.entitled_days("2026-01-15", "2026-03-31"), 4)
		self.assertEqual(vacation_rules.entitled_days(None, "2026-03-31"), 0)
