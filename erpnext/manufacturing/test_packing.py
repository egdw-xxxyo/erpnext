from unittest.mock import patch

import frappe

from erpnext.manufacturing import packing
from erpnext.tests.utils import ERPNextTestSuite


def step(idx, enters_stock=0, warehouse=None, after_stock=False):
	return frappe._dict(
		idx=idx,
		operation=f"Op{idx}",
		workstation=None,
		enters_stock=enters_stock,
		unit_target_warehouse=warehouse,
		after_stock=after_stock,
	)


ROUTE = [step(1), step(2, 1, "Staging - X"), step(3, 0, "Finished - X", True)]


class TestPacking(ERPNextTestSuite):
	def test_landing_is_the_staging_warehouse_of_the_marked_step(self):
		with patch.object(packing.unit_route, "route", return_value=ROUTE):
			self.assertEqual(packing.landing_warehouse("BOM-X"), "Staging - X")
			self.assertEqual(packing.pack_target("BOM-X"), "Finished - X")

	def test_no_route_means_no_staging(self):
		route = [step(1), step(2, 1, "Staging - X")]
		with patch.object(packing.unit_route, "route", return_value=route):
			self.assertIsNone(packing.landing_warehouse("BOM-X"))
		with patch.object(packing.unit_route, "route", return_value=[step(1), step(2)]):
			self.assertIsNone(packing.landing_warehouse("BOM-X"))
		self.assertIsNone(packing.landing_warehouse(None))

	def test_delivery_of_a_unit_in_staging_is_refused(self):
		doc = frappe._dict(items=[frappe._dict(serial_and_batch_bundle=None, serial_no="SN-1\nSN-2")])
		with (
			patch.object(packing, "staging_warehouses", return_value={"Staging - X"}),
			patch.object(frappe, "get_all", return_value=["SN-2"]),
		):
			self.assertRaises(frappe.ValidationError, packing.block_unpacked_delivery, doc)

	def test_delivery_of_packed_units_passes(self):
		doc = frappe._dict(items=[frappe._dict(serial_and_batch_bundle=None, serial_no="SN-1")])
		with (
			patch.object(packing, "staging_warehouses", return_value={"Staging - X"}),
			patch.object(frappe, "get_all", return_value=[]),
		):
			packing.block_unpacked_delivery(doc)

	def test_serial_list_accepts_json_and_lines(self):
		self.assertEqual(packing._serial_list('["A", "B", "A"]'), ["A", "B"])
		self.assertEqual(packing._serial_list("A\nB\n"), ["A", "B"])
