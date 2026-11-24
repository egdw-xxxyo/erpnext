import unittest
from typing import ClassVar

from erpnext.access_control.company_access_rules import (
	IN_EFFECT,
	NARROWS,
	NO_EFFECT,
	USER_DISABLED,
	access_status,
	by_module,
	desired_pairs,
	duplicate_grants,
	exclude_choices,
	global_companies,
	grant_lines,
	include_choices,
	kept_excludes,
	permission_delta,
	scope_doctypes,
	unusable_doctypes,
)

CANDIDATES = {
	"Technical Document": "Technical Documentation",
	"Technical Document Section": "Technical Documentation",
	"Product Modification": "Technical Documentation",
	"Warehouse": "Stock",
	"Stock Entry": "Stock",
	"Project": "Projects",
}


class TestScopeDoctypes(unittest.TestCase):
	def test_module_brings_every_company_doctype_of_it(self):
		self.assertEqual(
			scope_doctypes(CANDIDATES, ["Technical Documentation"], [], []),
			["Product Modification", "Technical Document", "Technical Document Section"],
		)

	def test_include_adds_and_exclude_removes(self):
		self.assertEqual(
			scope_doctypes(CANDIDATES, ["Technical Documentation"], ["Project"], ["Product Modification"]),
			["Project", "Technical Document", "Technical Document Section"],
		)

	def test_exclude_wins_over_include(self):
		self.assertEqual(scope_doctypes(CANDIDATES, [], ["Project"], ["Project"]), [])

	def test_include_without_company_link_is_dropped(self):
		self.assertEqual(scope_doctypes(CANDIDATES, [], ["ToDo", "Project"], []), ["Project"])

	def test_unusable_lists_doctypes_without_company_link(self):
		self.assertEqual(unusable_doctypes(CANDIDATES, ["ToDo", "Project", "Note"]), ["Note", "ToDo"])

	def test_by_module_groups_and_sorts(self):
		self.assertEqual(
			by_module(["Warehouse", "Project", "Stock Entry"], CANDIDATES),
			{"Projects": ["Project"], "Stock": ["Stock Entry", "Warehouse"]},
		)


class TestChoices(unittest.TestCase):
	def test_include_offers_company_doctypes_outside_chosen_modules(self):
		self.assertEqual(
			include_choices(CANDIDATES, ["Technical Documentation", "Stock"]),
			["Project"],
		)

	def test_exclude_offers_only_what_the_scope_contains(self):
		self.assertEqual(
			exclude_choices(CANDIDATES, ["Stock"], ["Project", "ToDo"]),
			["Project", "Stock Entry", "Warehouse"],
		)

	def test_excludes_outside_the_scope_are_dropped_in_order(self):
		self.assertEqual(
			kept_excludes(CANDIDATES, ["Stock"], [], ["Warehouse", "Product Modification", "Stock Entry"]),
			["Warehouse", "Stock Entry"],
		)


class TestDesiredPairs(unittest.TestCase):
	SCOPES: ClassVar[dict] = {"Tech": ["Technical Document", "Product Modification"], "Stock": ["Warehouse"]}

	def test_each_grant_opens_its_scope(self):
		self.assertEqual(
			desired_pairs([("Magura", "Tech"), ("Varnex", "Stock")], self.SCOPES, frozenset()),
			{
				("Magura", "Technical Document"),
				("Magura", "Product Modification"),
				("Varnex", "Warehouse"),
			},
		)

	def test_company_already_open_everywhere_is_skipped(self):
		self.assertEqual(desired_pairs([("Kalheon", "Tech")], self.SCOPES, frozenset({"Kalheon"})), set())

	def test_unknown_scope_opens_nothing(self):
		self.assertEqual(desired_pairs([("Magura", "Gone")], self.SCOPES, frozenset()), set())

	def test_global_companies_ignore_scoped_and_managed_rows(self):
		rows = [
			{"for_value": "Kalheon", "apply_to_all_doctypes": 1},
			{"for_value": "Magura", "apply_to_all_doctypes": 0, "applicable_for": "Warehouse"},
			{"for_value": "Varnex", "apply_to_all_doctypes": 1, "managed": "x"},
		]
		self.assertEqual(global_companies(rows), {"Kalheon"})


class TestPermissionDelta(unittest.TestCase):
	def test_adds_missing_and_removes_stale_managed_rows(self):
		rows = [
			{"name": "a", "for_value": "Magura", "applicable_for": "Warehouse", "managed": "u"},
			{"name": "b", "for_value": "Magura", "applicable_for": "Project", "managed": "u"},
		]
		desired = frozenset({("Magura", "Warehouse"), ("Magura", "Stock Entry")})
		self.assertEqual(permission_delta(desired, rows), ([("Magura", "Stock Entry")], ["b"]))

	def test_manual_rows_satisfy_and_are_never_removed(self):
		rows = [
			{"name": "m", "for_value": "Magura", "applicable_for": "Warehouse", "managed": None},
			{"name": "k", "for_value": "Kalheon", "applicable_for": None, "managed": None},
		]
		self.assertEqual(permission_delta(frozenset({("Magura", "Warehouse")}), rows), ([], []))

	def test_empty_desired_removes_every_managed_row(self):
		rows = [{"name": "a", "for_value": "Magura", "applicable_for": "Warehouse", "managed": "u"}]
		self.assertEqual(permission_delta(frozenset(), rows), ([], ["a"]))


class TestDuplicateGrants(unittest.TestCase):
	def test_reports_repeated_pairs_once(self):
		grants = [("Magura", "Tech"), ("Magura", "Tech"), ("Magura", "Stock")]
		self.assertEqual(duplicate_grants(grants), [("Magura", "Tech")])


class TestSummary(unittest.TestCase):
	def test_status_follows_what_the_grants_change(self):
		pair = {("Magura", "Warehouse")}
		self.assertEqual(access_status(True, {"Kalheon"}, pair), IN_EFFECT)
		self.assertEqual(access_status(True, set(), pair), NARROWS)
		self.assertEqual(access_status(True, {"Kalheon"}, set()), NO_EFFECT)
		self.assertEqual(access_status(False, {"Kalheon"}, pair), USER_DISABLED)

	def test_grant_lines_skip_incomplete_rows(self):
		self.assertEqual(
			grant_lines([("Magura", "Tech"), ("Varnex", None), ("Varnex", "Stock")]),
			"Magura · Tech\nVarnex · Stock",
		)


if __name__ == "__main__":
	unittest.main()
