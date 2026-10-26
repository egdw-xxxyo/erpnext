import json
import unittest

import frappe
from frappe.utils import add_to_date, now_datetime

from erpnext.access_control.console import (
	change_access,
	get_change_options,
	preview_change,
	who_can,
)
from erpnext.access_control.doctype.access_request.access_request import _expire, approve, reject, revoke
from erpnext.access_control.impersonation import get_users

USER = "access-console-test@example.com"
MANAGER = "access-console-manager@example.com"
COLLEAGUE = "access-console-colleague@example.com"


def roles_of(user: str) -> set[str]:
	return set(frappe.get_all("Has Role", filters={"parenttype": "User", "parent": user}, pluck="role"))


class TestConsoleChanges(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.flags.mute_emails = True
		self.addCleanup(frappe.db.rollback)
		frappe.get_doc(
			{
				"doctype": "User",
				"email": USER,
				"first_name": "Console Test",
				"send_welcome_email": 0,
				"roles": [{"role": "Stock User"}],
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.flags.mute_emails = False
		frappe.set_user("Administrator")

	def test_grant_is_logged_as_an_approved_console_request(self):
		result = change_access(USER, "grant", "needs sales", roles=["Sales User"])
		doc = frappe.get_doc("Access Request", result["name"])
		self.assertIn("Sales User", roles_of(USER))
		self.assertEqual(
			(doc.source, doc.status, doc.resolution, doc.user), ("Console", "Approved", "Role", USER)
		)
		self.assertEqual(doc.decided_by, "Administrator")
		self.assertEqual(doc.reason, "needs sales")

	def test_reason_is_optional(self):
		result = change_access(USER, "grant", "  ", roles=["Sales User"])
		self.assertIsNone(frappe.db.get_value("Access Request", result["name"], "reason"))
		self.assertIn("Sales User", roles_of(USER))

	def test_privileged_roles_are_not_granted(self):
		with self.assertRaises(frappe.ValidationError):
			change_access(USER, "grant", "x", roles=["System Manager"])
		self.assertNotIn("System Manager", roles_of(USER))

	def test_removal_can_be_revoked(self):
		result = change_access(USER, "remove", "left the warehouse", roles=["Stock User"])
		self.assertNotIn("Stock User", roles_of(USER))
		revoke(result["name"])
		self.assertIn("Stock User", roles_of(USER))

	def test_temporary_grant_expires(self):
		till = add_to_date(now_datetime(), hours=1)
		result = change_access(USER, "grant", "audit", roles=["Sales User"], valid_till=str(till))
		frappe.db.set_value(
			"Access Request", result["name"], "valid_till", add_to_date(now_datetime(), hours=-1)
		)
		frappe.db.set_value("Access Request", result["name"], "title", "kept title")
		_expire(result["name"])
		self.assertNotIn("Sales User", roles_of(USER))
		self.assertEqual(
			frappe.db.get_value("Access Request", result["name"], ["status", "title"]),
			("Expired", "kept title"),
		)

	def test_temporary_access_must_end_in_the_future(self):
		with self.assertRaises(frappe.ValidationError):
			change_access(
				USER,
				"grant",
				"x",
				roles=["Sales User"],
				valid_till=str(add_to_date(now_datetime(), hours=-1)),
			)

	def test_removal_cannot_be_temporary(self):
		with self.assertRaises(frappe.ValidationError):
			change_access(
				USER,
				"remove",
				"x",
				roles=["Stock User"],
				valid_till=str(add_to_date(now_datetime(), hours=1)),
			)

	def test_own_access_cannot_be_changed(self):
		with self.assertRaises(frappe.PermissionError):
			change_access("Administrator", "grant", "x", roles=["Sales User"])

	def test_options_and_preview(self):
		options = get_change_options(USER)
		self.assertIn("Stock User", options["roles"])
		self.assertNotIn("System Manager", [entry["role"] for entry in options["grantable"]])
		delta = preview_change(USER, "remove", roles=json.dumps(["Stock User"]))
		self.assertEqual(delta["lost_roles"], ["Stock User"])

	def test_request_insert_cannot_pretend_to_be_a_console_change(self):
		doc = frappe.get_doc(
			{
				"doctype": "Access Request",
				"user": USER,
				"source": "Console",
				"status": "Approved",
				"request_type": "Other",
				"valid_till": add_to_date(now_datetime(), hours=1),
			}
		).insert(ignore_permissions=True)
		self.assertEqual((doc.source, doc.status, doc.user), ("Request", "Pending", "Administrator"))
		self.assertIsNone(doc.valid_till)

	def test_who_can_lists_granting_roles(self):
		roles = who_can("ToDo", "read")
		self.assertIn("All", roles)
		with self.assertRaises(frappe.ValidationError):
			who_can("ToDo", "submit")


def new_user(email: str, roles: list[str]):
	frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"roles": [{"role": role} for role in roles],
		}
	).insert(ignore_permissions=True)


def new_employee(user: str, company: str):
	frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": user.split("@")[0],
			"gender": frappe.get_all("Gender", pluck="name", limit=1)[0],
			"date_of_birth": "1990-01-01",
			"date_of_joining": "2020-01-01",
			"company": company,
			"user_id": user,
		}
	).insert(ignore_permissions=True, ignore_mandatory=True)


