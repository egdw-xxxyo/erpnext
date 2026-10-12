import unittest

from erpnext.access_control.permission_rules import (
	ALL,
	OWNER,
	access_delta,
	access_map,
	delta_size,
	diagnose,
	docstatus_hints,
	effective_rows,
	granting_roles,
	inert_roles,
	is_grantable,
	is_sensitive,
	normalize_rows,
	page_roles,
	rank_candidates,
	report_roles,
	risky_rights,
	share_rights_for,
	user_permission_candidates,
	workflow_options,
)

RIGHTS = ("select", "read", "write", "create", "delete", "submit", "cancel", "export", "approve")


def rows(*raw):
	return normalize_rows(raw, RIGHTS)


class TestNormalize(unittest.TestCase):
	def test_reads_flags_of_any_truthy_form(self):
		(row,) = rows(
			{"role": "A", "permlevel": "1", "if_owner": "1", "read": 1, "write": "0", "approve": True}
		)
		self.assertEqual(row["permlevel"], 1)
		self.assertTrue(row["if_owner"])
		self.assertEqual(row["rights"], frozenset({"read", "approve"}))

	def test_missing_values_are_empty(self):
		(row,) = rows({"role": "A"})
		self.assertEqual((row["permlevel"], row["if_owner"], row["rights"]), (0, False, frozenset()))


class TestAccessMap(unittest.TestCase):
	def test_unions_rights_of_all_user_roles(self):
		perms = rows({"role": "A", "read": 1}, {"role": "B", "write": 1}, {"role": "C", "delete": 1})
		self.assertEqual(access_map(perms, ["A", "B"], RIGHTS), {0: {"read": ALL, "write": ALL}})

	def test_if_owner_only_rights_are_owner_scoped(self):
		perms = rows({"role": "A", "if_owner": 1, "read": 1, "write": 1, "create": 1})
		self.assertEqual(
			access_map(perms, ["A"], RIGHTS), {0: {"read": OWNER, "write": OWNER, "create": ALL}}
		)

	def test_unrestricted_row_wins_over_if_owner_row(self):
		perms = rows({"role": "A", "if_owner": 1, "read": 1, "write": 1}, {"role": "B", "read": 1})
		self.assertEqual(access_map(perms, ["A", "B"], RIGHTS), {0: {"read": ALL, "write": OWNER}})

	def test_field_levels_are_kept_apart_and_ignore_if_owner(self):
		perms = rows({"role": "A", "read": 1}, {"role": "A", "permlevel": 1, "if_owner": 1, "read": 1})
		self.assertEqual(access_map(perms, ["A"], RIGHTS), {0: {"read": ALL}, 1: {"read": ALL}})

	def test_custom_permission_types_are_supported(self):
		perms = rows({"role": "A", "approve": 1})
		self.assertEqual(access_map(perms, ["A"], RIGHTS), {0: {"approve": ALL}})

	def test_role_without_rights_gives_nothing(self):
		self.assertEqual(access_map(rows({"role": "A"}), ["A"], RIGHTS), {})


class TestAccessDelta(unittest.TestCase):
	def test_only_new_rights_are_reported(self):
		before = {0: {"read": ALL}}
		after = {0: {"read": ALL, "write": ALL}, 1: {"read": ALL}}
		self.assertEqual(access_delta(before, after), {0: {"write": ALL}, 1: {"read": ALL}})

	def test_owner_to_all_is_a_gain(self):
		self.assertEqual(access_delta({0: {"read": OWNER}}, {0: {"read": ALL}}), {0: {"read": ALL}})

	def test_nothing_new_gives_empty_delta(self):
		self.assertEqual(access_delta({0: {"read": ALL}}, {0: {"read": ALL}}), {})


class TestCustomDocPerm(unittest.TestCase):
	def test_custom_rows_replace_standard_rows_entirely(self):
		standard = rows({"role": "Stock User", "read": 1})
		custom = rows({"role": "Buyer", "read": 1})
		source, effective = effective_rows(standard, custom)
		self.assertEqual(source, "custom")
		self.assertEqual(access_map(effective, ["Stock User"], RIGHTS), {})

	def test_without_custom_rows_standard_rows_apply(self):
		standard = rows({"role": "Stock User", "read": 1})
		self.assertEqual(effective_rows(standard, ()), ("standard", standard))

	def test_inert_roles_are_standard_roles_missing_from_custom(self):
		standard = rows({"role": "Stock User", "read": 1}, {"role": "Buyer", "read": 1}, {"role": "Empty"})
		custom = rows({"role": "Buyer", "read": 1})
		self.assertEqual(inert_roles(standard, custom), ("Stock User",))

	def test_no_inert_roles_without_custom_rows(self):
		self.assertEqual(inert_roles(rows({"role": "Stock User", "read": 1}), ()), ())


class TestGrantingRoles(unittest.TestCase):
	def test_lists_roles_with_their_scope(self):
		perms = rows(
			{"role": "A", "write": 1},
			{"role": "B", "if_owner": 1, "write": 1},
			{"role": "C", "permlevel": 1, "write": 1},
			{"role": "D", "read": 1},
		)
		self.assertEqual(granting_roles(perms, "write"), {"A": ALL, "B": OWNER})


class TestPagesAndReports(unittest.TestCase):
	def test_page_custom_roles_add_to_standard(self):
		self.assertEqual(page_roles(["A"], ["B"]), frozenset({"A", "B"}))

	def test_report_custom_roles_replace_standard(self):
		self.assertEqual(report_roles(["A"], ["B"]), frozenset({"B"}))
		self.assertEqual(report_roles(["A"], []), frozenset({"A"}))


