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
	def test_employer_days_run_out_across_certificates(self):
		rule = sick_rules.case_rule("Illness or Injury")[0]

		self.assertEqual(sick_rules.split(4, rule), (4, 0))
		self.assertEqual(sick_rules.split(6, max(rule - 4, 0)), (1, 5))
		self.assertEqual(sick_rules.split(6, max(rule - 10, 0)), (0, 6))

	def test_number_needed_only_to_submit(self):
		doc = frappe.get_doc({"doctype": "Sick Leave Case", "eln_number": ""})

		with self.assertRaises(frappe.ValidationError):
			doc.before_submit()


class TestSickTaxes(IntegrationTestCase):
	def test_maternity_not_taxed(self):
		with patch.object(sick_rules.payroll_tax, "ssc_rate", return_value=0.22):
			result = sick_rules.taxes(1000, None, "Maternity")

		self.assertEqual((result.pit, result.military, result.withheld, result.net), (0, 0, 0, 1000))
		self.assertEqual(result.ssc, 220)

	def test_illness_taxed(self):
		result = sick_rules.taxes(1000, None, "Illness or Injury")

		self.assertGreater(result.withheld, 0)
		self.assertEqual(result.net, 1000 - result.withheld)


class TestSickDurationWarnings(IntegrationTestCase):
	def test_within_limits(self):
		self.assertEqual(sick_rules.duration_warnings("Illness or Injury", 120, 150), [])
		self.assertEqual(sick_rules.duration_warnings("Child Care", 14), [])
		self.assertEqual(sick_rules.duration_warnings("Family Member Care", 3), [])
		self.assertEqual(sick_rules.duration_warnings("Maternity", 126), [])

	def test_over_limits(self):
		self.assertEqual(len(sick_rules.duration_warnings("Illness or Injury", 121, 151)), 2)
		self.assertEqual(len(sick_rules.duration_warnings("Child Care", 15)), 1)
		self.assertEqual(len(sick_rules.duration_warnings("Family Member Care", 4)), 1)
		self.assertEqual(len(sick_rules.duration_warnings("Maternity", 140)), 1)

	def test_family_care_paid_by_fund(self):
		self.assertEqual(sick_rules.case_rule("Family Member Care"), (0, None))
