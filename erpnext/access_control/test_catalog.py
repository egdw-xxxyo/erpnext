import unittest

from erpnext.access_control.catalog import matches, option


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


class TestCatalogOption(unittest.TestCase):
	def test_title_is_escaped(self):
		self.assertNotIn("<script>", option(entry(title="<script>"))["label"])

	def test_route_and_lock(self):
		result = option(
			entry(kind="report", title="General Ledger", route=["query-report", "General Ledger"])
		)
		self.assertEqual(result["route"], ["query-report", "General Ledger"])
		self.assertIn("fa-lock", result["label"])

	def test_values_differ_by_kind(self):
		self.assertNotEqual(
			option(entry(kind="doctype", title="Sales"))["value"],
			option(entry(kind="page", title="Sales", route=["sales"]))["value"],
		)
