from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.accounts.supplier_requisites_validation import update_supplier_requisites_from_pdf
from erpnext.buying.procurement_document_details import (
	add_delivery_note,
	can_add_delivery_note,
	sync_order_details,
)


class TestProcurementDocumentDetails(IntegrationTestCase):
	@patch("erpnext.buying.procurement_document_details.frappe.get_roles")
	def test_delivery_note_permissions(self, roles):
		doc = frappe._dict(
			docstatus=1,
			owner="creator@example.com",
			initiator_user="buyer@example.com",
			procurement_completion_status="Підготовка",
		)
		with patch(
			"erpnext.buying.procurement_document_details.frappe.session",
			frappe._dict(user="treasurer@example.com"),
		):
			roles.return_value = ["Payments: Казначей"]
			self.assertTrue(can_add_delivery_note(doc))
			roles.return_value = ["Закупівельник"]
			self.assertFalse(can_add_delivery_note(doc))
		with patch(
			"erpnext.buying.procurement_document_details.frappe.session",
			frappe._dict(user="buyer@example.com"),
		):
			self.assertTrue(can_add_delivery_note(doc))
			roles.return_value = []
			self.assertFalse(can_add_delivery_note(doc))
		with patch(
			"erpnext.buying.procurement_document_details.frappe.session",
			frappe._dict(user="treasurer@example.com"),
		):
			roles.return_value = ["Payments: Казначей"]
			doc.docstatus = 0
			self.assertFalse(can_add_delivery_note(doc))
			doc.docstatus = 1
			doc.procurement_completion_status = "Завершено"
			self.assertFalse(can_add_delivery_note(doc))

	@patch("erpnext.buying.procurement_document_details.can_add_delivery_note", return_value=True)
	@patch("erpnext.buying.procurement_document_details.frappe.get_doc")
	def test_cannot_reuse_file_from_another_document(self, get_doc, allowed):
		doc = MagicMock()
		file = MagicMock(attached_to_doctype="Chat Thread", attached_to_name="private-chat")
		get_doc.side_effect = [doc, file]
		with self.assertRaises(frappe.PermissionError):
			add_delivery_note("CPO-A", "SUP-A", "/private/files/note.pdf")
		doc.save.assert_not_called()

	@patch("erpnext.buying.procurement_document_details.frappe.db.set_value")
	@patch("erpnext.buying.procurement_document_details.frappe.get_all")
	def test_sync_updates_only_changed_values_without_saving(self, get_all, set_value):
		doc = MagicMock()
		doc.doctype = "Consolidated Purchase Order"
		doc.name = "CPO-A"
		doc.request_initiator_user = "initiator@example.com"
		doc.items = [frappe._dict(supplier="SUP-A")]
		doc.delivery_notes = [frappe._dict(supplier="SUP-A", delivery_note_file="note.pdf")]
		doc.get.return_value = 1
		get_all.return_value = [
			frappe._dict(name="PO-A", custom_request_initiator_user=doc.request_initiator_user)
		]
		sync_order_details(doc)
		doc.db_set.assert_not_called()
		set_value.assert_not_called()
		get_all.return_value[0].custom_request_initiator_user = "old@example.com"
		sync_order_details(doc)
		self.assertFalse(set_value.call_args.kwargs["update_modified"])
		doc.save.assert_not_called()

	@patch("erpnext.buying.procurement_document_details.frappe.db.set_value")
	@patch("erpnext.buying.procurement_document_details.frappe.get_all", return_value=[])
	def test_delivery_note_counts_distinct_matching_suppliers(self, get_all, set_value):
		doc = MagicMock(doctype="Consolidated Purchase Order", name="CPO-A")
		doc.items = [frappe._dict(supplier="A"), frappe._dict(supplier="B"), frappe._dict(supplier="A")]
		doc.delivery_notes = [
			frappe._dict(supplier="A", delivery_note_file="one.pdf"),
			frappe._dict(supplier="A", delivery_note_file="two.zip"),
			frappe._dict(supplier="B", delivery_note_file=""),
			frappe._dict(supplier="OTHER", delivery_note_file="other.pdf"),
		]
		doc.get.return_value = 0
		sync_order_details(doc)
		self.assertEqual(
			set_value.call_args.args[2],
			{
				"custom_has_delivery_note": 1,
				"custom_delivery_note_supplier_count": 1,
				"custom_delivery_note_supplier_total": 2,
			},
		)
		doc.delivery_notes.append(frappe._dict(supplier="B", delivery_note_file="three.pdf"))
		sync_order_details(doc)
		self.assertEqual(set_value.call_args.args[2]["custom_delivery_note_supplier_count"], 2)

	@patch("erpnext.accounts.supplier_requisites_validation.validate_supplier_requisites")
	@patch("erpnext.accounts.supplier_requisites_validation.frappe.get_doc")
	def test_vat_false_is_saved_and_payment_documents_cannot_update(self, get_doc, validate):
		doc = MagicMock(doctype="Purchase Invoice")
		doc.is_new.return_value = False
		supplier = MagicMock()
		get_doc.side_effect = [doc, supplier]
		validate.return_value = {"applicable": True, "supplier": "SUP-A", "checks": []}
		result = update_supplier_requisites_from_pdf({}, {"is_vat_payer": 0})
		self.assertEqual(result["updated"], {"is_vat_payer": 0})
		supplier.check_permission.assert_called_once_with("write")
		supplier.save.assert_called_once()
		for doctype in ("Payment Request", "Payment Entry"):
			doc.doctype = doctype
			get_doc.side_effect = [doc]
			with self.assertRaises(frappe.ValidationError):
				update_supplier_requisites_from_pdf({}, {"is_vat_payer": 1})
