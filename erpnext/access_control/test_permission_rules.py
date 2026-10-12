import unittest

from erpnext.access_control.permission_rules import (
	ALL,
	OWNER,
	access_delta,
	access_map,
	applicable_rights,
	chosen_rights,
	coverage,
	delta_size,
	diagnose,
	docstatus_hints,
	effective_rows,
	granting_roles,
	held_rights,
	inert_roles,
	is_grantable,
	is_offerable_profile,
	is_revocable,
	is_sensitive,
	merge_granting,
	missing_rights,
	normalize_rows,
	page_roles,
	rank_candidates,
	rank_profiles,
	report_roles,
	requested_rights,
	rights_to_add,
	risky_rights,
	role_grant_log,
	role_right_refusal,
	role_right_unavailable,
	roles_after_profile,
	roles_after_revoke,
	rows_with_rights,
	same_rows,
	share_coverage,
	share_rights_for,
	share_unavailable,
	user_permission_candidates,
	user_permission_unavailable,
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

	def test_share_unavailable_reasons(self):
		self.assertEqual(share_unavailable(False, "read"), "no_document")
		self.assertEqual(share_unavailable(True, "delete"), "not_shareable")
		self.assertIsNone(share_unavailable(True, "write"))

	def test_user_permission_unavailable_reasons(self):
		links = [("Company", "Alpha"), ("Warehouse", None)]
		self.assertEqual(user_permission_unavailable(False, links, {}), "no_document")
		self.assertEqual(user_permission_unavailable(True, links, {}), "no_restrictions")
		self.assertEqual(user_permission_unavailable(True, links, {"Company": ["Alpha"]}), "already_allowed")
		self.assertIsNone(user_permission_unavailable(True, links, {"Company": ["Beta"]}))

	def test_profile_is_offered_only_when_it_grants_and_is_not_privileged(self):
		self.assertTrue(is_offerable_profile(["Accounts User", "Sales User"], {"Accounts User": ALL}))
		self.assertFalse(is_offerable_profile(["Sales User"], {"Accounts User": ALL}))
		self.assertFalse(is_offerable_profile(["Accounts User", "System Manager"], {"Accounts User": ALL}))

	def test_roles_after_profile_add_keeps_current_profiles(self):
		current = [["Sales User"], ["Stock User", "Sales User"]]
		self.assertEqual(
			roles_after_profile("add", current, ["Accounts User"]),
			["Accounts User", "Sales User", "Stock User"],
		)
		self.assertEqual(roles_after_profile("replace", current, ["Accounts User"]), ["Accounts User"])
		self.assertEqual(roles_after_profile("add", [], ["Accounts User"]), ["Accounts User"])

	def test_profiles_rank_losses_first_then_size(self):
		ranked = rank_profiles(
			[
				{"profile": "Wide", "size": 30, "lost_roles": []},
				{"profile": "Lossy", "size": 2, "lost_roles": ["Sales User"]},
				{"profile": "Narrow", "size": 5, "lost_roles": []},
			]
		)
		self.assertEqual([candidate["profile"] for candidate in ranked], ["Narrow", "Wide", "Lossy"])

	def test_applicable_rights_drop_submit_and_import_when_not_supported(self):
		rights = ["select", "read", "write", "submit", "cancel", "amend", "import", "export"]
		self.assertEqual(applicable_rights(rights, False, False), ["read", "write", "export"])
		self.assertEqual(applicable_rights(rights, True, True), rights[1:])

	def test_requested_rights_always_include_read_and_denied_right(self):
		applicable = ["read", "write", "create", "delete", "export"]
		self.assertEqual(
			requested_rights("delete", ["export", "bogus"], applicable), ["read", "delete", "export"]
		)
		self.assertEqual(requested_rights(None, [], applicable), ["read"])
		self.assertEqual(requested_rights("select", [], applicable), ["read", "select"])

	def test_chosen_rights_keep_applicable_order_and_fall_back_when_empty(self):
		applicable = ["read", "write", "create", "delete"]
		self.assertEqual(chosen_rights(applicable, ["delete", "read", "bogus"], ["read"]), ["read", "delete"])
		self.assertEqual(chosen_rights(applicable, [], ["read", "write"]), ["read", "write"])
		self.assertEqual(chosen_rights(applicable, None, ["read"]), ["read"])

	def test_coverage_and_missing_rights(self):
		rows = [
			{"role": "A", "permlevel": 0, "if_owner": 0, "rights": ("read", "write")},
			{"role": "B", "permlevel": 0, "if_owner": 1, "rights": ("delete",)},
		]
		covered = coverage(rows, ["A", "B"], ["read", "write", "delete", "export"])
		self.assertEqual(covered, {"read": ALL, "write": ALL, "delete": OWNER})
		self.assertEqual(missing_rights(covered, ["read", "delete", "export"]), ["export"])

	def test_share_coverage_adds_shared_and_implied_rights(self):
		covered = share_coverage({"read": OWNER, "export": ALL}, ["read", "write"])
		self.assertEqual(covered, {"read": ALL, "write": ALL, "print": ALL, "email": ALL, "export": ALL})

	def test_candidates_covering_everything_rank_first(self):
		ranked = rank_candidates(
			[
				{"role": "Narrow", "size": 1, "missing": ["write"]},
				{"role": "Wide", "size": 9, "missing": []},
			]
		)
		self.assertEqual([candidate["role"] for candidate in ranked], ["Wide", "Narrow"])

	def test_merge_granting_prefers_full_scope(self):
		merged = merge_granting([{"A": OWNER, "B": ALL}, {"A": ALL, "C": OWNER}])
		self.assertEqual(merged, {"A": ALL, "B": ALL, "C": OWNER})


class TestRoleRight(unittest.TestCase):
	rows = (
		{"role": "A", "permlevel": 0, "if_owner": False, "rights": frozenset({"read", "write"})},
		{"role": "A", "permlevel": 0, "if_owner": True, "rights": frozenset({"delete"})},
		{"role": "A", "permlevel": 1, "if_owner": False, "rights": frozenset({"read", "write"})},
		{"role": "B", "permlevel": 0, "if_owner": False, "rights": frozenset({"read"})},
	)

	def test_unavailable_outside_doctype_requests_and_on_protected_doctypes(self):
		self.assertEqual(role_right_unavailable(False, None, None), "not_doctype")
		self.assertEqual(role_right_unavailable(True, "User", "Core"), "protected_doctype")
		self.assertEqual(role_right_unavailable(True, "Server Script", "Core"), "protected_doctype")
		self.assertEqual(role_right_unavailable(True, "Client Script", "Custom"), "protected_doctype")
		self.assertIsNone(role_right_unavailable(True, "Purchase Invoice", "Accounts"))

	def test_refusal_blocks_privileged_roles_and_own_roles_of_non_system_managers(self):
		self.assertEqual(role_right_refusal("All", ["Access Manager"]), "never_granted")
		self.assertEqual(role_right_refusal("System Manager", ["System Manager"]), "never_granted")
		self.assertEqual(role_right_refusal("Sales User", ["Access Manager", "Sales User"]), "own_role")
		self.assertIsNone(role_right_refusal("Sales User", ["System Manager", "Sales User"]))
		self.assertIsNone(role_right_refusal("Sales User", ["Access Manager"]))

	def test_held_rights_count_only_level_zero_rows_for_all_documents(self):
		self.assertEqual(held_rights(self.rows, "A"), {"read", "write"})
		self.assertEqual(held_rights(self.rows, "C"), frozenset())

	def test_rights_to_add_skip_what_the_role_already_gives(self):
		self.assertEqual(
			rights_to_add(self.rows, "A", ["read", "delete", "print", "delete"]), ["delete", "print"]
		)
		self.assertEqual(rights_to_add(self.rows, "A", ["read", "write"]), [])

	def test_rows_with_rights_extend_coverage_for_the_role(self):
		after = rows_with_rights(self.rows, "B", ["write", "print"])
		self.assertEqual(
			coverage(after, ["B"], ["read", "write", "print", "delete"]),
			{"read": ALL, "write": ALL, "print": ALL},
		)

	def test_same_rows_ignore_order_and_empty_rows(self):
		empty = {"role": "C", "permlevel": 0, "if_owner": False, "rights": frozenset()}
		self.assertTrue(same_rows(self.rows, (*reversed(self.rows), empty)))
		self.assertFalse(same_rows(self.rows, rows_with_rights(self.rows, "B", ["write"])))


class TestRevoke(unittest.TestCase):
	def test_role_grant_log_records_how_the_role_was_added(self):
		self.assertEqual(role_grant_log("R", [], None), {"role": "R", "profile": None, "unlinked": []})
		self.assertEqual(
			role_grant_log("R", ["P", "Q"], "profile:Q"), {"role": "R", "profile": "Q", "unlinked": []}
		)
		self.assertEqual(
			role_grant_log("R", ["P", "Q"], "unlink"), {"role": "R", "profile": None, "unlinked": ["P", "Q"]}
		)

	def test_revoking_a_role_drops_only_that_role(self):
		self.assertEqual(roles_after_revoke("Role", {"role": "B"}, ["A", "B", "C"]), ["A", "C"])

	def test_changes_to_role_profiles_cannot_be_revoked(self):
		self.assertFalse(is_revocable("Role Profile", {"profile": "P"}))
		self.assertFalse(is_revocable("Role", {"role": "R", "profile": "P", "unlinked": []}))

	def test_direct_grants_can_be_revoked(self):
		self.assertTrue(is_revocable("Role", {"role": "R", "profile": None, "unlinked": ["P"]}))
		for resolution in ("Role Right", "Document Share", "User Permission"):
			self.assertTrue(is_revocable(resolution, {"any": 1}))

	def test_nothing_to_revoke_without_a_log(self):
		self.assertFalse(is_revocable("Document Share", None))
		self.assertFalse(is_revocable(None, {"any": 1}))

	def test_other_resolutions_do_not_change_roles(self):
		for resolution in ("Document Share", "User Permission", "Role Right"):
			self.assertIsNone(roles_after_revoke(resolution, {}, ["A"]))
