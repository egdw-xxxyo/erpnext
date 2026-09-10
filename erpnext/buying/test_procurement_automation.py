from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order import (
	ConsolidatedPurchaseOrder,
	_is_purchase_receipt_stage_complete,
	get_allowed_primary_supplier_names,
	get_allowed_related_supplier_names,
	get_related_supplier_names,
)
from erpnext.buying.procurement_automation import (
	_close_assignments_silently,
	_get_consolidated_item_rate,
	_get_primary_procurement_initiator,
	_notify_procurement_initiators,
)
from erpnext.buying.procurement_workflow_reason import _apply_creator_department_approval
from erpnext.setup.procurement_workflow_setup import CUSTOM_FIELDS


class TestProcurementAutomation(FrappeTestCase):
	@patch("erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.get_all")
	def test_related_supplier_names_include_self_and_both_relation_directions(self, get_all):
		get_all.side_effect = [["SUPPLIER-B"], ["SUPPLIER-C"]]

		self.assertEqual(
			get_related_supplier_names("SUPPLIER-A"),
			["SUPPLIER-A", "SUPPLIER-B", "SUPPLIER-C"],
		)

	@patch("erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.db.get_value")
	@patch(
		"erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.get_related_supplier_names",
		return_value=["SUPPLIER-A", "SUPPLIER-B"],
	)
	def test_private_entrepreneur_can_select_cooperating_supplier(self, _get_related, get_value):
		get_value.return_value = "Individual"
		doc = MagicMock(
			items=[
				frappe._dict(
					idx=1,
					supplier="SUPPLIER-A",
					related_supplier="SUPPLIER-B",
					item_code=None,
					qty=1,
					rate=1,
					schedule_date="2026-09-08",
				)
			]
		)

		ConsolidatedPurchaseOrder._validate_items(doc)

	@patch("erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.db.get_value")
	def test_regular_supplier_rejects_different_related_supplier(self, get_value):
		get_value.return_value = "Company"
		doc = MagicMock(
			items=[
				frappe._dict(
					idx=1,
					supplier="SUPPLIER-A",
					related_supplier="SUPPLIER-X",
					item_code=None,
					qty=1,
					rate=1,
					schedule_date="2026-09-08",
				)
			]
		)

		with self.assertRaises(frappe.ValidationError):
			ConsolidatedPurchaseOrder._validate_items(doc)

	@patch("erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.db.get_value")
	def test_regular_supplier_can_select_itself(self, get_value):
		get_value.return_value = "Company"
		self.assertEqual(get_allowed_related_supplier_names("SUPPLIER-A"), ["SUPPLIER-A"])

	@patch("erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.get_all")
	@patch(
		"erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.get_related_supplier_names",
		return_value=["SUPPLIER-A", "SUPPLIER-B", "SUPPLIER-C"],
	)
	def test_reverse_selection_only_offers_self_and_connected_private_entrepreneurs(
		self, _get_related, get_all
	):
		get_all.return_value = ["SUPPLIER-A"]

		self.assertEqual(
			get_allowed_primary_supplier_names("SUPPLIER-B"),
			["SUPPLIER-A", "SUPPLIER-B"],
		)
		get_all.assert_called_once_with(
			"Supplier",
			filters={
				"name": ["in", ["SUPPLIER-A", "SUPPLIER-B", "SUPPLIER-C"]],
				"supplier_type": "Individual",
			},
			pluck="name",
		)

	@patch(
		"erpnext.buying.procurement_final_approval.get_configured_final_approvers",
		return_value=["ceo@example.invalid", "second.ceo@example.invalid"],
	)
	@patch("erpnext.buying.procurement_workflow_reason.frappe.db.exists", return_value=True)
	def test_ceo_creator_does_not_skip_department_review(self, _role_exists, _approvers):
		doc = frappe._dict(
			doctype="Consolidated Purchase Order",
			name="CPO-TEST",
			owner="ceo@example.invalid",
			workflow_state="Перевірка підрозділу",
		)
		core_apply_workflow = MagicMock()

		result = _apply_creator_department_approval(doc, core_apply_workflow)

		self.assertIs(result, doc)
		core_apply_workflow.assert_not_called()

	def test_prepaid_materials_still_require_warehouse_receipt(self):
		self.assertFalse(_is_purchase_receipt_stage_complete(True, [], {}))

	@patch("erpnext.buying.procurement_automation._get_procurement_chain")
	@patch("erpnext.buying.procurement_automation.frappe.get_all")
	def test_primary_initiator_comes_from_material_request(self, get_all, get_chain):
		get_chain.return_value = {
			"Material Request": {"MAT-MR-TEST"},
			"Consolidated Purchase Order": {"CPO-TEST"},
			"Purchase Order": set(),
		}
		get_all.return_value = [
			frappe._dict(owner="Administrator", custom_procurement_initiator_user=None)
		]

		self.assertEqual(_get_primary_procurement_initiator("CPO-TEST"), "Administrator")

	def test_purchase_receipt_ttn_is_not_provisioned(self):
		self.assertNotIn("Purchase Receipt", CUSTOM_FIELDS)

	@patch("erpnext.stock.get_item_details.get_price_list_rate_for")
	@patch("erpnext.buying.procurement_automation.frappe.get_cached_value")
	def test_consolidated_item_rate_falls_back_to_buying_price_list(
		self, get_cached_value, get_price_list_rate_for
	):
		get_cached_value.return_value = 0
		get_price_list_rate_for.return_value = 425

		rate = _get_consolidated_item_rate(
			frappe._dict(
				item_code="ITEM-1",
				base_rate=0,
				rate=0,
				uom="Nos",
				stock_uom="Nos",
				qty=2,
				conversion_factor=1,
			),
			frappe._dict(rate=0, price_list_rate=0, stock_uom="Nos", conversion_factor=1),
			frappe._dict(buying_price_list="Standard Buying", transaction_date="2026-08-24"),
			"SUPPLIER-1",
		)

		self.assertEqual(rate, 425)
		self.assertEqual(get_price_list_rate_for.call_args.args[0].supplier, "SUPPLIER-1")

	@patch("erpnext.stock.get_item_details.get_price_list_rate_for")
	def test_consolidated_item_rate_keeps_material_request_rate(self, get_price_list_rate_for):
		rate = _get_consolidated_item_rate(
			frappe._dict(item_code="ITEM-1", base_rate=0, rate=0),
			frappe._dict(rate=300, price_list_rate=300),
			frappe._dict(buying_price_list="Standard Buying"),
		)

		self.assertEqual(rate, 300)
		get_price_list_rate_for.assert_not_called()

	@patch("erpnext.buying.procurement_automation.frappe.get_cached_value")
	def test_consolidated_item_rate_falls_back_to_item_valuation_rate(self, get_cached_value):
		get_cached_value.return_value = (300, 255)

		rate = _get_consolidated_item_rate(
			frappe._dict(item_code="ITEM-1", base_rate=0, rate=0, conversion_factor=2),
			frappe._dict(rate=0, price_list_rate=0, conversion_factor=2),
			frappe._dict(buying_price_list=None),
		)

		self.assertEqual(rate, 600)
		get_cached_value.assert_called_once_with(
			"Item", "ITEM-1", ["valuation_rate", "last_purchase_rate"]
		)

	@patch("erpnext.buying.procurement_automation.enqueue_create_notification")
	@patch("erpnext.buying.procurement_automation._get_procurement_initiators")
	def test_final_notification_is_deduplicated(self, get_initiators, enqueue):
		get_initiators.return_value = ["initiator@example.invalid"]

		_notify_procurement_initiators("CPO-TEST", "completed")

		enqueue.assert_called_once()
		self.assertEqual(
			enqueue.call_args.kwargs["dedupe_on"],
			["document_type", "document_name", "subject"],
		)
		self.assertIn("завершено", enqueue.call_args.args[1]["subject"])

	@patch("frappe.desk.form.assign_to.notify_assignment")
	@patch("erpnext.buying.procurement_automation.frappe.get_doc")
	@patch("erpnext.buying.procurement_automation.frappe.get_all")
	def test_stage_assignment_is_closed_without_cancellation_notification(
		self, get_all, get_doc, notify_assignment
	):
		get_all.return_value = ["TODO-TEST"]
		todo = MagicMock(status="Open")
		get_doc.return_value = todo

		_close_assignments_silently("Purchase Order", "PO-TEST")

		self.assertEqual(todo.status, "Closed")
		todo.save.assert_called_once_with(ignore_permissions=True)
		notify_assignment.assert_not_called()
