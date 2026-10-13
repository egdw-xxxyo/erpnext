from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from erpnext.buying.procurement_item_likes import preserve_item_likes, set_item_like


class TestProcurementItemLikes(TestCase):
	@patch("erpnext.buying.procurement_item_likes.frappe.db.set_value")
	@patch("erpnext.buying.procurement_item_likes.frappe.get_doc")
	def test_like_only_updates_the_selected_child_without_saving_order(self, get_doc, set_value):
		order = get_doc.return_value
		order.get.return_value = [frappe._dict(name="ROW-A")]
		self.assertEqual(set_item_like("ORDER-A", "ROW-A", True), 1)
		order.check_permission.assert_called_once_with("write")
		order.save.assert_not_called()
		set_value.assert_called_once_with(
			"Consolidated Purchase Order Item", "ROW-A", "custom_item_liked", 1, update_modified=False
		)

	@patch("erpnext.buying.procurement_item_likes.frappe.db.set_value")
	@patch("erpnext.buying.procurement_item_likes.frappe.get_doc")
	def test_read_only_user_cannot_change_like(self, get_doc, set_value):
		get_doc.return_value.check_permission.side_effect = frappe.PermissionError
		with self.assertRaises(frappe.PermissionError):
			set_item_like("ORDER-A", "ROW-A", True)
		set_value.assert_not_called()

	@patch("erpnext.buying.procurement_item_likes.frappe.throw", side_effect=frappe.ValidationError)
	@patch("erpnext.buying.procurement_item_likes.frappe.db.set_value")
	@patch("erpnext.buying.procurement_item_likes.frappe.get_doc")
	def test_cannot_like_a_row_from_another_order(self, get_doc, set_value, throw):
		get_doc.return_value.get.return_value = [frappe._dict(name="ROW-A")]
		with self.assertRaises(frappe.ValidationError):
			set_item_like("ORDER-A", "ROW-B", True)
		set_value.assert_not_called()

	@patch("erpnext.buying.procurement_item_likes.frappe.get_all")
	def test_regular_save_preserves_concurrent_likes_and_new_row_values(self, get_all):
		get_all.return_value = [frappe._dict(name="ROW-A", custom_item_liked=1)]
		existing, new = MagicMock(), MagicMock()
		existing.name, new.name = "ROW-A", "NEW-ROW"
		order = MagicMock()
		order.is_new.return_value = False
		order.get.return_value = [existing, new]
		preserve_item_likes(order)
		existing.set.assert_called_once_with("custom_item_liked", 1)
		new.set.assert_not_called()
