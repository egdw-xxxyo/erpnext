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

	def test_job_workplace_defaults_to_the_only_packaging_bench_of_the_line(self):
		with patch.object(frappe, "get_all", return_value=["Bench"]):
			self.assertEqual(packing._only_packaging_workplace("Line"), "Bench")
		with patch.object(frappe, "get_all", return_value=["Bench", "Other"]):
			self.assertIsNone(packing._only_packaging_workplace("Line"))
		self.assertIsNone(packing._only_packaging_workplace(None))


class TestReturnToStaging(ERPNextTestSuite):
	def test_return_target_is_the_lines_wip_warehouse(self):
		def value(doctype, name, fields=None, *args, **kwargs):
			if doctype == "Serial No":
				return "WO-1"
			if doctype == "Work Order":
				return ("Line A", "BOM-1")
			return "Wip - X"

		with patch.object(packing.frappe.db, "get_value", side_effect=value):
			self.assertEqual(packing.return_target("SN-1"), "Wip - X")

	def test_return_target_falls_back_to_the_bom_landing(self):
		def value(doctype, name, fields=None, *args, **kwargs):
			if doctype == "Serial No":
				return "WO-1"
			if doctype == "Work Order":
				return ("Line A", "BOM-1")
			return None

		with (
			patch.object(packing.frappe.db, "get_value", side_effect=value),
			patch.object(packing, "landing_warehouse", return_value="Staging - X"),
		):
			self.assertEqual(packing.return_target("SN-1"), "Staging - X")

	def test_unit_without_a_work_order_has_no_return_target(self):
		with patch.object(packing.frappe.db, "get_value", return_value=None):
			self.assertIsNone(packing.return_target("SN-1"))

	def test_a_box_is_returned_by_cancelling_its_transfer(self):
		entry = frappe._dict(name="STE-1", flags=frappe._dict(), cancel=lambda: None)
		with (
			patch.object(
				packing, "_packing_job_of", return_value=frappe._dict(name="PJ-1", stock_entry="STE-1")
			),
			patch.object(packing.frappe, "get_all", return_value=["SN-1", "SN-2"]),
			patch.object(packing.frappe, "get_doc", return_value=entry),
			patch.object(packing, "_transfer") as transfer,
		):
			result = packing.return_units_to_staging(["SN-1", "SN-2"])
		self.assertEqual(result, {"cancelled": ["STE-1"], "moved": 0, "errors": []})
		transfer.assert_not_called()

	def test_a_job_with_other_units_is_not_cancelled(self):
		with (
			patch.object(
				packing, "_packing_job_of", return_value=frappe._dict(name="PJ-1", stock_entry="STE-1")
			),
			patch.object(packing.frappe, "get_all", return_value=["SN-1", "SN-2", "SN-3"]),
			patch.object(packing.frappe, "get_doc") as get_doc,
			patch.object(packing, "return_target", return_value=None),
		):
			result = packing.return_units_to_staging(["SN-1", "SN-2"])
		get_doc.assert_not_called()
		self.assertEqual(result["cancelled"], [])
