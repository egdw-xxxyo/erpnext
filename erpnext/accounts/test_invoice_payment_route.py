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
	prepare_approval,
	record_vote,
)


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
		with self.assertRaises(frappe.PermissionError):
			record_vote(doc)
