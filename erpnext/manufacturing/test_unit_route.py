from unittest.mock import patch

import frappe

from erpnext.manufacturing import unit_route
from erpnext.tests.utils import ERPNextTestSuite


def step(idx, operation, enters_stock=0):
	return frappe._dict(
		idx=idx, operation=operation, workstation=None, enters_stock=enters_stock, unit_target_warehouse=None
	)


class TestUnitRoute(ERPNextTestSuite):
	def test_steps_after_the_marked_one_are_after_stock(self):
		rows = [step(1, "Bench"), step(2, "QC", 1), step(3, "Packing")]
		with patch.object(frappe, "get_all", return_value=rows):
			result = unit_route.route("BOM-X")
		self.assertEqual([row["after_stock"] for row in result], [False, False, True])
		self.assertEqual(unit_route.stock_step("BOM-X").operation, "QC")

	def test_bom_without_a_marked_step_has_no_after_stock_steps(self):
		rows = [step(1, "Bench"), step(2, "Packing")]
		with patch.object(frappe, "get_all", return_value=rows):
			self.assertFalse(any(row["after_stock"] for row in unit_route.route("BOM-X")))
			self.assertIsNone(unit_route.stock_step("BOM-X"))

	def test_two_marked_steps_are_refused(self):
		doc = frappe._dict(operations=[step(1, "Bench", 1), step(2, "QC", 1)])
		self.assertRaises(frappe.ValidationError, unit_route.validate_bom, doc)

	def test_work_order_drops_steps_after_stock_and_renumbers(self):
		rows = [step(1, "Bench"), step(2, "QC", 1), step(3, "Packing")]
		wo_rows = [
			frappe._dict(idx=1, operation="Bench", bom="BOM-X"),
			frappe._dict(idx=2, operation="QC", bom="BOM-X"),
			frappe._dict(idx=3, operation="Packing", bom="BOM-X"),
		]

		class Doc(frappe._dict):
			def set(self, key, value):
				self[key] = value

		doc = Doc(docstatus=0, bom_no="BOM-X", operations=wo_rows)
		with patch.object(frappe, "get_all", return_value=rows):
			unit_route.drop_after_stock_operations(doc)
		self.assertEqual([row.operation for row in doc.operations], ["Bench", "QC"])
