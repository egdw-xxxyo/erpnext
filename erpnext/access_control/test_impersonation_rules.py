import unittest

from erpnext.access_control.impersonation_rules import (
	allowed_while_viewing,
	decide_refusal,
	in_scope,
	manage_refusal,
	manager_scope,
	requested_method,
	view_refusal,
)

MANAGER = ("Access Manager",)
SYSTEM = ("System Manager",)


def refusal(viewer_roles=MANAGER, target_roles=("Sales User",), **overrides):
	args = {
		"viewer": "am@example.com",
		"viewer_roles": viewer_roles,
		"target": "user@example.com",
		"target_roles": target_roles,
		"target_enabled": True,
		"target_type": "System User",
		"viewing": False,
		**overrides,
	}
	return view_refusal(**args)


class TestViewRefusal(unittest.TestCase):
	def test_access_manager_views_ordinary_user(self):
		self.assertIsNone(refusal())

	def test_requires_manager_role(self):
		self.assertEqual(refusal(viewer_roles=("Sales User",)), "not_manager")
		self.assertEqual(refusal(viewer_roles=SYSTEM), "not_manager")

	def test_administrator_needs_no_role(self):
		self.assertIsNone(refusal(viewer="Administrator", viewer_roles=(), target_roles=SYSTEM))

	def test_cannot_view_self(self):
		self.assertEqual(refusal(target="am@example.com"), "self")

	def test_service_users_are_refused(self):
		self.assertEqual(refusal(target="Administrator"), "service_user")
		self.assertEqual(refusal(target="Guest"), "service_user")

	def test_disabled_and_website_users_are_refused(self):
		self.assertEqual(refusal(target_enabled=False), "disabled")
		self.assertEqual(refusal(target_type="Website User"), "not_desk_user")

	def test_top_roles_need_administrator_or_both_manager_roles(self):
		self.assertEqual(refusal(target_roles=SYSTEM), "top_role")
		self.assertEqual(refusal(viewer_roles=SYSTEM, target_roles=SYSTEM), "not_manager")
		self.assertIsNone(refusal(viewer_roles=MANAGER + SYSTEM, target_roles=SYSTEM))
		self.assertIsNone(refusal(viewer="Administrator", viewer_roles=MANAGER, target_roles=SYSTEM))

	def test_nested_view_is_refused_first(self):
		self.assertEqual(refusal(viewer_roles=(), viewing=True), "viewing")


class TestRequestedMethod(unittest.TestCase):
	def test_method_from_path(self):
		self.assertEqual(requested_method("/api/method/logout", None), "logout")
		self.assertEqual(requested_method("/api/v2/method/a.b.c/", None), "a.b.c")

	def test_method_from_cmd(self):
		self.assertEqual(requested_method("/", "a.b.c"), "a.b.c")
		self.assertIsNone(requested_method("/app/todo", None))

	def test_allowed_while_viewing(self):
		allowed = {"logout"}
		self.assertTrue(allowed_while_viewing("logout", allowed))
		self.assertFalse(allowed_while_viewing("frappe.client.save", allowed))
		self.assertFalse(allowed_while_viewing(None, allowed))


def manage(manager_roles=MANAGER, target_roles=("Sales User",), **overrides):
	args = {
		"manager": "am@example.com",
		"manager_roles": manager_roles,
		"target": "user@example.com",
		"target_roles": target_roles,
		"target_enabled": True,
		**overrides,
	}
	return manage_refusal(**args)


class TestManageRefusal(unittest.TestCase):
	def test_access_manager_changes_ordinary_user(self):
		self.assertIsNone(manage())

	def test_needs_a_manager(self):
		self.assertEqual(manage(manager_roles=("Sales User",)), "not_manager")
		self.assertEqual(manage(manager_roles=SYSTEM), "not_manager")

	def test_not_own_access(self):
		self.assertEqual(manage(target="am@example.com"), "self")

	def test_not_service_or_disabled_users(self):
		self.assertEqual(manage(target="Administrator"), "service_user")
		self.assertEqual(manage(target_enabled=False), "disabled")

	def test_system_managers_only_by_administrator_or_both_manager_roles(self):
		self.assertEqual(manage(target_roles=SYSTEM), "top_role")
		self.assertIsNone(manage(manager_roles=MANAGER + SYSTEM, target_roles=SYSTEM))
		self.assertIsNone(manage(manager="Administrator", manager_roles=MANAGER, target_roles=SYSTEM))

	def test_users_outside_the_scope_are_refused(self):
		self.assertEqual(manage(in_scope=False), "out_of_scope")
		self.assertEqual(refusal(in_scope=False), "out_of_scope")


class TestDecideRefusal(unittest.TestCase):
	def test_ordinary_requests_are_decided_by_any_manager(self):
		self.assertIsNone(decide_refusal("am@example.com", MANAGER, ("Sales User",)))

	def test_system_manager_requests_need_a_top_manager(self):
		self.assertEqual(decide_refusal("am@example.com", MANAGER, SYSTEM), "top_role")
		self.assertIsNone(decide_refusal("am@example.com", MANAGER + SYSTEM, SYSTEM))
		self.assertIsNone(decide_refusal("Administrator", (), SYSTEM))

	def test_requests_outside_the_scope_are_refused(self):
		self.assertEqual(
			decide_refusal("am@example.com", MANAGER, ("Sales User",), in_scope=False), "out_of_scope"
		)


class TestManagerScope(unittest.TestCase):
	def test_administrator_and_unrestricted_managers_see_everyone(self):
		self.assertIsNone(manager_scope(True, {"Company": ["A"]}))
		self.assertIsNone(manager_scope(False, {}))
		self.assertIsNone(manager_scope(False, {"Project": ["P"], "Company": []}))

	def test_restrictions_map_to_employee_fields(self):
		self.assertEqual(
			manager_scope(False, {"Company": ["A"], "Employee": ["E1"], "Project": ["P"]}),
			{"company": frozenset({"A"}), "name": frozenset({"E1"})},
		)

	def test_employee_must_match_every_restriction(self):
		scope = {"company": frozenset({"A"}), "department": frozenset({"D"})}
		self.assertTrue(in_scope(scope, {"company": "A", "department": "D"}))
		self.assertFalse(in_scope(scope, {"company": "A", "department": "X"}))
		self.assertFalse(in_scope(scope, {"company": "B", "department": "D"}))

	def test_users_without_employee_are_hidden_from_restricted_managers(self):
		self.assertFalse(in_scope({"company": frozenset({"A"})}, None))
		self.assertTrue(in_scope(None, None))
