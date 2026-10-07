from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.buying import procurement_order_reuse as reuse
from erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order import (
	ConsolidatedPurchaseOrder,
)
from erpnext.buying.procurement_workflow import DOCTYPE_PERMISSIONS, MATERIAL_REQUEST_PREPARER_ROLE
from erpnext.setup.procurement_workflow_setup import _sync_consolidated_procurement_users

GET_DOC = frappe.get_doc


class TestProcurementOrderReuse(IntegrationTestCase):
	def source(self):
		return GET_DOC(
			{
				"doctype": "Material Request",
				"name": "MR-REUSE-TEST",
				"docstatus": 1,
				"material_request_type": "Purchase",
				"items": [
					{
						"name": "ROW1",
						"item_code": "ITEM1",
						"qty": 10,
						"stock_qty": 20,
						"conversion_factor": 2,
						"uom": "Box",
						"ordered_qty": 0,
					},
					{
						"name": "ROW2",
						"item_code": "ITEM1",
						"qty": 5,
						"stock_qty": 5,
						"conversion_factor": 1,
						"uom": "Nos",
						"ordered_qty": 0,
					},
				],
			}
		)

	def reservation(self, **values):
		return frappe._dict(
			parent="CPO1",
			material_request_item="ROW1",
			item_code="ITEM1",
			uom="Box",
			qty=6,
			purchase_order_item=None,
			**values,
		)

	@patch.object(reuse.frappe.db, "sql")
	def test_partial_reservation_preserves_original_rows(self, sql):
		sql.return_value = [self.reservation()]
		remaining = reuse.get_material_request_remaining(self.source())
		self.assertEqual(remaining["ROW1"].remaining_qty, 4)
		self.assertEqual(remaining["ROW2"].remaining_qty, 5)
		self.assertIn("p.docstatus < 2", sql.call_args.args[0])
		self.assertIn("Відхилено", sql.call_args.args[0])

	@patch.object(reuse.frappe, "get_all")
	@patch.object(reuse.frappe.db, "sql")
	def test_submitted_purchase_order_is_counted_once_and_current_order_can_be_saved(self, sql, get_all):
		source = self.source()
		source.items[0].ordered_qty = 14  # Twelve covered units, plus two from a separate PO.
		row = self.reservation()
		row.purchase_order_item = "POI1"
		sql.return_value = [row]
		get_all.return_value = [frappe._dict(material_request_item="ROW1", stock_qty=12)]
		self.assertEqual(reuse.get_material_request_remaining(source)["ROW1"].remaining_qty, 3)
		self.assertEqual(
			reuse.get_material_request_remaining(source, exclude="CPO1")["ROW1"].remaining_qty, 9
		)

	@patch.object(reuse, "get_material_request_remaining")
	@patch.object(reuse.frappe, "get_doc")
	def test_mapping_only_contains_unreserved_quantities(self, get_doc, remaining):
		source = self.source()
		get_doc.side_effect = (
			lambda dt, *args, **kwargs: source if dt == "Material Request" else GET_DOC(dt, *args, **kwargs)
		)
		remaining.return_value = {
			"ROW1": frappe._dict(remaining_qty=4),
			"ROW2": frappe._dict(remaining_qty=0),
		}
		mapped = frappe.new_doc("Purchase Order")
		for name, qty in (("ROW1", 10), ("ROW2", 5)):
			mapped.append(
				"items",
				{
					"material_request_item": name,
					"item_code": "ITEM1",
					"qty": qty,
					"uom": "Box" if name == "ROW1" else "Nos",
					"rate": 3,
				},
			)
		reuse.limit_mapped_request_items(mapped, "MR-REUSE-TEST")
		self.assertEqual(len(mapped.items), 1)
		self.assertEqual((mapped.items[0].qty, mapped.items[0].stock_qty, mapped.items[0].amount), (4, 8, 12))

	@patch.object(reuse, "get_material_request_remaining")
	@patch.object(reuse.frappe, "get_doc")
	def test_combined_duplicate_rows_cannot_exceed_remaining_quantity(self, get_doc, remaining):
		source = self.source()
		source.check_permission = MagicMock()
		get_doc.side_effect = (
			lambda dt, *args, **kwargs: source if dt == "Material Request" else GET_DOC(dt, *args, **kwargs)
		)
		remaining.return_value = {"ROW1": frappe._dict(remaining_qty=4)}
		doc = frappe.new_doc("Consolidated Purchase Order")
		for _i in range(2):
			doc.append(
				"items",
				{
					"material_request": source.name,
					"material_request_item": "ROW1",
					"item_code": "ITEM1",
					"uom": "Box",
					"qty": 3,
				},
			)
		with self.assertRaises(frappe.ValidationError):
			reuse.validate_consolidated_request_quantities(doc)
		get_doc.assert_any_call("Material Request", source.name, for_update=True)
		remaining.assert_called_once_with(source, exclude=doc.name, lock=True)

	@patch.object(reuse, "get_material_request_remaining")
	@patch.object(reuse.frappe, "get_doc")
	def test_item_cannot_claim_a_different_source_row(self, get_doc, remaining):
		source = self.source()
		source.check_permission = MagicMock()
		get_doc.side_effect = (
			lambda dt, *args, **kwargs: source if dt == "Material Request" else GET_DOC(dt, *args, **kwargs)
		)
		remaining.return_value = {"ROW1": frappe._dict(remaining_qty=10)}
		doc = frappe.new_doc("Consolidated Purchase Order")
		doc.append(
			"items",
			{
				"material_request": source.name,
				"material_request_item": "ROW1",
				"item_code": "DIFFERENT",
				"uom": "Box",
				"qty": 1,
			},
		)
		with self.assertRaises(frappe.ValidationError):
			reuse.validate_consolidated_request_quantities(doc)

	@patch.object(reuse, "require_buyer_role")
	@patch.object(reuse.frappe, "has_permission", return_value=True)
	@patch.object(reuse.frappe, "get_doc")
	@patch.object(ConsolidatedPurchaseOrder, "insert")
	def test_repeat_does_not_copy_identity_invoices_links_or_approvals(
		self, insert, get_doc, _permission, _buyer
	):
		source = ConsolidatedPurchaseOrder(
			{
				"doctype": "Consolidated Purchase Order",
				"name": "CPO-OLD",
				"company": "TEST",
				"currency": "UAH",
				"material_request": "OLD-MR",
				"request_initiator_user": "old-user",
				"workflow_state": "Проведено",
				"supplier_invoices": [{"supplier": "SUP", "invoice_pdf": "/private/files/old.pdf"}],
				"items": [
					{
						"supplier": "SUP",
						"related_supplier": "SUP-RELATED",
						"item_code": "ITEM1",
						"item_name": "Item",
						"qty": 3,
						"rate": 2,
						"uom": "Nos",
						"warehouse": "WH",
						"schedule_date": "2000-01-01",
						"material_request": "OLD-MR",
						"material_request_item": "OLD-ROW",
						"purchase_order": "OLD-PO",
						"purchase_order_item": "OLD-POI",
					}
				],
			}
		)
		source.append("items", {"supplier": "LEGACY-SUP", "item_code": "ITEM2", "qty": 1, "uom": "Nos"})
		source.check_permission = MagicMock()
		get_doc.side_effect = (
			lambda dt, *args, **kwargs: source
			if dt == "Consolidated Purchase Order"
			else GET_DOC(dt, *args, **kwargs)
		)
		target = reuse.repeat_consolidated_order(source.name)
		insert.assert_called_once()
		self.assertEqual(target.workflow_state, "Чернетка")
		self.assertEqual(target.company, source.company)
		self.assertEqual(target.items[0].related_supplier, "SUP-RELATED")
		self.assertEqual(target.items[1].related_supplier, "LEGACY-SUP")
		self.assertFalse(target.request_initiator_user)
		self.assertFalse(target.material_request)
		self.assertFalse(target.supplier_invoices)
		self.assertEqual((target.items[0].qty, target.items[0].warehouse), (3, "WH"))
		for field in ("material_request", "material_request_item", "purchase_order", "purchase_order_item"):
			self.assertFalse(target.items[0].get(field))
		self.assertGreaterEqual(str(target.items[0].schedule_date), reuse.nowdate())

	def test_repeat_draft_can_be_saved_but_requires_initiator_for_approval(self):
		doc = ConsolidatedPurchaseOrder(
			{
				"doctype": "Consolidated Purchase Order",
				"workflow_state": "Чернетка",
				"initiator_user": "Administrator",
			}
		)
		doc._set_procurement_users()
		doc.workflow_state = "Перевірка підрозділу"
		with self.assertRaises(frappe.ValidationError):
			doc._set_procurement_users()

	def test_preparer_has_no_submission_permissions(self):
		permissions = DOCTYPE_PERMISSIONS["Material Request"][MATERIAL_REQUEST_PREPARER_ROLE]
		self.assertTrue({"read", "create", "write"}.issubset(permissions))
		self.assertFalse({"submit", "cancel", "amend"}.intersection(permissions))

	@patch("erpnext.setup.procurement_workflow_setup.frappe.db.set_value")
	@patch("erpnext.setup.procurement_workflow_setup.frappe.get_all")
	@patch("erpnext.setup.procurement_workflow_setup.frappe.db.table_exists", return_value=True)
	def test_migration_preserves_deliberately_empty_draft_initiator(self, _exists, get_all, set_value):
		get_all.side_effect = [
			[
				frappe._dict(
					name="CPO-REPEATED",
					owner="Administrator",
					initiator_user="Administrator",
					request_initiator_user=None,
					docstatus=0,
					workflow_state="Чернетка",
				)
			],
			[],
		]
		_sync_consolidated_procurement_users()
		self.assertIsNone(set_value.call_args.args[2]["request_initiator_user"])
