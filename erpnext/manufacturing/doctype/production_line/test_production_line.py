from unittest.mock import patch

import frappe

from erpnext.manufacturing.doctype.production_line.production_line import ProductionLine, _plan_rows
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


class TestReleasedOrdersAreReadOnly(ERPNextTestSuite):
	def validate(self, saved, now):
		doc = ProductionLine.__new__(ProductionLine)
		doc.__dict__.update(name="L1", orders=now, flags=frappe._dict(), __islocal=0)
		with (
			patch.object(ProductionLine, "is_new", return_value=False),
			patch.object(frappe, "get_all", return_value=saved),
		):
			doc._validate_orders()

	def released(self, **changes):
		row = dict(name="r1", item_code="A", workplace="W1", qty=10, work_order="WO-1", idx=1)
		return frappe._dict({**row, **changes})

	def test_untouched_released_order_passes(self):
		self.validate([self.released()], [self.released()])

	def test_released_order_cannot_be_removed(self):
		with self.assertRaises(frappe.ValidationError):
			self.validate([self.released()], [])

	def test_released_order_cannot_change(self):
		for change in ({"qty": 11}, {"item_code": "B"}, {"workplace": "W2"}, {"work_order": None}):
			with self.assertRaises(frappe.ValidationError):
				self.validate([self.released()], [self.released(**change)])
