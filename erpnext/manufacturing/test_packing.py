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

	def test_marked_step_with_a_warehouse_is_enough_to_stage(self):
		route = [step(1, 1, "Staging - X")]
		with patch.object(packing.unit_route, "route", return_value=route):
			self.assertEqual(packing.landing_warehouse("BOM-X"), "Staging - X")

	def test_no_staging_without_a_marked_step_or_a_warehouse(self):
		with patch.object(packing.unit_route, "route", return_value=[step(1), step(2)]):
			self.assertIsNone(packing.landing_warehouse("BOM-X"))
		with patch.object(packing.unit_route, "route", return_value=[step(1, 1)]):
			self.assertIsNone(packing.landing_warehouse("BOM-X"))
		self.assertIsNone(packing.landing_warehouse(None))

	def test_pack_target_falls_back_to_the_lines_packaging_workplace(self):
		with (
			patch.object(packing.unit_route, "route", return_value=[step(1, 1, "Staging - X")]),
			patch.object(packing, "line_pack_target", return_value="Finished - X") as target,
		):
			self.assertEqual(packing.pack_target("BOM-X", "Line", "Bench"), "Finished - X")
			target.assert_called_once_with("Line", "Bench")

	def test_pack_target_prefers_a_step_after_stock(self):
		with patch.object(packing.unit_route, "route", return_value=ROUTE):
			self.assertEqual(packing.pack_target("BOM-X", "Line"), "Finished - X")

	def test_line_pack_target_is_the_packaging_bench_then_the_finished_goods(self):
		rows = [frappe._dict(target_warehouse=None), frappe._dict(target_warehouse="Bench WH - X")]
		with patch.object(frappe, "get_all", return_value=rows):
			self.assertEqual(packing.line_pack_target("Line"), "Bench WH - X")
		with (
			patch.object(frappe, "get_all", return_value=[]),
			patch.object(frappe.db, "get_value", return_value="FG - X"),
		):
			self.assertEqual(packing.line_pack_target("Line"), "FG - X")
		self.assertIsNone(packing.line_pack_target(None))

	def test_a_workplace_that_does_not_pack_is_refused(self):
		with patch.object(frappe, "get_all", return_value=[]):
			self.assertRaises(frappe.ValidationError, packing._check_packing_workplace, "Bench")
		self.assertIsNone(packing._check_packing_workplace(None))

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
