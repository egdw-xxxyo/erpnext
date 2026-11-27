import unittest

import frappe
from frappe import _

from erpnext.access_control import user_permission_scan
from erpnext.access_control.denial import create_request, get_denial, resolve
from erpnext.access_control.doctype.access_request.access_request import (
	approve,
	get_approval_options,
	get_user_permission_preview,
	recheck,
)

USER = "access-up-test@example.com"


def new_user(email: str, roles: list[str]):
	frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": "UP Test",
			"send_welcome_email": 0,
			"roles": [{"role": role} for role in roles],
		}
	).insert(ignore_permissions=True)


def allow(user: str, doctype: str, value: str, applicable_for: str | None = None):
	frappe.get_doc(
		{
			"doctype": "User Permission",
			"user": user,
			"allow": doctype,
			"for_value": value,
			"apply_to_all_doctypes": 0 if applicable_for else 1,
			"applicable_for": applicable_for,
		}
	).insert(ignore_permissions=True)
	frappe.clear_cache(user=user)


def restore():
	frappe.set_user("Administrator")
	frappe.clear_cache(user=USER)
	frappe.flags.mute_emails = False


class UserPermissionCase(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.flags.mute_emails = True
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(restore)
		warehouses = frappe.get_all("Warehouse", filters={"is_group": 0}, pluck="name", limit=2)
		if len(warehouses) < 2:
			self.skipTest("needs two warehouses")
		self.allowed, self.blocked = warehouses[:2]
		new_user(USER, ["Stock User"])
		allow(USER, "Warehouse", self.allowed)

	def request(self, warehouse: str) -> str:
		frappe.set_user(USER)
		doc = frappe.get_doc(
			{
				"doctype": "Access Request",
				"request_type": "Document Type",
				"reference_doctype": "Warehouse",
				"reference_name": warehouse,
				"ptype": "read",
			}
		).insert(ignore_permissions=True)
		frappe.set_user("Administrator")
		return doc.name


class TestScan(UserPermissionCase):
	def test_document_links_name_the_table_field_and_row(self):
		order = frappe.new_doc("Sales Order")
		order.append("items", {"item_code": "A", "warehouse": self.allowed})
		order.append("items", {"item_code": "B", "warehouse": self.blocked})
		self.assertIn(
			{
				"allow": "Warehouse",
				"value": self.blocked,
				"field": _(frappe.get_meta("Sales Order Item").get_field("warehouse").label),
				"table": _(order.meta.get_field("items").label),
				"row": 2,
			},
			user_permission_scan.document_links(order),
		)

	def test_blocks_list_only_values_outside_the_users_permissions(self):
		order = frappe.new_doc("Sales Order")
		order.append("items", {"item_code": "A", "warehouse": self.allowed})
		order.append("items", {"item_code": "B", "warehouse": self.blocked})
		order.append("items", {"item_code": "C", "warehouse": self.blocked})
		blocks = user_permission_scan.blocks(order, USER)
		self.assertEqual(
			[(block["allow"], block["for_value"]) for block in blocks], [("Warehouse", self.blocked)]
		)
		self.assertEqual(blocks[0]["places"][0]["rows"], [2, 3])

	def test_value_allowed_for_one_doctype_unblocks_only_that_doctype(self):
		allow(USER, "Warehouse", self.blocked, applicable_for="Sales Order")
		self.assertIn(self.blocked, user_permission_scan.allowed_for(USER, "Sales Order")["Warehouse"])
		self.assertNotIn(self.blocked, user_permission_scan.allowed_for(USER, "Delivery Note")["Warehouse"])

	def test_doctype_values_collect_restricted_links_of_every_document(self):
		documents, limited = user_permission_scan.doctype_values("Warehouse", {"Warehouse"})
		self.assertFalse(limited)
		self.assertEqual(documents[self.blocked], {("Warehouse", self.blocked)})


class TestUserPermissionGrant(UserPermissionCase):
	def test_situation_names_the_blocking_value(self):
		name = self.request(self.blocked)
		situation = get_approval_options(name)["situation"]
		self.assertEqual(
			[(block["allow"], block["for_value"]) for block in situation["user_permission_blocks"]],
			[("Warehouse", self.blocked)],
		)

	def test_offer_includes_values_blocking_other_documents(self):
		options = get_approval_options(self.request(self.blocked))
		self.assertEqual(options["user_permissions"], [{"allow": "Warehouse", "for_value": self.blocked}])
		others = options["user_permission_others"]
		self.assertTrue(others)
		self.assertNotIn(self.blocked, [entry["for_value"] for entry in others])
		self.assertTrue(all(entry["documents"] > 0 for entry in others))

	def test_preview_counts_documents_the_grant_opens(self):
		name = self.request(self.blocked)
		before = get_user_permission_preview(name, [])
		after = get_user_permission_preview(name, [{"allow": "Warehouse", "for_value": self.blocked}])
		self.assertEqual(after["blocked_after"], before["blocked_after"] - 1)
		self.assertNotIn(self.blocked, [entry["for_value"] for entry in after["remaining"]])

	def test_grant_is_limited_to_the_requested_doctype_by_default(self):
		name = self.request(self.blocked)
		approve(name, "User Permission", user_permissions=[{"allow": "Warehouse", "for_value": self.blocked}])
		granted = frappe.get_all(
			"User Permission",
			filters={"user": USER, "for_value": self.blocked},
			fields=["apply_to_all_doctypes", "applicable_for"],
		)
		self.assertEqual(
			[(row.apply_to_all_doctypes, row.applicable_for) for row in granted], [(0, "Warehouse")]
		)

	def test_grant_for_every_doctype(self):
		name = self.request(self.blocked)
		approve(
			name,
			"User Permission",
			user_permissions=[{"allow": "Warehouse", "for_value": self.blocked}],
			user_permission_scope="all",
		)
		self.assertTrue(
			frappe.db.exists(
				"User Permission", {"user": USER, "for_value": self.blocked, "apply_to_all_doctypes": 1}
			)
		)

	def test_value_from_another_document_can_be_granted(self):
		name = self.request(self.blocked)
		other = get_approval_options(name)["user_permission_others"][0]["for_value"]
		approve(
			name,
			"User Permission",
			user_permissions=[
				{"allow": "Warehouse", "for_value": self.blocked},
				{"allow": "Warehouse", "for_value": other},
			],
		)
		self.assertTrue(frappe.db.exists("User Permission", {"user": USER, "for_value": other}))

	def test_value_that_blocks_nothing_is_refused(self):
		name = self.request(self.blocked)
		with self.assertRaises(frappe.ValidationError):
			approve(
				name, "User Permission", user_permissions=[{"allow": "Warehouse", "for_value": self.allowed}]
			)


class TestRecheck(UserPermissionCase):
	def test_request_stays_pending_while_access_is_missing(self):
		name = self.request(self.blocked)
		self.assertFalse(recheck(name)["allowed"])
		self.assertEqual(frappe.db.get_value("Access Request", name, "status"), "Pending")

	def test_request_closes_when_access_was_given_elsewhere(self):
		name = self.request(self.blocked)
		allow(USER, "Warehouse", self.blocked, applicable_for="Warehouse")
		self.assertTrue(recheck(name)["allowed"])
		doc = frappe.get_doc("Access Request", name)
		self.assertEqual(
			(doc.status, doc.decided_by, doc.resolution), ("Already Granted", "Administrator", "")
		)

	def test_other_request_cannot_be_checked(self):
		frappe.set_user(USER)
		name = (
			frappe.get_doc({"doctype": "Access Request", "request_type": "Other"})
			.insert(ignore_permissions=True)
			.name
		)
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			recheck(name)


class TestNotFound(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)

	def test_missing_page_or_doctype_is_not_found(self):
		self.assertEqual(
			resolve({"kind": "page_or_doctype", "slug": "null"})["kind"],
			"not_found",
		)

	def test_existing_targets_are_resolved_as_before(self):
		self.assertEqual(
			resolve({"kind": "page_or_doctype", "slug": "sales-order"})["doctype"], "Sales Order"
		)
		page = frappe.get_all("Page", pluck="name", limit=1)[0]
		self.assertEqual(resolve({"kind": "page_or_doctype", "slug": page})["kind"], "page")
		workspace = frappe.get_all("Workspace", pluck="name", limit=1)
		if workspace:
			self.assertEqual(resolve({"kind": "page_or_doctype", "slug": workspace[0]})["kind"], "other")

	def test_missing_page_report_and_doctype_are_not_found(self):
		for context in (
			{"kind": "page", "page": "no-such-page"},
			{"kind": "report", "report": "No Such Report"},
			{"kind": "doctype", "doctype": "No Such DocType", "name": None, "ptype": "read"},
		):
			self.assertEqual(resolve(context)["kind"], "not_found", context)

	def test_missing_document_of_an_existing_doctype_asks_for_the_doctype(self):
		context = resolve(
			{"kind": "doctype", "doctype": "Warehouse", "name": "No Such Warehouse", "ptype": "read"}
		)
		self.assertEqual((context["kind"], context["name"]), ("doctype", None))

	def test_nothing_can_be_requested_for_a_missing_target(self):
		context = {"kind": "page_or_doctype", "slug": "null"}
		self.assertFalse(get_denial(context)["can_request"])
		with self.assertRaises(frappe.ValidationError):
			create_request(context, reason="test")
