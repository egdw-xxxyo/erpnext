from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.buying.procurement_automation import _get_consolidated_procurement_status
from erpnext.buying.procurement_receipt_linking import _eligible_receipt, _require_manager, link_receipts


class TestProcurementReceiptLinking(IntegrationTestCase):
	@patch("erpnext.buying.procurement_receipt_linking.frappe.get_roles")
	def test_only_system_manager(self, roles):
		roles.return_value = ["Закупівельник"]
		with self.assertRaises(frappe.PermissionError):
			_require_manager()
		roles.return_value = ["System Manager"]
		_require_manager()

	def make_documents(self, quantities):
		order = MagicMock()
		order.name = "PO-A"
		order.docstatus = 1
		order.status = "To Receive and Bill"
		order.supplier = "SUP-A"
		order.company = "COMP-A"
		order.currency = "UAH"
		order.items = [
			frappe._dict(
				name="PO-ROW", item_code="ITEM-A", uom="Nos", conversion_factor=1, qty=10, received_qty=0
			)
		]
		receipts = []
		for index, qty in enumerate(quantities):
			receipt = MagicMock()
			receipt.name = f"PR-{index}"
			receipt.docstatus = 1
			receipt.is_return = 0
			receipt.supplier = order.supplier
			receipt.company = order.company
			receipt.currency = order.currency
			receipt.items = [
				frappe._dict(
					name=f"PR-ROW-{index}", item_code="ITEM-A", uom="Nos", conversion_factor=1, qty=qty
				)
			]
			receipts.append(receipt)
		mappings = [
			{"receipt": receipt.name, "receipt_row": receipt.items[0].name, "order_row": "PO-ROW"}
			for receipt in receipts
		]
		return order, receipts, mappings

	def test_candidates_reject_other_orders_suppliers_and_returns(self):
		order, receipts, mappings = self.make_documents([4])
		receipt = receipts[0]
		self.assertTrue(_eligible_receipt(receipt, order))
		receipt.items[0].purchase_order = "PO-OTHER"
		self.assertFalse(_eligible_receipt(receipt, order))
		receipt.items[0].purchase_order = None
		receipt.supplier = "OTHER"
		self.assertFalse(_eligible_receipt(receipt, order))
		receipt.supplier = order.supplier
		receipt.is_return = 1
		self.assertFalse(_eligible_receipt(receipt, order))

	@patch("erpnext.buying.procurement_receipt_linking._require_manager")
	@patch("erpnext.buying.procurement_receipt_linking.frappe.db.set_value")
	@patch("erpnext.buying.procurement_receipt_linking.frappe.get_doc")
	def test_combined_quantities_cannot_exceed_order(self, get_doc, set_value, manager):
		order, receipts, mappings = self.make_documents([6, 6])
		get_doc.side_effect = [order, *receipts]
		with self.assertRaises(frappe.ValidationError):
			link_receipts(order.name, mappings)
		set_value.assert_not_called()
		for receipt in receipts:
			receipt.update_prevdoc_status.assert_not_called()

	@patch(
		"erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.sync_linked_consolidated_purchase_order_progress"
	)
	@patch("erpnext.buying.procurement_receipt_linking.frappe.clear_document_cache")
	@patch("erpnext.buying.procurement_receipt_linking._require_manager")
	@patch("erpnext.buying.procurement_receipt_linking.frappe.db.set_value")
	@patch("erpnext.buying.procurement_receipt_linking.frappe.get_doc")
	def test_multiple_receipts_link_without_resubmitting_stock(
		self, get_doc, set_value, manager, clear_cache, progress
	):
		order, receipts, mappings = self.make_documents([4, 6])
		get_doc.side_effect = [order, *receipts]
		self.assertEqual(link_receipts(order.name, mappings)["receipts"], ["PR-0", "PR-1"])
		for receipt in receipts:
			receipt.update_prevdoc_status.assert_called_once()
			receipt.submit.assert_not_called()
			receipt.save.assert_not_called()
			receipt.update_stock_ledger.assert_not_called()
			self.assertEqual(receipt.items[0].purchase_order_item, "PO-ROW")

	def test_all_suppliers_need_delivery_notes_to_complete(self):
		doc = MagicMock()
		doc.docstatus = 1
		doc.items = [frappe._dict(supplier="A"), frappe._dict(supplier="B")]
		doc.get.return_value = [frappe._dict(supplier="A", delivery_note_file="a.pdf")]
		args = dict(
			terminal=False,
			payment_complete=True,
			fiscal_receipt_complete=True,
			purchase_receipt_complete=True,
			warehouse_receipt_complete=True,
		)
		self.assertEqual(_get_consolidated_procurement_status(doc, **args), "Очікуються видаткові накладні")
		doc.get.return_value.append(frappe._dict(supplier="B", delivery_note_file="b.pdf"))
		self.assertEqual(_get_consolidated_procurement_status(doc, **args), "Завершено")
		args.update(fiscal_receipt_complete=False, purchase_receipt_complete=False)
		doc.get.return_value.pop()
		self.assertEqual(_get_consolidated_procurement_status(doc, **args), "Очікуються видаткові накладні")
		args["warehouse_receipt_complete"] = False
		self.assertEqual(_get_consolidated_procurement_status(doc, **args), "Очікує надходження")
