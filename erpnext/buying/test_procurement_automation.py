from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext.accounts.doctype.payment_request.payment_request import PaymentRequest
from erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order import (
	ConsolidatedPurchaseOrder,
	_get_material_request_summaries,
	_get_supplier_invoice_suppliers,
	_is_purchase_receipt_stage_complete,
	get_allowed_primary_supplier_names,
	get_allowed_related_supplier_names,
	get_purchase_invoice_options,
	get_related_supplier_names,
	get_supplier_invoice_files,
	make_purchase_invoice,
)
from erpnext.buying.doctype.supplier.supplier import (
	get_supplier_bank_accounts,
	set_default_supplier_bank_account,
)
from erpnext.buying.procurement_assignment import (
	_add as add_procurement_assignment_internal,
)
from erpnext.buying.procurement_assignment import (
	add as add_procurement_assignment,
)
from erpnext.buying.procurement_automation import (
	_close_assignments_silently,
	_get_consolidated_item_rate,
	_get_primary_procurement_initiator,
	_notify_procurement_initiators,
	get_material_request_consolidated_orders,
	notify_procurement_approval,
	notify_procurement_receipt,
	sync_all_current_assignee_names,
)
from erpnext.buying.procurement_workflow import _remove_obsolete_purchase_order_permissions
from erpnext.buying.procurement_workflow_reason import _apply_creator_department_approval
from erpnext.setup.procurement_workflow_setup import CUSTOM_FIELDS