class TestManagerScope(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.flags.mute_emails = True
		self.addCleanup(frappe.db.rollback)
		self.company = frappe.get_all("Company", pluck="name", limit=1)[0]
		new_user(USER, ["Stock User"])
		new_user(COLLEAGUE, ["Stock User"])
		new_user(MANAGER, ["Access Manager"])
		new_employee(COLLEAGUE, self.company)
		frappe.get_doc(
			{"doctype": "User Permission", "user": MANAGER, "allow": "Company", "for_value": self.company}
		).insert(ignore_permissions=True)
		frappe.clear_cache(user=MANAGER)
		frappe.set_user(MANAGER)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.clear_cache(user=MANAGER)
		frappe.flags.mute_emails = False

	def test_restricted_manager_sees_only_employees_of_the_company(self):
		names = [user["user"] for user in get_users()]
		self.assertIn(COLLEAGUE, names)
		self.assertNotIn(USER, names)

	def test_restricted_manager_decides_only_requests_within_the_scope(self):
		frappe.set_user(USER)
		outside = frappe.get_doc({"doctype": "Access Request", "request_type": "Other"}).insert(
			ignore_permissions=True
		)
		frappe.set_user(COLLEAGUE)
		inside = frappe.get_doc({"doctype": "Access Request", "request_type": "Other"}).insert(
			ignore_permissions=True
		)
		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			reject(outside.name)
		with self.assertRaises(frappe.PermissionError):
			approve(outside.name, "Role", roles=["Sales User"])
		reject(inside.name)
		self.assertEqual(frappe.db.get_value("Access Request", inside.name, "status"), "Rejected")

	def test_restricted_manager_cannot_change_users_outside_the_scope(self):
		with self.assertRaises(frappe.PermissionError):
			change_access(USER, "grant", None, roles=["Sales User"])
		change_access(COLLEAGUE, "grant", None, roles=["Sales User"])
		self.assertIn("Sales User", roles_of(COLLEAGUE))


class TestAccessManagerGuard(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.flags.mute_emails = True
		self.addCleanup(frappe.db.rollback)
		new_user(USER, ["Stock User"])
		new_user(MANAGER, ["System Manager"])

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.mute_emails = False

	def test_system_manager_cannot_grant_access_manager(self):
		frappe.set_user(MANAGER)
		user = frappe.get_doc("User", USER)
		user.append("roles", {"role": "Access Manager"})
		with self.assertRaises(frappe.ValidationError):
			user.save()

	def test_administrator_grants_and_removes_access_manager(self):
		frappe.get_doc("User", USER).add_roles("Access Manager")
		self.assertIn("Access Manager", roles_of(USER))
		frappe.get_doc("User", USER).remove_roles("Access Manager")
		self.assertNotIn("Access Manager", roles_of(USER))

	def test_system_manager_is_not_an_access_manager(self):
		request = frappe.get_doc({"doctype": "Access Request", "request_type": "Other"}).insert(
			ignore_permissions=True
		)
		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			get_users()
		self.assertNotIn(request.name, frappe.get_list("Access Request", pluck="name"))
