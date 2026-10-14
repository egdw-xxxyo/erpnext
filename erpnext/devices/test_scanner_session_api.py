from unittest.mock import patch

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