class TestProcurementAutomation(FrappeTestCase):
	@patch("erpnext.buying.procurement_assignment.frappe.msgprint")
	@patch(
		"erpnext.buying.procurement_assignment.frappe.get_cached_value",
		return_value="Тестовий Закупівельник",
	)
	@patch("erpnext.buying.procurement_assignment.frappe.db.exists", return_value=True)
	@patch("erpnext.buying.procurement_assignment.frappe.get_doc")
	@patch("erpnext.buying.procurement_assignment.get_assignments", return_value=[])
	@patch("erpnext.buying.procurement_assignment.core_add")
	def test_duplicate_procurement_assignment_message_uses_full_name(
		self, core_add, _get_assignments, _get_doc, _exists, _get_name, msgprint
	):
		add_procurement_assignment(
			frappe._dict(
				doctype="Material Request",
				name="MAT-MR-TEST",
				assign_to=["procurement.buyer@example.invalid"],
			)
		)

		core_add.assert_not_called()
		message = msgprint.call_args.args[0]
		self.assertIn("Тестовий Закупівельник", message)
		self.assertNotIn("procurement.buyer@example.invalid", message)

	@patch("erpnext.buying.procurement_assignment.frappe.msgprint")
	@patch(
		"erpnext.buying.procurement_assignment.frappe.get_cached_value",
		return_value="Тестовий Закупівельник",
	)
	@patch("erpnext.buying.procurement_assignment.frappe.db.exists", return_value=True)
	@patch("erpnext.buying.procurement_assignment.frappe.get_doc")
	@patch("erpnext.buying.procurement_assignment.get_assignments", return_value=[])
	@patch("erpnext.buying.procurement_assignment.core_add")
	def test_automatic_duplicate_assignment_uses_full_name_without_permission_check(
		self, core_add, _get_assignments, get_doc, _exists, _get_name, msgprint
	):
		add_procurement_assignment_internal(
			frappe._dict(
				doctype="Material Request",
				name="MAT-MR-TEST",
				assign_to=["procurement.buyer@example.invalid"],
			),
			ignore_permissions=True,
		)

		core_add.assert_not_called()
		get_doc.assert_not_called()
		message = msgprint.call_args.args[0]
		self.assertIn("Тестовий Закупівельник", message)
		self.assertNotIn("procurement.buyer@example.invalid", message)

	@patch("erpnext.buying.procurement_automation.frappe.get_all")
	@patch("erpnext.buying.procurement_automation.frappe.get_doc")
	def test_material_request_lists_all_linked_consolidated_orders(self, get_doc, get_all):
		get_all.side_effect = [
			["CPO-2"],
			["CPO-1"],
			[
				frappe._dict(
					name="CPO-2",
					workflow_state="Погоджено",
					procurement_completion_status="Очікує оплату",
					docstatus=1,
				)
			],
		]

		result = get_material_request_consolidated_orders("MAT-MR-TEST")

		get_doc.return_value.check_permission.assert_called_once_with("read")
		self.assertEqual(result[0].name, "CPO-2")
		self.assertEqual(result[0].workflow_state, "Погоджено")
		self.assertEqual(result[0].procurement_completion_status, "Очікує оплату")

	@patch("erpnext.buying.procurement_automation.frappe.db.has_column", return_value=True)
	@patch("erpnext.buying.procurement_automation.frappe.db.exists", return_value=True)
	@patch("erpnext.buying.procurement_automation.frappe.db.set_value")
	@patch("erpnext.buying.procurement_automation.frappe.get_cached_value")
	@patch("erpnext.buying.procurement_automation.frappe.get_all")
	def test_current_assignee_backfill_stores_names_not_emails(
		self, get_all, get_cached_value, set_value, _exists, _has_column
	):
		get_all.side_effect = [
			["CPO-TEST"],
			[frappe._dict(name="TODO-TEST", allocated_to="buyer@example.invalid")],
		]
		get_cached_value.return_value = "Тестовий Закупівельник"

		sync_all_current_assignee_names()

		set_value.assert_called_once_with(
			"Consolidated Purchase Order",
			"CPO-TEST",
			"current_assignees",
			"Тестовий Закупівельник",
			update_modified=False,
		)

	@patch(
		"erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.get_cached_value",
		return_value="Замовник Матеріалів",
	)
	@patch("erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.get_all")
	def test_material_request_comment_is_read_and_sanitized_without_copying(self, get_all, _get_name):
		get_all.return_value = [
			frappe._dict(
				name="MAT-MR-TEST",
				owner="requester@example.invalid",
				custom_procurement_comment="<p>Потрібно терміново</p><script>alert(1)</script>",
			)
		]
		doc = frappe._dict(
			items=[frappe._dict(material_request="MAT-MR-TEST")], material_request="MAT-MR-TEST"
		)

		result = _get_material_request_summaries(doc)

		self.assertIn("Потрібно терміново", result[0].procurement_comment)
		self.assertNotIn("<script", result[0].procurement_comment)
		self.assertEqual(result[0].created_by.full_name, "Замовник Матеріалів")

	@patch("erpnext.buying.doctype.supplier.supplier.frappe.get_all")
	@patch("erpnext.buying.doctype.supplier.supplier.frappe.get_doc")
	def test_supplier_bank_accounts_are_read_from_standard_records(self, get_doc, get_all):
		get_all.return_value = [
			frappe._dict(name="BANK-A", account_name="Supplier Main", iban="UA123", is_default=1)
		]

		result = get_supplier_bank_accounts("SUPPLIER-A")

		get_doc.return_value.check_permission.assert_called_once_with("read")
		get_all.assert_called_once_with(
			"Bank Account",
			filters={
				"party_type": "Supplier",
				"party": "SUPPLIER-A",
				"is_company_account": 0,
				"disabled": 0,
			},
			fields=["name", "account_name", "iban", "is_default"],
			order_by="is_default desc, account_name asc, name asc",
		)
		self.assertEqual(result[0].name, "BANK-A")

	@patch("erpnext.buying.doctype.supplier.supplier.frappe.clear_cache")
	@patch("erpnext.buying.doctype.supplier.supplier.frappe.db.set_value")
	@patch("erpnext.buying.doctype.supplier.supplier._get_supplier_bank_accounts")
	@patch("erpnext.buying.doctype.supplier.supplier.frappe.get_doc")
	def test_supplier_default_bank_account_is_changed_on_supplier_save(
		self, get_doc, get_accounts, set_value, clear_cache
	):
		before = [
			frappe._dict(name="BANK-A", is_default=1),
			frappe._dict(name="BANK-B", is_default=0),
		]
		after = [frappe._dict(name="BANK-B", account_name="New Main", iban="UA456", is_default=1)]
		get_accounts.side_effect = [before, after]

		result = set_default_supplier_bank_account("SUPPLIER-A", "BANK-B")

		get_doc.return_value.check_permission.assert_called_once_with("write")
		set_value.assert_any_call("Bank Account", "BANK-A", "is_default", 0, update_modified=False)
		set_value.assert_any_call("Bank Account", "BANK-B", "is_default", 1, update_modified=False)
		clear_cache.assert_called_once_with(doctype="Bank Account")
		self.assertEqual(result, after)

	@patch("erpnext.accounts.doctype.payment_request.payment_request.frappe.throw")
	@patch("erpnext.accounts.doctype.payment_request.payment_request.frappe.db.get_value")
	def test_payment_request_rejects_another_suppliers_bank_account(self, get_value, throw):
		get_value.return_value = frappe._dict(
			party_type="Supplier",
			party="SUPPLIER-B",
			is_company_account=0,
			disabled=0,
		)
		doc = MagicMock(
			payment_request_type="Outward",
			party_type="Supplier",
			party="SUPPLIER-A",
			bank_account="BANK-B",
		)

		PaymentRequest.validate_supplier_bank_account(doc)

		throw.assert_called_once()

	@patch("erpnext.buying.procurement_workflow.frappe.delete_doc")
	@patch("erpnext.buying.procurement_workflow.frappe.get_all")
	def test_obsolete_purchase_order_permissions_are_removed(self, get_all, delete_doc):
		get_all.return_value = ["OLD-PERM-1", "OLD-PERM-2"]

		_remove_obsolete_purchase_order_permissions()

		self.assertEqual(delete_doc.call_count, 2)
		delete_doc.assert_any_call("Custom DocPerm", "OLD-PERM-1", force=True, ignore_permissions=True)

	@patch("erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.get_doc")
	@patch("erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.get_all")
	def test_supplier_invoice_files_are_read_from_source_for_exact_supplier(self, get_all, get_doc):
		source = MagicMock()
		get_doc.return_value = source
		get_all.return_value = [
			frappe._dict(invoice_document="supplier-invoice.pdf", invoice_pdf="/private/files/invoice.pdf")
		]

		result = get_supplier_invoice_files("CPO-TEST", "SUPPLIER-A")

		source.check_permission.assert_called_once_with("read")
		get_all.assert_called_once_with(
			"Consolidated Purchase Supplier Invoice",
			filters={
				"parent": "CPO-TEST",
				"parenttype": "Consolidated Purchase Order",
				"parentfield": "supplier_invoices",
				"supplier": "SUPPLIER-A",
				"invoice_pdf": ["is", "set"],
			},
			fields=["invoice_document", "invoice_pdf"],
			order_by="idx asc",
		)
		self.assertEqual(
			result,
			[
				{
					"consolidated_order": "CPO-TEST",
					"supplier": "SUPPLIER-A",
					"files": [
						{
							"file_name": "supplier-invoice.pdf",
							"file_url": "/private/files/invoice.pdf",
						}
					],
				}
			],
		)

	@patch(
		"erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order._get_supplier_invoice_suppliers",
		return_value={"SUPPLIER-A"},
	)
	@patch("erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.get_all")
	@patch("erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.get_doc")
	def test_purchase_invoice_options_only_include_suppliers_with_attached_invoice(
		self, get_doc, get_all, _get_invoice_suppliers
	):
		get_all.return_value = [
			frappe._dict(
				name="PO-A",
				supplier="SUPPLIER-A",
				supplier_name="Supplier A",
				grand_total=100,
				currency="UAH",
				per_billed=0,
			),
			frappe._dict(
				name="PO-B",
				supplier="SUPPLIER-B",
				supplier_name="Supplier B",
				grand_total=200,
				currency="UAH",
				per_billed=0,
			),
		]

		result = get_purchase_invoice_options("CPO-TEST")

		self.assertEqual([row.supplier for row in result["eligible_orders"]], ["SUPPLIER-A"])
		self.assertEqual(
			result["missing_suppliers"],
			[{"supplier": "SUPPLIER-B", "supplier_name": "Supplier B"}],
		)
		get_doc.return_value.check_permission.assert_called_once_with("read")

	@patch(
		"erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order._get_supplier_invoice_suppliers",
		return_value=set(),
	)
	@patch("erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.get_doc")
	def test_purchase_invoice_creation_requires_attached_supplier_invoice(
		self, get_doc, _get_invoice_suppliers
	):
		get_doc.return_value.docstatus = 1

		with self.assertRaises(frappe.ValidationError):
			make_purchase_invoice("CPO-TEST", "SUPPLIER-A")

	@patch("erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.get_all")
	def test_supplier_invoice_supplier_lookup_requires_attached_file(self, get_all):
		get_all.return_value = ["SUPPLIER-A"]

		self.assertEqual(_get_supplier_invoice_suppliers("CPO-TEST"), {"SUPPLIER-A"})
		get_all.assert_called_once_with(
			"Consolidated Purchase Supplier Invoice",
			filters={
				"parent": "CPO-TEST",
				"parenttype": "Consolidated Purchase Order",
				"parentfield": "supplier_invoices",
				"invoice_pdf": ["is", "set"],
			},
			pluck="supplier",
		)

	@patch("erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.get_doc")
	@patch("erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.get_all")
	def test_payment_reference_resolves_supplier_files_through_purchase_invoice(self, get_all, get_doc):
		purchase_invoice = MagicMock()
		purchase_invoice.supplier = "SUPPLIER-A"
		purchase_invoice.custom_consolidated_purchase_order = "CPO-TEST"
		purchase_invoice.get.side_effect = lambda fieldname: getattr(purchase_invoice, fieldname, None)
		source = MagicMock()
		get_doc.side_effect = (
			lambda doctype, _name: purchase_invoice if doctype == "Purchase Invoice" else source
		)
		get_all.return_value = []

		result = get_supplier_invoice_files(
			references=[
				{
					"reference_doctype": "Purchase Invoice",
					"reference_name": "PINV-TEST",
					"payment_request": "PAY-REQ-TEST",
				}
			]
		)

		purchase_invoice.check_permission.assert_called_once_with("read")
		source.check_permission.assert_not_called()
		get_doc.assert_called_once_with("Purchase Invoice", "PINV-TEST")
		self.assertEqual(result[0]["consolidated_order"], "CPO-TEST")
		self.assertEqual(result[0]["supplier"], "SUPPLIER-A")

	@patch("erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.get_all")
	def test_related_supplier_names_include_self_and_both_relation_directions(self, get_all):
		get_all.side_effect = [["SUPPLIER-B"], ["SUPPLIER-C"]]

		self.assertEqual(
			get_related_supplier_names("SUPPLIER-A"),
			["SUPPLIER-A", "SUPPLIER-B", "SUPPLIER-C"],
		)

	@patch(
		"erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.db.get_value"
	)
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

	@patch(
		"erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.db.get_value"
	)
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

	@patch(
		"erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.frappe.db.get_value"
	)
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
		get_all.return_value = [frappe._dict(owner="Administrator", custom_procurement_initiator_user=None)]

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
		get_cached_value.assert_called_once_with("Item", "ITEM-1", ["valuation_rate", "last_purchase_rate"])

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

	@patch("erpnext.buying.procurement_automation.enqueue_create_notification")
	@patch("erpnext.buying.procurement_automation._get_procurement_requests_with_initiators")
	@patch(
		"erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order._get_invoice_receipt_summary"
	)
	def test_receipt_notification_identifies_each_material_request(
		self, get_receipt_summary, get_requests, enqueue
	):
		get_receipt_summary.return_value = {"purchase_receipt_complete": True}
		get_requests.return_value = [
			frappe._dict(name="MAT-MR-0001", initiator="first@example.invalid"),
			frappe._dict(name="MAT-MR-0002", initiator="second@example.invalid"),
		]

		notify_procurement_receipt("CON-PO-0001", "MAT-PRE-0001")

		self.assertEqual(enqueue.call_count, 2)
		first_recipients, first_notification = enqueue.call_args_list[0].args
		self.assertEqual(first_recipients, ["first@example.invalid"])
		self.assertEqual(
			first_notification["subject"],
			"Надходження за замовленням матеріалів MAT-MR-0001: повністю",
		)
		self.assertEqual(
			first_notification["email_content"],
			"За вашим замовленням матеріалів MAT-MR-0001 товари надійшли повністю. "
			"Прихідна накладна: MAT-PRE-0001. Замовлення на придбання: CON-PO-0001.",
		)
		self.assertIn("email_content", enqueue.call_args.kwargs["dedupe_on"])
		get_receipt_summary.return_value = {"purchase_receipt_complete": False}
		enqueue.reset_mock()
		notify_procurement_receipt("CON-PO-0001", "MAT-PRE-0002")
		self.assertEqual(
			enqueue.call_args_list[0].args[1]["subject"],
			"Надходження за замовленням матеріалів MAT-MR-0001: частково",
		)

	@patch("erpnext.buying.procurement_automation.sync_procurement_participants_for_reference")
	@patch("erpnext.buying.procurement_automation.enqueue_create_notification")
	@patch("erpnext.buying.procurement_automation.frappe.get_cached_value", return_value="Закупівельник")
	def test_approval_alert_uses_buyer_name_and_only_sends_on_stage_entry(
		self, _get_name, enqueue, _participants
	):
		doc = MagicMock(
			doctype="Consolidated Purchase Order",
			workflow_state="Перевірка підрозділу",
			flags=frappe._dict(),
		)
		doc.name = "CON-PO-0001"
		doc.get.return_value = "buyer@example.invalid"
		doc.get_doc_before_save.return_value = frappe._dict(workflow_state="Чернетка")
		text = "Перевірити і погодити зведене замовлення на придбання CON-PO-0001."

		notify_procurement_approval(doc, ["head@example.invalid"], text)
		notify_procurement_approval(doc, ["head@example.invalid"], text)

		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.args[1]["type"], "Alert")
		self.assertEqual(enqueue.call_args.args[1]["email_content"], text)
		self.assertEqual(
			enqueue.call_args.args[1]["subject"],
			"Нове замовлення на придбання потребує погодження: CON-PO-0001. "
			"Ведучий закупівельник: Закупівельник",
		)
		doc.flags.clear()
		doc.get_doc_before_save.return_value = frappe._dict(workflow_state=doc.workflow_state)
		notify_procurement_approval(doc, ["head@example.invalid"], text)
		enqueue.assert_called_once()

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
