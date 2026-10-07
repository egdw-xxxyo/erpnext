import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.accounts.payment_workflow_automation import ALL_ASSIGNMENT_DAYS as PAYMENT_ASSIGNMENT_DAYS
from erpnext.accounts.payment_workflow_automation import (
	_ensure_assignment_rule as ensure_payment_assignment_rule,
)
from erpnext.buying import procurement_final_approval as approval
from erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order import (
	ConsolidatedPurchaseOrder,
)
from erpnext.buying.procurement_automation import sync_procurement_stage_assignment
from erpnext.buying.procurement_links import _visible_documents, get_procurement_links
from erpnext.buying.procurement_workflow import (
	ALL_ASSIGNMENT_DAYS,
	PROCUREMENT_ASSIGNMENT_RULES,
	_ensure_procurement_assignment_rules,
)
from erpnext.setup.procurement_workflow_setup import _save


class TestProcurementFinalApproval(IntegrationTestCase):
	def doc(self, **values):
		doc = ConsolidatedPurchaseOrder(
			{
				"doctype": "Consolidated Purchase Order",
				"name": "CPO-TEST-SNAPSHOT",
				"workflow_state": approval.FINAL_APPROVAL_STATE,
				"grand_total": 20000,
				"ceo_approval_threshold": 15000,
				"owner": "buyer@example.invalid",
				**values,
			}
		)
		return doc

	@patch.object(approval, "get_configured_final_approvers", return_value=["ceo1", "ceo2", "ceo3"])
	def test_snapshot_on_entry_and_settings_change_does_not_change_it(self, configured):
		doc = self.doc()
		doc._doc_before_save = self.doc(workflow_state="Перевірка підрозділу")
		approval.capture_final_approvers(doc)
		self.assertEqual(approval.get_document_final_approvers(doc), ["ceo1", "ceo2", "ceo3"])
		configured.return_value = ["ceo4"]
		previous = self.doc(
			**{
				approval.SNAPSHOT_FIELD: doc.get(approval.SNAPSHOT_FIELD),
				approval.VOTES_FIELD: '["ceo1"]',
				"final_approval_count": 1,
			}
		)
		doc._doc_before_save = previous
		doc.set(approval.SNAPSHOT_FIELD, '["ceo4"]')
		doc.set(approval.VOTES_FIELD, '["ceo4"]')
		approval.capture_final_approvers(doc)
		self.assertEqual(approval.get_document_final_approvers(doc), ["ceo1", "ceo2", "ceo3"])
		self.assertEqual(approval.get_document_approved_users(doc), ["ceo1"])

	@patch.object(approval, "get_configured_final_approvers", return_value=["ceo3"])
	def test_new_approval_cycle_uses_current_settings(self, _configured):
		doc = self.doc(
			**{approval.SNAPSHOT_FIELD: '["ceo1", "ceo2"]', approval.VOTES_FIELD: '["ceo1", "ceo2"]'}
		)
		doc._doc_before_save = self.doc(workflow_state="Потребує доопрацювання")
		approval.capture_final_approvers(doc)
		self.assertEqual(approval.get_document_final_approvers(doc), ["ceo3"])
		self.assertEqual(approval.get_document_approved_users(doc), [])
		self.assertEqual(doc.final_approval_count, 0)

	def test_cannot_advance_without_all_frozen_votes(self):
		doc = self.doc(workflow_state="Погоджено")
		doc._doc_before_save = self.doc(
			**{approval.SNAPSHOT_FIELD: '["ceo1", "ceo2", "ceo3"]', approval.VOTES_FIELD: '["ceo1", "ceo2"]'}
		)
		with self.assertRaises(frappe.ValidationError):
			approval.capture_final_approvers(doc)
		doc._doc_before_save.set(approval.VOTES_FIELD, '["ceo1", "ceo2", "ceo3"]')
		approval.capture_final_approvers(doc)

	@patch.object(approval, "_is_valid_approver", return_value=True)
	@patch.object(approval.frappe, "get_single")
	def test_active_list_can_have_one_or_more_than_two_users(self, get_single, _valid):
		settings = frappe._dict(
			custom_final_approvers_initialized=1,
			custom_final_approvers=[
				frappe._dict(approver="ceo1", active=1),
				frappe._dict(approver="ceo2", active=0),
				frappe._dict(approver="ceo3", active=1),
				frappe._dict(approver="ceo4", active=1),
			],
		)
		get_single.return_value = settings
		self.assertEqual(approval.get_configured_final_approvers(), ["ceo1", "ceo3", "ceo4"])
		settings.custom_final_approvers = settings.custom_final_approvers[:1]
		self.assertEqual(approval.get_configured_final_approvers(), ["ceo1"])
		settings.custom_final_approvers = []
		settings.custom_final_approver_1 = "legacy"
		with self.assertRaises(frappe.ValidationError):
			approval.get_configured_final_approvers()

	@patch.object(approval.frappe.db, "set_value")
	@patch.object(approval, "_close_user_assignment")
	def test_third_vote_preserves_first_two(self, _close, set_value):
		doc = self.doc(
			**{approval.SNAPSHOT_FIELD: '["ceo1", "ceo2", "ceo3"]', approval.VOTES_FIELD: '["ceo1", "ceo2"]'}
		)
		self.assertEqual(approval._write_vote(doc, "ceo3", True), 3)
		self.assertEqual(
			json.loads(set_value.call_args.args[2][approval.VOTES_FIELD]), ["ceo1", "ceo2", "ceo3"]
		)

	@patch.object(approval.frappe.db, "set_value")
	def test_backfill_preserves_old_votes_and_is_idempotent(self, set_value):
		doc = self.doc(
			final_approval_count=2,
			final_approved_by_1="ceo1",
			final_approved_by_2="ceo2",
			workflow_state="Погоджено",
		)
		with (
			patch.object(
				approval.frappe,
				"get_single",
				return_value=frappe._dict(custom_final_approver_1="ceo1", custom_final_approver_2="ceo2"),
			),
			patch.object(approval.frappe, "get_all", return_value=["legacy-doc"]),
			patch.object(approval.frappe, "get_doc", return_value=doc),
		):
			approval.sync_existing_final_approval_documents()
			values = set_value.call_args.args[2]
			self.assertEqual(json.loads(values[approval.SNAPSHOT_FIELD]), ["ceo1", "ceo2"])
			self.assertEqual(values["final_approval_count"], 2)
			for field, value in values.items():
				doc.set(field, value)
			set_value.reset_mock()
			approval.sync_existing_final_approval_documents()
			set_value.assert_not_called()

	def test_only_snapshotted_user_can_vote_and_duplicate_is_rejected(self):
		doc = self.doc(
			**{approval.SNAPSHOT_FIELD: '["ceo1", "ceo2", "ceo3"]', approval.VOTES_FIELD: '["ceo1"]'}
		)
		with (
			patch.object(approval.frappe, "get_doc", return_value=doc),
			patch.object(doc, "check_permission"),
			patch.object(approval.frappe, "session", frappe._dict(user="ceo4")),
		):
			with self.assertRaises(frappe.ValidationError):
				approval.record_final_approval(doc)
		with (
			patch.object(approval.frappe, "get_doc", return_value=doc),
			patch.object(doc, "check_permission"),
			patch.object(approval.frappe, "session", frappe._dict(user="ceo1")),
		):
			with self.assertRaises(frappe.ValidationError):
				approval.record_final_approval(doc)

	def test_workflow_waits_for_three_votes_then_advances(self):
		from erpnext.buying.procurement_workflow_reason import apply_workflow

		doc = self.doc(**{approval.SNAPSHOT_FIELD: '["ceo1", "ceo2", "ceo3"]'})
		with (
			patch.object(approval.frappe, "get_doc", return_value=doc),
			patch.object(approval, "record_final_approval", return_value=2) as vote,
			patch("frappe.model.workflow.apply_workflow") as core,
			patch.object(approval, "close_final_approval_assignments"),
			patch.object(approval.frappe, "msgprint"),
		):
			apply_workflow({"doctype": doc.doctype, "name": doc.name}, "Погодити")
			core.assert_not_called()
			vote.return_value = 3
			apply_workflow({"doctype": doc.doctype, "name": doc.name}, "Погодити")
			core.assert_called_once()

	def test_repeated_settings_migration_does_not_save_or_insert(self):
		settings = MagicMock()
		settings.get.return_value = 1
		with patch.object(approval.frappe, "get_single", return_value=settings):
			approval.migrate_final_approver_settings()
		settings.update_single.assert_not_called()
		settings.save.assert_not_called()
		settings.append.assert_not_called()

	@patch("erpnext.setup.procurement_workflow_setup.frappe.get_doc")
	def test_unchanged_configuration_is_not_saved(self, get_doc):
		doc = MagicMock()
		doc.is_new.return_value = False
		doc.as_dict.return_value = {"name": "rule", "assignment_days": [{"day": "Monday"}]}
		get_doc.return_value.as_dict.return_value = doc.as_dict.return_value
		_save(doc)
		doc.save.assert_not_called()


