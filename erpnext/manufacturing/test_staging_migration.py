import frappe

from erpnext.manufacturing import staging_migration
from erpnext.tests.utils import ERPNextTestSuite


class TestStagingMigration(ERPNextTestSuite):
	def test_line_items_come_from_the_plan_and_the_orders(self):
		line = frappe._dict(
			plan=[frappe._dict(item_code="B"), frappe._dict(item_code="A")],
			orders=[frappe._dict(item_code="A"), frappe._dict(item_code="C")],
		)
		self.assertEqual(staging_migration._line_items(line), ["A", "B", "C"])

	def test_count_by_warehouse(self):
		rows = [frappe._dict(warehouse="X"), frappe._dict(warehouse="X"), frappe._dict(warehouse="Y")]
		self.assertEqual(staging_migration._count_by(rows), {"X": 2, "Y": 1})
