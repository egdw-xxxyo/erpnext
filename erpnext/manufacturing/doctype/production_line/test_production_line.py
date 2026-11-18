from unittest.mock import patch

import frappe

from erpnext.manufacturing.doctype.production_line.production_line import (
	ProductionLine,
	_plan_rows,
	max_producible,
)
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


class TestOrderFitsStock(ERPNextTestSuite):
	def rows(self, *pairs):
		return [frappe._dict(per_unit=per_unit, free=free) for per_unit, free in pairs]

	def test_scarcest_component_decides(self):
		self.assertEqual(max_producible(self.rows((2, 1000), (1, 51), (0.5, 100))), 51)

	def test_fractional_need_rounds_down_to_whole_units(self):
		self.assertEqual(max_producible(self.rows((0.3, 1))), 3)
		self.assertEqual(max_producible(self.rows((0.1, 0.3))), 3)

	def test_negative_free_stock_means_nothing(self):
		self.assertEqual(max_producible(self.rows((1, -5), (1, 10))), 0)

	def test_no_components_has_no_limit(self):
		self.assertIsNone(max_producible([]))


class TestAllowedItems(ERPNextTestSuite):
	def validate(self, allowed, orders=(), plan=(), critical=()):
		doc = ProductionLine.__new__(ProductionLine)
		doc.__dict__.update(
			allowed_items=[frappe._dict(item_code=code) for code in allowed],
			critical_stock=[frappe._dict(item_code=code) for code in critical],
			orders=[
				frappe._dict(idx=i + 1, item_code=code, work_order=None) for i, code in enumerate(orders)
			],
			plan=[frappe._dict(idx=i + 1, item_code=code) for i, code in enumerate(plan)],
		)
		doc._validate_allowed_items()

	def test_empty_list_allows_any_item(self):
		self.validate([], orders=["X"], plan=["Y"])

	def test_allowed_item_passes(self):
		self.validate(["A"], orders=["A"], plan=["A"])

	def test_order_outside_list_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.validate(["A"], orders=["B"])

	def test_plan_outside_list_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.validate(["A"], plan=["B"])

	def test_duplicates_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.validate(["A", "A"])
		with self.assertRaises(frappe.ValidationError):
			self.validate(["A"], critical=["C", "C"])
