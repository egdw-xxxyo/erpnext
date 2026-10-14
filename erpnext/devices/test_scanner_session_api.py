from unittest.mock import patch

import frappe

from erpnext.devices import scanner_session_api as api
from erpnext.tests.utils import ERPNextTestSuite


class TestLinkFilterRoomForPacking(ERPNextTestSuite):
	def test_plain_filters_pass_through(self):
		filters = {"docstatus": 1}
		self.assertEqual(api._resolve_link_filters("Sales Order", filters), {"docstatus": 1})

	def test_room_for_packing_becomes_a_name_list(self):
		with patch.object(api, "_orders_with_room_for_packing", return_value=["SO-1", "SO-2"]):
			resolved = api._resolve_link_filters("Sales Order", {"docstatus": 1, api.ROOM_FOR_PACKING: 1})
		self.assertEqual(resolved, {"docstatus": 1, "name": ["in", ["SO-1", "SO-2"]]})

	def test_no_orders_with_room_matches_nothing(self):
		with patch.object(api, "_orders_with_room_for_packing", return_value=[]):
			resolved = api._resolve_link_filters("Sales Order", {api.ROOM_FOR_PACKING: 1})
		self.assertEqual(api._names_of(resolved["name"]), {""})

	def test_other_doctypes_ignore_the_key(self):
		self.assertEqual(api._resolve_link_filters("Item", {api.ROOM_FOR_PACKING: 1}), {})


class TestScannerRelease(ERPNextTestSuite):
	def test_claim_needs_an_employee(self):
		with patch.object(api, "_session_employee", return_value=None):
			with self.assertRaises(frappe.PermissionError):
				api.claim_virtual_scanner()

	def test_workplace_is_required(self):
		with patch.object(api, "_assert_scanner_mine", return_value=frappe._dict(name="S-1", workplace=None)):
			with self.assertRaises(frappe.ValidationError):
				api.set_scanner_workplace("S-1", None)

	def test_forget_clears_assignment_and_state(self):
		row = frappe._dict(name="S-1", scanner_name="S-1")
		with (
			patch.object(api, "_assert_scanner_mine", return_value=row),
			patch.object(api, "_owner_user", return_value="u@x.com"),
			patch.object(api, "_scanner_row", return_value=row),
			patch.object(api, "_read_session", return_value={}),
			patch.object(api, "_publish_session_update"),
			patch.object(api, "_drop_session") as drop,
			patch.object(api.frappe.db, "set_value") as set_value,
		):
			api.forget_scanner("S-1")
		set_value.assert_called_once_with("Scanner", "S-1", {"employee": None, "workplace": None})
		drop.assert_called_once_with("S-1")
