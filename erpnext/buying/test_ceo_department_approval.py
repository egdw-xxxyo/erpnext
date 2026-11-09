import json
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from erpnext.accounts.payment_request_approval import (
	SNAPSHOT,
	TREASURY,
	VOTES,
	prepare_approval,
	votes,
)
from erpnext.accounts.payment_workflow_reason import apply_workflow as apply_payment
from erpnext.buying import procurement_final_approval as approval
from erpnext.buying.doctype.recurring_purchase.recurring_purchase import apply_workflow as apply_recurring
from erpnext.buying.procurement_workflow import (
	APPROVE_ALL_CEOS_ACTION,
	DEPARTMENT_HEAD_ROLE,
	WORKFLOW_TRANSITIONS,
)
from erpnext.buying.procurement_workflow_reason import apply_workflow as apply_purchase


class ApprovalDoc(frappe._dict):
	def set(self, key, value):
		self[key] = value

	def get_doc_before_save(self):
		return self.get("before")

	def is_new(self):
		return False


ROUTES = (
	("Consolidated Purchase Order", apply_purchase),
	("Recurring Purchase", apply_recurring),
	("Payment Request", apply_payment),
)


def make_doc(doctype, required=None):
	is_request = doctype == "Payment Request"
	doc = ApprovalDoc(
		doctype=doctype,
		name="TEST-CEO-OVERRIDE",
		docstatus=0,
		workflow_state=approval.FINAL_APPROVAL_STATE,
		grand_total=20000,
		ceo_approval_threshold=15000,
		owner="buyer",
		reference_doctype="Purchase Invoice",
		reference_name="INV-A",
		payment_request_type="Outward",
		party_type="Supplier",
	)
	doc.set(SNAPSHOT if is_request else approval.SNAPSHOT_FIELD, json.dumps(required or []))
	doc.set(VOTES if is_request else approval.VOTES_FIELD, json.dumps([required[0]] if required else []))
	doc.check_permission = MagicMock()
	doc.add_comment = MagicMock()
	return doc