class TestProcurementLinks(IntegrationTestCase):
	@patch("erpnext.buying.procurement_links.frappe.has_permission", return_value=False)
	@patch("erpnext.buying.procurement_links.frappe.get_list")
	def test_inaccessible_documents_are_not_returned(self, get_list, _permission):
		self.assertEqual(_visible_documents("Payment Entry", {"secret"}), [])
		get_list.assert_not_called()

	@patch("erpnext.buying.procurement_links._visible_documents", side_effect=lambda dt, names: sorted(names))
	@patch("erpnext.buying.procurement_links.frappe.get_all")
	@patch("erpnext.buying.procurement_links.frappe.get_doc")
	def test_traverses_invoices_requests_payments_and_receipts(self, get_doc, get_all, _visible):
		get_doc.return_value = MagicMock(
			material_request="MR1", items=[frappe._dict(material_request="MR1")], name="CPO1"
		)

		def query(dt, **kwargs):
			field = kwargs.get("pluck")
			if dt == "Purchase Order":
				return ["PO1"]
			if dt == "Purchase Invoice":
				return ["PI1"]
			if dt == "Purchase Invoice Item":
				return ["PI2"] if field == "parent" else ["PRC1"]
			if dt == "Purchase Receipt Item":
				return ["PRC2"]
			if dt == "Payment Request":
				return ["PAYREQ1"]
			if dt == "Payment Entry Reference":
				return ["PAY1"]
			return []

		get_all.side_effect = query
		groups = {row["doctype"]: row["documents"] for row in get_procurement_links("CPO1")}
		self.assertEqual(groups["Material Request"], ["MR1"])
		self.assertEqual(groups["Purchase Invoice"], ["PI1", "PI2"])
		self.assertEqual(groups["Payment Request"], ["PAYREQ1"])
		self.assertEqual(groups["Payment Entry"], ["PAY1"])
		self.assertEqual(groups["Purchase Receipt"], ["PRC1", "PRC2"])
		get_doc.return_value.check_permission.assert_called_once_with("read")


