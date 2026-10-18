import json
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from erpnext.accounts.invoice_payment_route import (
	_can_confirm,
	_payment_progress,
	confirm_invoice_payment_requests,
	validate_pending_requests,
)
from erpnext.accounts.payment_request_approval import (
	SNAPSHOT,
	THRESHOLD,
	TREASURY,
	VOTES,
	check_final_decision,
	prepare_approval,
	record_vote,
	votes,
)
from erpnext.buying.procurement_final_approval import ADMINISTRATOR_OVERRIDE


class ApprovalDoc(frappe._dict):
	def set(self, key, value):
		self[key] = value

	def get_doc_before_save(self):
		return self.get("before")


def request(state="Чернетка", **values):
	return ApprovalDoc(
		doctype="Payment Request",
		name="REQ-A",
		owner="buyer@example.com",
		workflow_state=state,
		reference_doctype="Purchase Invoice",
		reference_name="INV-A",
		payment_request_type="Outward",
		party_type="Supplier",
		company="Company A",
		party="Supplier A",
		grand_total=20000,
		currency="UAH",
		**values,
	)


class TestInvoicePaymentRoute(TestCase):
	@patch("erpnext.accounts.payment_procurement_route.set_procurement_approval_route")
	@patch(
		"erpnext.accounts.payment_request_approval.get_configured_final_approvers",
		return_value=["ceo1", "ceo2", "ceo3"],
	)
	def test_entering_final_approval_captures_all_active_ceos(self, configured, set_route):
		before = request("Перевірка підрозділу", custom_payment_ceo_threshold=15000)
		doc = request("Фінальне погодження", before=before)
		prepare_approval(doc)
		self.assertEqual(json.loads(doc.get(SNAPSHOT)), ["ceo1", "ceo2", "ceo3"])
		self.assertEqual(json.loads(doc.get(VOTES)), [])
		self.assertEqual(doc.get(THRESHOLD), 15000)

	@patch("erpnext.accounts.payment_procurement_route.set_procurement_approval_route")
	@patch("erpnext.accounts.payment_request_approval.get_configured_final_approvers")
	def test_settings_changes_and_client_votes_do_not_change_the_snapshot(self, configured, set_route):
		before = request(
			"Фінальне погодження",
			custom_payment_ceo_approvers='["ceo1","ceo2"]',
			custom_payment_ceo_votes='["ceo1"]',
			custom_payment_ceo_threshold=15000,
		)
		doc = request(
			"Фінальне погодження",
			before=before,
			custom_payment_ceo_approvers='["intruder"]',
			custom_payment_ceo_votes='["ceo1","ceo2"]',
		)
		prepare_approval(doc)
		self.assertEqual(doc.get(SNAPSHOT), before.get(SNAPSHOT))
		self.assertEqual(doc.get(VOTES), before.get(VOTES))
		configured.assert_not_called()

	@patch("erpnext.accounts.payment_procurement_route.set_procurement_approval_route")
	def test_cannot_advance_with_missing_ceo_votes(self, set_route):
		before = request(
			"Фінальне погодження",
			custom_payment_ceo_approvers='["ceo1","ceo2"]',
			custom_payment_ceo_votes='["ceo1"]',
		)
		doc = request(TREASURY, before=before)
		with self.assertRaises(frappe.ValidationError):
			prepare_approval(doc)

	@patch("erpnext.accounts.payment_procurement_route.set_procurement_approval_route")
	def test_source_cannot_be_changed_to_bypass_approval(self, set_route):
		before = request("Фінальне погодження")
		doc = request(TREASURY, before=before)
		doc.reference_name = "OTHER-INVOICE"
		with self.assertRaises(frappe.ValidationError):
			prepare_approval(doc)

	@patch("erpnext.accounts.invoice_payment_route._source_snapshot", return_value=None)
	def test_standalone_invoice_cannot_auto_submit_pending_request(self, snapshot):
		self.assertFalse(_can_confirm(frappe._dict(), [frappe._dict(workflow_state=TREASURY)]))

	@patch("erpnext.accounts.invoice_payment_route._source_snapshot", return_value={"source": "CPO-A"})
	def test_upstream_order_does_not_allow_skipping_pending_department_review(self, snapshot):
		self.assertFalse(_can_confirm(frappe._dict(), [frappe._dict(workflow_state="Перевірка підрозділу")]))

	@patch("erpnext.accounts.invoice_payment_route.frappe.get_all")
	def test_payment_step_requires_full_payment_and_all_instructions(self, get_all):
		entries = [
			frappe._dict(owner="treasurer", custom_fiscal_receipt="/private/files/a.pdf"),
			frappe._dict(owner="treasurer", custom_fiscal_receipt=""),
		]
		get_all.side_effect = [["PAY-A", "PAY-B"], entries]
		with patch("erpnext.accounts.invoice_payment_route._user", return_value={}):
			step = _payment_progress(
				frappe._dict(doctype="Purchase Request", status="Paid"),
				frappe._dict(name="INV-A", outstanding_amount=0),
			)
		self.assertFalse(step["completed"])

	@patch(
		"erpnext.accounts.invoice_payment_route._pending_requests", return_value=[frappe._dict(name="REQ-A")]
	)
	@patch("erpnext.accounts.invoice_payment_route.frappe.get_doc")
	def test_manual_payment_submission_cannot_bypass_pending_request(self, get_doc, pending):
		doc = frappe._dict(
			payment_type="Pay",
			party_type="Supplier",
			references=[
				frappe._dict(
					reference_doctype="Purchase Invoice", reference_name="INV-A", allocated_amount=100
				)
			],
		)
		with self.assertRaises(frappe.ValidationError):
			validate_pending_requests(doc)

	@patch("frappe.model.workflow.apply_workflow")
	@patch("erpnext.accounts.invoice_payment_route._can_confirm", return_value=True)
	@patch(
		"erpnext.accounts.invoice_payment_route._pending_requests",
		return_value=[frappe._dict(name="REQ-A", workflow_state=TREASURY)],
	)
	@patch("erpnext.accounts.invoice_payment_route.frappe.get_doc")
	def test_confirmation_uses_standard_workflow_and_does_not_create_payment(
		self, get_doc, pending, can_confirm, apply
	):
		invoice = MagicMock(docstatus=1, outstanding_amount=100, name="INV-A")
		invoice.name = "INV-A"
		req = MagicMock(docstatus=0, workflow_state=TREASURY, reference_name="INV-A")
		get_doc.side_effect = [invoice, req]
		self.assertEqual(confirm_invoice_payment_requests("INV-A", ["REQ-A"]), ["REQ-A"])
		req.check_permission.assert_called_once_with("submit")
		apply.assert_called_once_with(req.as_dict(), "Погодити")

	@patch(
		"erpnext.accounts.payment_request_approval.frappe.get_roles",
		return_value=["Payments: Фінальний погоджувач"],
	)
	@patch("erpnext.accounts.payment_request_approval.frappe.get_doc")
	def test_unconfigured_ceo_cannot_vote(self, get_doc, roles):
		doc = request(
			"Фінальне погодження",
			custom_payment_ceo_approvers='["another-user"]',
			custom_payment_ceo_votes="[]",
		)
		doc.check_permission = MagicMock()
		get_doc.return_value = doc
		with (
			patch("erpnext.accounts.payment_request_approval.frappe.session", frappe._dict(user="outsider")),
			self.assertRaises(frappe.PermissionError),
		):
			record_vote(doc)

	def test_administrator_completes_ceo_step_and_keeps_actual_votes(self):
		for required in ([], ["ceo1"], ["ceo1", "ceo2", "ceo3", "ceo4"], ["Administrator", "ceo1", "ceo2"]):
			with self.subTest(required=required):
				doc = request(
					"Фінальне погодження",
					**{
						SNAPSHOT: json.dumps(required),
						VOTES: '["Administrator"]' if "Administrator" in required else "[]",
					},
				)
				doc.check_permission = MagicMock()
				doc.add_comment = MagicMock()
				doc.reload = MagicMock()
				with (
					patch(
						"erpnext.accounts.payment_request_approval.frappe.session",
						frappe._dict(user="Administrator"),
					),
					patch("erpnext.accounts.payment_request_approval.frappe.get_doc", return_value=doc),
					patch("erpnext.accounts.payment_request_approval.frappe.get_roles", return_value=[]),
					patch("erpnext.accounts.payment_request_approval.frappe.db.set_value"),
					patch("erpnext.accounts.payment_workflow_automation.sync_payment_request_assignment"),
					patch("erpnext.accounts.payment_procurement_route.set_procurement_approval_route"),
				):
					check_final_decision(doc)
					approved, complete = record_vote(doc)
					self.assertTrue(complete)
					self.assertIs(approved, doc)
					self.assertEqual(json.loads(doc.get(SNAPSHOT)), required)
					self.assertEqual(votes(doc), ["Administrator"])
					doc.add_comment.assert_called_once()
					next_doc = request(TREASURY, before=doc)
					prepare_approval(next_doc)
					self.assertEqual(votes(next_doc), ["Administrator"])

	@patch("erpnext.accounts.payment_procurement_route.set_procurement_approval_route")
	def test_old_ordinary_administrator_vote_does_not_override_other_ceos(self, _route):
		before = request(
			"Фінальне погодження", **{SNAPSHOT: '["Administrator", "ceo2"]', VOTES: '["Administrator"]'}
		)
		with self.assertRaises(frappe.ValidationError):
			prepare_approval(request(TREASURY, before=before))

	@patch("erpnext.accounts.payment_procurement_route.set_procurement_approval_route")
	def test_client_cannot_forge_administrator_ceo_vote(self, _route):
		before = request("Фінальне погодження", **{SNAPSHOT: '["ceo1", "ceo2"]', VOTES: "[]"})
		doc = request(
			TREASURY, before=before, **{VOTES: json.dumps(["Administrator", ADMINISTRATOR_OVERRIDE])}
		)
		with self.assertRaises(frappe.ValidationError):
			prepare_approval(doc)

	def test_final_workflow_action_is_available_to_administrator_without_membership(self):
		from erpnext.accounts.payment_workflow import WORKFLOW_TRANSITIONS

		transition = next(
			row
			for row in WORKFLOW_TRANSITIONS
			if row["state"] == "Фінальне погодження" and row["action"] == "Погодити"
		)
		doc = request(
			"Фінальне погодження", custom_payment_dynamic_approval=1, **{SNAPSHOT: '["ceo1", "ceo2", "ceo3"]'}
		)
		for user, allowed in (("Administrator", True), ("ceo1", True), ("outsider", False)):
			with self.subTest(user=user):
				result = frappe.safe_eval(
					transition["condition"],
					{"frappe": frappe._dict(session=frappe._dict(user=user))},
					{"doc": doc},
				)
				self.assertEqual(result, allowed)

	@patch("erpnext.accounts.payment_procurement_route.set_procurement_approval_route")
	@patch("erpnext.accounts.payment_request_approval.get_approval_threshold", return_value=15000)
	def test_administrator_vote_is_reset_for_a_new_payment_approval_cycle(self, _threshold, _route):
		before = request("Потребує доопрацювання", **{SNAPSHOT: '["ceo1"]', VOTES: '["Administrator"]'})
		doc = request("Перевірка підрозділу", before=before)
		prepare_approval(doc)
		self.assertEqual(json.loads(doc.get(VOTES)), [])
		self.assertIsNone(doc.get(SNAPSHOT))
