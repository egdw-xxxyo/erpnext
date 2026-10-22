"""Automatic department approval must come from the prepaid request's actual author."""

from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from erpnext.buying.procurement_workflow_reason import _apply_creator_department_approval


class TestPrepaidDepartmentApproval(TestCase):
	def setUp(self):
		self.doc = frappe._dict(
			doctype="Consolidated Purchase Order",
			name="CPO-TEST",
			company="Company A",
			owner="buyer@example.invalid",
			request_initiator_user="manually-selected@example.invalid",
			initiator_user="buyer@example.invalid",
			workflow_state="Перевірка підрозділу",
			items_already_purchased=1,
			items=[frappe._dict(material_request="MR-TEST")],
		)
		self.request = frappe._dict(
			name="MR-TEST",
			owner="head@example.invalid",
			company="Company A",
			docstatus=1,
			material_request_type="Purchase",
			custom_items_already_purchased=1,
		)
		self.result = frappe._dict(workflow_state="Фінальне погодження", add_comment=MagicMock())
		self.core = MagicMock(return_value=self.result)
		self.enterContext(patch("frappe.set_user"))
		self.enterContext(patch("frappe.get_cached_value", return_value="Head"))
		self.enterContext(patch("frappe.db.get_value", side_effect=self.get_value))
		self.write = self.enterContext(patch("frappe.db.set_value"))
		self.roles = self.enterContext(
			patch(
				"frappe.db.exists",
				side_effect=lambda dt, filters: filters.get("parent") == "head@example.invalid",
			)
		)
		self.ceos = self.enterContext(
			patch("erpnext.buying.procurement_final_approval.get_configured_final_approvers", return_value=[])
		)
		self.enterContext(patch("erpnext.buying.procurement_workflow_reason._", side_effect=lambda s: s))

	def get_value(self, doctype, filters, *args, **kwargs):
		if doctype == "Material Request":
			return self.request if all(self.request.get(k) == value for k, value in filters.items()) else None
		return "WORKFLOW-ACTION"

	def assert_manual(self):
		self.assertIs(_apply_creator_department_approval(self.doc, self.core), self.doc)
		self.core.assert_not_called()

	def test_prepaid_request_author_approves_without_assignment_or_matching_initiator(self):
		self.assertIs(_apply_creator_department_approval(self.doc, self.core), self.result)
		self.core.assert_called_once_with(self.doc, "Погодити")
		self.assertEqual(self.result.workflow_state, "Фінальне погодження")
		self.assertEqual(self.write.call_args.args[2]["completed_by"], "head@example.invalid")
		self.assertEqual(self.result.add_comment.call_args.kwargs["comment_email"], "head@example.invalid")
		self.assertIn("MR-TEST", self.result.add_comment.call_args.kwargs["text"])

	def test_selecting_a_head_in_direct_cpo_does_not_approve(self):
		self.doc.owner = self.doc.request_initiator_user = self.doc.initiator_user = "head@example.invalid"
		self.doc.items = [frappe._dict(material_request=None)]
		self.doc.material_request = "MR-TEST"  # A forged parent reference is insufficient.
		self.assert_manual()

	def test_request_initiator_cannot_replace_actual_author(self):
		self.request.owner = "ordinary@example.invalid"
		self.doc.request_initiator_user = "head@example.invalid"
		self.assert_manual()

	def test_unpaid_request_is_manual_even_if_cpo_marked_prepaid(self):
		self.request.custom_items_already_purchased = 0
		self.assert_manual()

	def test_cpo_must_also_be_marked_prepaid(self):
		self.doc.items_already_purchased = 0
		self.assert_manual()

	def test_request_must_be_submitted_purchase_for_same_company(self):
		for field, value in (
			("docstatus", 0),
			("docstatus", 2),
			("material_request_type", "Material Transfer"),
			("company", "Company B"),
		):
			with self.subTest(field=field, value=value), patch.dict(self.request, {field: value}):
				self.assert_manual()

	def test_mixed_or_unlinked_items_require_manual_review(self):
		for source in (None, "ANOTHER-MR"):
			with self.subTest(source=source):
				self.doc.items = [
					frappe._dict(material_request="MR-TEST"),
					frappe._dict(material_request=source),
				]
				self.assert_manual()

	def test_only_department_stage_can_be_advanced(self):
		self.doc.workflow_state = "Фінальне погодження"
		self.assert_manual()

	def test_head_who_is_also_ceo_only_gets_department_approval(self):
		self.ceos.return_value = ["head@example.invalid"]
		_apply_creator_department_approval(self.doc, self.core)
		self.core.assert_called_once_with(self.doc, "Погодити")
		self.assertEqual(self.result.workflow_state, "Фінальне погодження")

	def test_recurring_purchase_creator_policy_is_preserved(self):
		self.doc.doctype = "Recurring Purchase"
		self.doc.owner = "head@example.invalid"
		_apply_creator_department_approval(self.doc, self.core)
		self.core.assert_called_once_with(self.doc, "Погодити")
		self.assertNotIn("MR-TEST", self.result.add_comment.call_args.kwargs["text"])

	def test_recurring_ceo_creator_still_needs_department_review(self):
		self.doc.doctype = "Recurring Purchase"
		self.doc.owner = "head@example.invalid"
		self.ceos.return_value = ["head@example.invalid"]
		self.assert_manual()
