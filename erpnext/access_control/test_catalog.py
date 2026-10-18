import unittest

from erpnext.access_control.catalog import matches, option, search_inaccessible


def entry(kind="doctype", title="Payroll Entry", route=None):
	return {
		"kind": kind,
		"name": title,
		"title": title,
		"module": "Payroll",
		"route": route or ["List", title],
	}


class TestCatalogMatch(unittest.TestCase):
	def test_every_word_must_match(self):
		self.assertTrue(matches(entry(), ["payroll", "entry"]))
		self.assertFalse(matches(entry(), ["payroll", "slip"]))

	def test_empty_query_matches_nothing(self):
		self.assertFalse(matches(entry(), []))


class TestCatalogSearch(unittest.TestCase):
	def test_short_query_returns_nothing(self):
		self.assertEqual(search_inaccessible(" pa "), {"total": 0, "items": []})


class TestCatalogOption(unittest.TestCase):
	def test_report_keeps_route_and_kind(self):
		result = option(
			entry(kind="report", title="General Ledger", route=["query-report", "General Ledger"])
		)
		self.assertEqual(result["route"], ["query-report", "General Ledger"])
		self.assertEqual(result["title"], "General Ledger")
		self.assertTrue(result["kind"])

	def test_single_has_no_kind(self):
		result = option(entry(kind="single", title="Payroll Settings"))
		self.assertEqual(result["kind"], "")