class TestSensitivity(unittest.TestCase):
	def test_permission_and_payroll_doctypes_are_sensitive(self):
		self.assertTrue(is_sensitive("Custom DocPerm", "Core"))
		self.assertTrue(is_sensitive("Salary Slip", "Payroll"))
		self.assertFalse(is_sensitive("ToDo", "Desk"))

	def test_risky_rights_across_levels(self):
		self.assertEqual(
			risky_rights({0: {"read": ALL, "delete": ALL}, 1: {"export": ALL}}), ("delete", "export")
		)


class TestDiagnose(unittest.TestCase):
	def facts(self, **overrides):
		return {
			"scope": ALL,
			"is_owner": False,
			"controller_ok": True,
			"user_permission_ok": True,
			"shared": False,
			"allowed": True,
			**overrides,
		}

	def test_allowed_by_role(self):
		self.assertEqual(diagnose(self.facts()), {"allowed": True, "via": "role", "blockers": []})

	def test_missing_role(self):
		result = diagnose(self.facts(scope=None, allowed=False))
		self.assertEqual(result["blockers"], ["no_role"])

	def test_owner_only_role_on_foreign_document(self):
		result = diagnose(self.facts(scope=OWNER, allowed=False))
		self.assertEqual(result["blockers"], ["not_owner"])

	def test_owner_only_role_on_own_document_is_fine(self):
		self.assertTrue(diagnose(self.facts(scope=OWNER, is_owner=True))["allowed"])

	def test_user_permission_and_controller_blockers(self):
		result = diagnose(self.facts(controller_ok=False, user_permission_ok=False, allowed=False))
		self.assertEqual(result["blockers"], ["controller", "user_permission"])

	def test_share_overrides_missing_role(self):
		result = diagnose(self.facts(scope=None, shared=True))
		self.assertEqual((result["allowed"], result["via"]), (True, "share"))

	def test_doctype_level_check_skips_document_layers(self):
		result = diagnose(self.facts(is_owner=None, controller_ok=None, user_permission_ok=None))
		self.assertEqual(result["blockers"], [])

	def test_unexplained_denial(self):
		self.assertEqual(diagnose(self.facts(allowed=False))["blockers"], ["unknown"])

	def test_not_submittable(self):
		result = diagnose(self.facts(not_submittable=True, allowed=False))
		self.assertEqual(result["blockers"], ["not_submittable"])


class TestDocstatusHints(unittest.TestCase):
	def test_submitted_document(self):
		self.assertEqual(docstatus_hints("write", 1, True), ("submitted_is_read_only",))
		self.assertEqual(docstatus_hints("delete", 1, True), ("cancel_before_delete",))

	def test_cancel_and_submit_need_the_right_state(self):
		self.assertEqual(docstatus_hints("cancel", 0, True), ("only_submitted_can_be_cancelled",))
		self.assertEqual(docstatus_hints("submit", 1, True), ("only_draft_can_be_submitted",))

	def test_no_document_no_hints(self):
		self.assertEqual(docstatus_hints("write", None, True), ())


class TestWorkflowOptions(unittest.TestCase):
	def test_lists_transitions_from_current_state_only(self):
		transitions = [
			{"state": "Draft", "action": "Send", "next_state": "Review", "allowed": "Sales User"},
			{"state": "Draft", "action": "Drop", "next_state": "Dropped", "allowed": "Sales Manager"},
			{"state": "Review", "action": "Approve", "next_state": "Approved", "allowed": "Sales Manager"},
		]
		self.assertEqual(
			workflow_options(transitions, "Draft", ["Sales User"]),
			[
				{"action": "Send", "next_state": "Review", "role": "Sales User", "user_has_role": True},
				{"action": "Drop", "next_state": "Dropped", "role": "Sales Manager", "user_has_role": False},
			],
		)


class TestGranting(unittest.TestCase):
	def test_admin_roles_are_never_granted(self):
		self.assertFalse(is_grantable("System Manager"))
		self.assertFalse(is_grantable("Access Manager"))
		self.assertFalse(is_grantable("Administrator"))
		self.assertTrue(is_grantable("Sales User"))

	def test_delta_size_counts_every_new_capability(self):
		delta = {
			"doctypes": [{"access": [{"rights": {"read": ALL, "write": ALL}}, {"rights": {"read": ALL}}]}],
			"pages": [{"name": "p"}],
			"reports": [],
			"workspaces": [{"name": "w"}],
			"notifications": [],
			"workflow": {"transitions": [{}], "editable_states": []},
		}
		self.assertEqual(delta_size(delta), 6)

	def test_smallest_delta_comes_first(self):
		ranked = rank_candidates(
			[{"role": "B", "size": 9}, {"role": "A", "size": 2}, {"role": "C", "size": 2}]
		)
		self.assertEqual([candidate["role"] for candidate in ranked], ["A", "C", "B"])

	def test_share_is_not_offered_for_create_delete_cancel(self):
		self.assertIsNone(share_rights_for("delete"))
		self.assertIsNone(share_rights_for("create"))
		self.assertIsNone(share_rights_for("cancel"))
		self.assertEqual(share_rights_for("write"), ("read", "write"))
		self.assertEqual(share_rights_for("print"), ("read",))

	def test_user_permission_only_widens_existing_restrictions(self):
		links = [("Company", "Beta"), ("Company", "Beta"), ("Warehouse", "Main"), ("Company", "Alpha")]
		allowed = {"Company": ["Alpha"]}
		self.assertEqual(
			user_permission_candidates(links, allowed), [{"allow": "Company", "for_value": "Beta"}]
		)
