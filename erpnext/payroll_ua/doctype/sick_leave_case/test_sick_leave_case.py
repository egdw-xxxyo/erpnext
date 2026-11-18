from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.payroll_ua import sick_rules


def employee(years=0, months=0, joined="2020-01-01", in_full=0):
	return frappe._dict(
		name="_Test Sick Employee",
		date_of_joining=joined,
		custom_insurance_years=years,
		custom_insurance_months=months,
		custom_sick_pay_in_full=in_full,
	)


class TestSickRules(IntegrationTestCase):
	def test_employer_pays_first_days_of_the_case(self):
		self.assertEqual(sick_rules.split(10, 5), (5, 5))
		self.assertEqual(sick_rules.split(3, 5), (3, 0))
		self.assertEqual(sick_rules.split(10, 0), (0, 10))

	def test_continuation_keeps_counting_the_case(self):
		# ЕЛН 4 дні + продовження 6 днів — один випадок на 10 днів, роботодавцю лише 5
		self.assertEqual(sick_rules.split(4 + 6, sick_rules.case_rule("Illness or Injury")[0]), (5, 5))

	def test_percent_by_insurance_record(self):
		cases = (
			(employee(joined="2026-01-01"), 50.0),
			(employee(years=3, joined="2026-01-01"), 60.0),
			(employee(years=5, joined="2026-01-01"), 70.0),
			(employee(years=7, months=11, joined="2026-01-01"), 100.0),
		)

		for person, expected in cases:
			self.assertEqual(sick_rules.percent(person, "Illness or Injury", "2026-02-01")[0], expected)

	def test_percent_override(self):
		self.assertEqual(
			sick_rules.percent(employee(joined="2026-01-01"), "Maternity", "2026-02-01")[0], 100.0
		)
		self.assertEqual(
			sick_rules.percent(employee(joined="2026-01-01", in_full=1), "Illness or Injury", "2026-02-01")[
				0
			],
			100.0,
		)

	def test_insurance_record_split(self):
		record = sick_rules.insurance_record(employee(years=2, months=3, joined="2025-11-01"), "2026-11-15")

		self.assertEqual(record.before_join_months, 27)
		self.assertEqual(record.here_months, 12)
		self.assertEqual((record.years, record.months), (3, 3))

	def test_cash_weight(self):
		with patch.object(sick_rules.payroll_tax, "_setting", return_value=50):
			self.assertEqual(sick_rules.cash_unpaid_weight(), 0.5)

		with patch.object(sick_rules.payroll_tax, "_setting", return_value=None):
			self.assertEqual(sick_rules.cash_unpaid_weight(), 0.5)

		with patch.object(sick_rules.payroll_tax, "_setting", return_value=100):
			self.assertEqual(sick_rules.cash_unpaid_weight(), 0)


class TestSickLeaveCase(IntegrationTestCase):
	def case(self, *certificates):
		return frappe.get_doc(
			{
				"doctype": "Sick Leave Case",
				"certificates": [
					{"eln_number": str(index), "from_date": start, "to_date": end}
					for index, (start, end) in enumerate(certificates, start=1)
				],
			}
		)

	def test_period_from_continuations(self):
		doc = self.case(("2026-10-28", "2026-10-31"), ("2026-11-01", "2026-11-06"))
		doc.set_period()

		self.assertEqual(str(doc.start_date), "2026-10-28")
		self.assertEqual(str(doc.end_date), "2026-11-06")
		self.assertEqual(doc.calendar_days, 10)

	def test_gap_is_a_new_case(self):
		doc = self.case(("2026-10-28", "2026-10-31"), ("2026-11-03", "2026-11-06"))

		with self.assertRaises(frappe.ValidationError):
			doc.set_period()