class TestDepartmentHeadCEOApproval(TestCase):
	def setUp(self):
		self.enterContext(patch.object(frappe, "session", frappe._dict(user="head")))
		self.enterContext(patch.object(frappe, "get_roles", return_value=[DEPARTMENT_HEAD_ROLE]))
		self.enterContext(patch.object(frappe, "get_cached_value", return_value="Department <Head>"))

	def test_all_routes_accept_one_head_decision_for_any_number_of_ceos(self):
		for doctype, apply in ROUTES:
			for required in ([], ["ceo1"], ["ceo1", "ceo2", "ceo3", "ceo4"]):
				with self.subTest(doctype=doctype, required=required):
					doc = make_doc(doctype, required)
					is_request = doctype == "Payment Request"
					field = VOTES if is_request else approval.VOTES_FIELD
					with (
						patch.object(frappe, "get_doc", return_value=doc),
						patch.object(
							frappe.db, "set_value", side_effect=lambda dt, name, values: doc.update(values)
						),
						patch("frappe.model.workflow.apply_workflow", return_value=doc) as core,
					):
						result = apply(
							{
								"doctype": doctype,
								"name": doc.name,
								"workflow_action_reason": "Budget <approved>",
								"custom_workflow_action_reason": "Budget <approved>",
							},
							APPROVE_ALL_CEOS_ACTION,
						)
					self.assertIs(result, doc)
					core.assert_called_once_with(doc, APPROVE_ALL_CEOS_ACTION)
					self.assertEqual(approval.get_department_head_approval(doc, field), "head")
					self.assertEqual(
						json.loads(doc.get(SNAPSHOT if is_request else approval.SNAPSHOT_FIELD)), required
					)
					actual = votes(doc) if is_request else approval.get_document_approved_users(doc)
					self.assertEqual(actual, [*required[:1], "head"])
					comment = doc.add_comment.call_args.kwargs["text"]
					self.assertIn("Budget &lt;approved&gt;", comment)
					self.assertIn("Department &lt;Head&gt;", comment)

	def test_reason_and_role_are_required_before_any_votes_are_written(self):
		for doctype, apply in ROUTES:
			for reason, roles in (
				("", [DEPARTMENT_HEAD_ROLE]),
				("  ", [DEPARTMENT_HEAD_ROLE]),
				("x" * 2001, [DEPARTMENT_HEAD_ROLE]),
				("Explanation", [approval.FINAL_APPROVER_ROLE]),
			):
				with self.subTest(doctype=doctype, reason=reason[:12], roles=roles):
					doc = make_doc(doctype, ["ceo1", "ceo2"])
					with (
						patch.object(frappe, "get_doc", return_value=doc),
						patch.object(frappe, "get_roles", return_value=roles),
						patch.object(frappe.db, "set_value") as write,
						patch("frappe.model.workflow.apply_workflow") as core,
						self.assertRaises((frappe.ValidationError, frappe.PermissionError)),
					):
						apply(
							{
								"doctype": doctype,
								"name": doc.name,
								"workflow_action_reason": reason,
								"custom_workflow_action_reason": reason,
							},
							APPROVE_ALL_CEOS_ACTION,
						)
					write.assert_not_called()
					core.assert_not_called()

	def test_head_action_cannot_skip_department_review_or_repeat_completed_approval(self):
		for state in ("Чернетка", "Перевірка підрозділу", "Погоджено", TREASURY):
			with self.subTest(state=state):
				doc = make_doc("Consolidated Purchase Order")
				doc.workflow_state = state
				with (
					patch.object(frappe, "get_doc", return_value=doc),
					patch.object(frappe.db, "set_value") as write,
					self.assertRaises(frappe.ValidationError),
				):
					approval.apply_department_head_approval(doc, "Explanation", MagicMock())
				write.assert_not_called()

	def test_head_decision_passes_validation_and_cannot_be_forged_in_payload(self):
		for doctype, _apply in ROUTES:
			with self.subTest(doctype=doctype):
				is_request = doctype == "Payment Request"
				field = VOTES if is_request else approval.VOTES_FIELD
				before = make_doc(doctype, ["ceo1", "ceo2", "ceo3"])
				decision = json.dumps(["ceo1", "head", approval.DEPARTMENT_HEAD_OVERRIDE_PREFIX + "head"])
				for persisted in (False, True):
					before.set(field, decision if persisted else '["ceo1"]')
					doc = make_doc(doctype)
					doc.before = before
					doc.workflow_state = TREASURY if is_request else "Погоджено"
					doc.set(field, decision)
					with patch("erpnext.accounts.payment_procurement_route.set_procurement_approval_route"):
						if persisted:
							(prepare_approval if is_request else approval.capture_final_approvers)(doc)
							self.assertEqual(approval.get_department_head_approval(doc, field), "head")
						else:
							with self.assertRaises(frappe.ValidationError):
								(prepare_approval if is_request else approval.capture_final_approvers)(doc)

	def test_new_cycle_resets_head_decision_including_standard_payment_route(self):
		for doctype, _apply in ROUTES:
			is_request = doctype == "Payment Request"
			standard_payment_cases = (False, True) if is_request else (False,)
			for standard_payment in standard_payment_cases:
				with self.subTest(doctype=doctype, standard_payment=standard_payment):
					field = VOTES if is_request else approval.VOTES_FIELD
					before = make_doc(doctype, ["ceo1"])
					before.workflow_state = "Потребує доопрацювання"
					before.set(field, json.dumps(["head", approval.DEPARTMENT_HEAD_OVERRIDE_PREFIX + "head"]))
					doc = make_doc(doctype)
					doc.before = before
					doc.workflow_state = (
						"Перевірка підрозділу" if is_request else approval.FINAL_APPROVAL_STATE
					)
					if standard_payment:
						doc.reference_doctype = before.reference_doctype = "Expense Claim"
					with (
						patch("erpnext.accounts.payment_procurement_route.set_procurement_approval_route"),
						patch.object(approval, "get_configured_final_approvers", return_value=["ceo2"]),
						patch(
							"erpnext.accounts.payment_request_approval.get_approval_threshold",
							return_value=15000,
						),
					):
						(prepare_approval if is_request else approval.capture_final_approvers)(doc)
					self.assertIsNone(approval.get_department_head_approval(doc, field))
					self.assertEqual(json.loads(doc.get(field)), [])

	def test_head_cannot_bypass_reason_with_direct_standard_payment_state_change(self):
		before = make_doc("Payment Request", ["ceo1"])
		before.reference_doctype = "Expense Claim"
		doc = make_doc("Payment Request")
		doc.reference_doctype = "Expense Claim"
		doc.workflow_state = TREASURY
		doc.before = before
		doc.set(VOTES, json.dumps(["head", approval.DEPARTMENT_HEAD_OVERRIDE_PREFIX + "head"]))
		with (
			patch("erpnext.accounts.payment_procurement_route.set_procurement_approval_route"),
			self.assertRaises(frappe.ValidationError),
		):
			prepare_approval(doc)

	def test_all_workflow_definitions_expose_head_action_only_at_ceo_stage(self):
		from erpnext.accounts.payment_workflow import WORKFLOW_TRANSITIONS as payment_transitions

		for transitions, target in ((WORKFLOW_TRANSITIONS, "Погоджено"), (payment_transitions, TREASURY)):
			rows = [row for row in transitions if row["action"] == APPROVE_ALL_CEOS_ACTION]
			self.assertEqual(len(rows), 1)
			self.assertEqual(rows[0]["state"], approval.FINAL_APPROVAL_STATE)
			self.assertEqual(rows[0]["next_state"], target)
			self.assertEqual(rows[0]["allowed"], DEPARTMENT_HEAD_ROLE)
