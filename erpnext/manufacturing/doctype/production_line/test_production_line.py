import frappe

from erpnext.manufacturing.doctype.production_line.production_line import _plan_rows
from erpnext.tests.utils import ERPNextTestSuite


def line(mode):
	return frappe._dict(
		planning_mode=mode,
		plan=[frappe._dict(enabled=1, item_code="Daily Item", workplace="W1", daily_qty=5)],
		orders=[
			frappe._dict(item_code="Ordered Item", workplace="W1", qty=100),
			frappe._dict(item_code="Other Item", workplace="W2", qty=10),
		],
	)


class TestProductionLinePlanning(ERPNextTestSuite):
	def test_daily_line_plans_from_the_daily_plan(self):
		self.assertEqual([row.item_code for row in _plan_rows(line("Daily Planning"))], ["Daily Item"])

	def test_line_saved_before_planning_modes_is_daily(self):
		self.assertEqual([row.item_code for row in _plan_rows(line(None))], ["Daily Item"])

	def test_manual_line_plans_from_its_orders(self):
		rows = _plan_rows(line("Manual Planning"))
		self.assertEqual([row.item_code for row in rows], ["Ordered Item", "Other Item"])

	def test_manual_orders_are_filtered_by_workplace_and_item(self):
		manual = line("Manual Planning")
		self.assertEqual([row.item_code for row in _plan_rows(manual, workplace="W2")], ["Other Item"])
		self.assertEqual(
			[row.item_code for row in _plan_rows(manual, item_code="Ordered Item")], ["Ordered Item"]
		)
