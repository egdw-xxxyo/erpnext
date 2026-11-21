import unittest

import frappe

from erpnext.access_control.company_access import MARKER, doctype_query, preview_scope

USER = "company-access-test@example.com"
SCOPE = "Company Access Test Scope"


def companies_seen(doctype: str) -> set[str]:
	frappe.clear_cache(user=USER)
	frappe.set_user(USER)
	try:
		return set(frappe.get_list(doctype, pluck="company", limit_page_length=0))
	finally:
		frappe.set_user("Administrator")


def managed_rows() -> list[dict]:
	return frappe.get_all(
		"User Permission",
		filters={"user": USER, MARKER: ["is", "set"]},
		fields=["for_value", "applicable_for"],
	)


class TestCompanyAccess(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.flags.mute_emails = True
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(setattr, frappe.flags, "mute_emails", False)
		self.addCleanup(frappe.set_user, "Administrator")
		with_both = frappe.get_all(
			"Warehouse", filters={"company": ["is", "set"]}, pluck="company", distinct=True
		)
		with_cost_centers = set(frappe.get_all("Cost Center", pluck="company", distinct=True))
		self.main, self.extra = [c for c in with_both if c in with_cost_centers][:2]
		frappe.get_doc(
			{
				"doctype": "User",
				"email": USER,
				"first_name": "Company Access",
				"send_welcome_email": 0,
				"roles": [{"role": "Stock User"}, {"role": "Accounts User"}],
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": USER,
				"allow": "Company",
				"for_value": self.main,
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Company Access Scope",
				"scope_name": SCOPE,
				"include_doctypes": [{"document_type": "Warehouse"}],
			}
		).insert()

	def grant(self, company: str):
		return frappe.get_doc(
			{"doctype": "User Company Access", "user": USER, "grants": [{"company": company, "scope": SCOPE}]}
		).insert()

	def test_extra_company_opens_only_within_the_scope(self):
		self.assertEqual(companies_seen("Warehouse"), {self.main})
		self.grant(self.extra)
		self.assertEqual(companies_seen("Warehouse"), {self.main, self.extra})
		self.assertEqual(companies_seen("Cost Center"), {self.main})

	def test_scope_change_resyncs_its_users(self):
		self.grant(self.extra)
		scope = frappe.get_doc("Company Access Scope", SCOPE)
		scope.append("include_doctypes", {"document_type": "Cost Center"})
		scope.save()
		self.assertEqual(companies_seen("Cost Center"), {self.main, self.extra})
		scope.exclude_doctypes = []
		scope.append("exclude_doctypes", {"document_type": "Warehouse"})
		scope.save()
		self.assertEqual(companies_seen("Warehouse"), {self.main})

	def test_removing_access_drops_only_managed_rows(self):
		access = self.grant(self.extra)
		self.assertEqual(managed_rows(), [{"for_value": self.extra, "applicable_for": "Warehouse"}])
		access.delete()
		self.assertEqual(managed_rows(), [])
		self.assertTrue(
			frappe.db.exists(
				"User Permission", {"user": USER, "for_value": self.main, "apply_to_all_doctypes": 1}
			)
		)
		self.assertEqual(companies_seen("Warehouse"), {self.main})

	def test_company_already_open_everywhere_is_not_duplicated(self):
		self.grant(self.main)
		self.assertEqual(managed_rows(), [])

	def test_repeated_rows_are_refused(self):
		access = frappe.get_doc(
			{
				"doctype": "User Company Access",
				"user": USER,
				"grants": [{"company": self.extra, "scope": SCOPE}, {"company": self.extra, "scope": SCOPE}],
			}
		)
		with self.assertRaises(frappe.ValidationError):
			access.insert()

	def test_scope_refuses_doctypes_without_company(self):
		scope = frappe.get_doc(
			{
				"doctype": "Company Access Scope",
				"scope_name": SCOPE + " 2",
				"include_doctypes": [{"document_type": "ToDo"}],
			}
		)
		with self.assertRaises(frappe.ValidationError):
			scope.insert()

	def test_preview_groups_module_doctypes(self):
		result = preview_scope(modules=["Stock"])
		listed = {doctype for doctypes in result["by_module"].values() for doctype in doctypes}
		self.assertIn("Warehouse", result["by_module"]["Stock"])
		self.assertNotIn("ToDo", listed)

	def test_exclusions_outside_the_scope_are_dropped_on_save(self):
		scope = frappe.get_doc("Company Access Scope", SCOPE)
		scope.append("modules", {"module": "Stock"})
		scope.append("exclude_doctypes", {"document_type": "Stock Entry"})
		scope.save()
		self.assertEqual([r.document_type for r in scope.exclude_doctypes], ["Stock Entry"])
		scope.modules = []
		scope.save()
		self.assertEqual(scope.reload().exclude_doctypes, [])

	def test_dropdowns_offer_only_meaningful_doctypes(self):
		def names(mode, txt=""):
			filters = {"mode": mode, "modules": ["Stock"], "include": ["Cost Center"]}
			return [row[0] for row in doctype_query("DocType", txt, "name", 0, 500, filters)]

		self.assertIn("Cost Center", names("include"))
		self.assertNotIn("Warehouse", names("include"))
		self.assertNotIn("ToDo", names("include"))
		self.assertIn("Warehouse", names("exclude"))
		self.assertIn("Cost Center", names("exclude"))
		self.assertNotIn("Project", names("exclude"))
		self.assertEqual(names("exclude", "warehouse"), ["Warehouse"])

	def test_list_summary_follows_grants_and_manual_permissions(self):
		self.grant(self.extra)
		summary = frappe.db.get_value(
			"User Company Access", USER, ["access_status", "main_companies", "extra_companies"], as_dict=True
		)
		self.assertEqual(summary.access_status, "In Effect")
		self.assertEqual(summary.main_companies, self.main)
		self.assertEqual(summary.extra_companies, f"{self.extra} · {SCOPE}")
		base = frappe.db.get_value("User Permission", {"user": USER, "for_value": self.main})
		frappe.delete_doc("User Permission", base, ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("User Company Access", USER, "access_status"), "Narrows")
