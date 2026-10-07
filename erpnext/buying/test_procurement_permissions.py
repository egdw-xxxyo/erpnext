from unittest import TestCase
from unittest.mock import patch

import frappe

from erpnext.accounts.payment_fiscal_receipt import (
	RECEIPT_ADDED,
	RECEIPT_STATUS_FIELD,
	RECEIPT_URL_FIELD,
	_update_payment_request_receipt_status,
)
from erpnext.accounts.payment_request_permissions import (
	get_permission_query_conditions,
)
from erpnext.accounts.payment_request_permissions import (
	has_permission as has_payment_request_permission,
)
from erpnext.buying.procurement_workflow import (
	BUYER_CREATE_PERMISSIONS,
	BUYER_OWNED_DOCTYPES,
	BUYER_OWNER_PERMISSIONS,
	BUYER_ROLE,
	DOCTYPE_PERMISSIONS,
)


class TestProcurementPermissions(TestCase):
	def test_buyer_mutating_permissions_are_limited_to_owned_procurement_documents(self):
		for doctype in BUYER_OWNED_DOCTYPES:
			self.assertEqual(DOCTYPE_PERMISSIONS[doctype][BUYER_ROLE], BUYER_CREATE_PERMISSIONS)
		for doctype in ("Supplier", "Bank Account", "Bank"):
			self.assertNotIn(doctype, BUYER_OWNED_DOCTYPES)
			self.assertTrue(
				{"read", "create", "write", "delete"}.issubset(DOCTYPE_PERMISSIONS[doctype][BUYER_ROLE])
			)
		self.assertIn("write", BUYER_OWNER_PERMISSIONS)
		self.assertIn("delete", BUYER_OWNER_PERMISSIONS)
		self.assertNotIn("write", BUYER_CREATE_PERMISSIONS)
		self.assertNotIn("delete", BUYER_CREATE_PERMISSIONS)

	@patch("erpnext.accounts.payment_request_permissions.frappe.get_roles")
	def test_department_head_can_view_all_payment_requests(self, get_roles):
		get_roles.return_value = ["Payments: Керівник підрозділу"]

		self.assertEqual(get_permission_query_conditions("manager@example.invalid"), "")
		self.assertTrue(
			has_payment_request_permission(
				frappe._dict(name="PAY-REQ-1", owner="another@example.invalid"),
				ptype="write",
				user="manager@example.invalid",
			)
		)

	@patch("erpnext.accounts.payment_fiscal_receipt.frappe")
	def test_payment_request_keeps_latest_instruction_link(self, mocked_frappe):
		mocked_frappe.get_all.side_effect = [
			["PAY-ENTRY-1"],
			[frappe._dict(custom_fiscal_receipt="/private/files/instruction.pdf")],
		]
		mocked_frappe.db.get_value.return_value = "Paid"
		mocked_frappe.db.has_column.return_value = True

		_update_payment_request_receipt_status("PAY-REQ-1")

		mocked_frappe.db.set_value.assert_called_once_with(
			"Payment Request",
			"PAY-REQ-1",
			{
				RECEIPT_STATUS_FIELD: RECEIPT_ADDED,
				RECEIPT_URL_FIELD: "/private/files/instruction.pdf",
			},
			update_modified=False,
		)