class TestProcurementMigrationAssignments(IntegrationTestCase):
	@patch("erpnext.accounts.payment_workflow_automation._save")
	@patch("erpnext.accounts.payment_workflow_automation.frappe.get_doc")
	@patch("erpnext.accounts.payment_workflow_automation.frappe.db.exists", return_value=True)
	def test_unchanged_payment_assignment_rule_is_not_saved(self, _exists, get_doc, save):
		spec = {
			"name": "Payments: test rule",
			"priority": 10,
			"condition": "workflow_state == 'Чернетка'",
			"unassign_condition": "workflow_state != 'Чернетка'",
			"rule": "Round Robin",
			"description": "Test",
		}
		values = {
			"document_type": "Payment Request",
			"priority": 10,
			"disabled": 1,
			"description": "Test",
			"assign_condition": spec["condition"],
			"unassign_condition": spec["unassign_condition"],
			"close_condition": "workflow_state in ('Погоджено', 'Відхилено')",
			"rule": "Round Robin",
			"field": None,
			"due_date_based_on": "custom_requested_payment_date",
			"assignment_days": [frappe._dict(day=day) for day in PAYMENT_ASSIGNMENT_DAYS],
		}
		doc = MagicMock()
		doc.get.side_effect = values.get
		get_doc.return_value = doc

		ensure_payment_assignment_rule(spec)

		save.assert_not_called()

	@patch("erpnext.buying.procurement_workflow._save")
	@patch("erpnext.buying.procurement_workflow.frappe.get_doc")
	@patch("erpnext.buying.procurement_workflow.frappe.db.exists", return_value=True)
	def test_unchanged_assignment_rule_is_not_saved(self, _exists, get_doc, save):
		spec = PROCUREMENT_ASSIGNMENT_RULES[0]
		values = {
			"document_type": spec["document_type"],
			"priority": spec["priority"],
			"disabled": 1,
			"description": spec["description"],
			"assign_condition": spec["condition"],
			"unassign_condition": spec["unassign_condition"],
			"close_condition": spec["close_condition"],
			"rule": spec.get("rule", "Round Robin"),
			"field": spec.get("field"),
			"assignment_days": [frappe._dict(day=day) for day in ALL_ASSIGNMENT_DAYS],
		}
		doc = MagicMock(rule=values["rule"])
		doc.get.side_effect = values.get
		get_doc.return_value = doc

		with patch("erpnext.buying.procurement_workflow.PROCUREMENT_ASSIGNMENT_RULES", (spec,)):
			_ensure_procurement_assignment_rules()

		save.assert_not_called()

	@patch("erpnext.buying.procurement_automation.add_assignment")
	@patch("erpnext.buying.procurement_automation._close_assignments_silently")
	@patch(
		"erpnext.buying.procurement_automation._has_fully_reserved_material_request",
		return_value=True,
	)
	def test_material_request_assignment_is_not_recreated_after_consolidation(
		self, _has_consolidated_order, close_assignments, add_assignment
	):
		doc = frappe._dict(doctype="Material Request", name="MAT-MR-TEST")

		sync_procurement_stage_assignment(doc)

		close_assignments.assert_called_once()
		add_assignment.assert_not_called()
