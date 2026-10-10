import frappe

from erpnext.manufacturing.consumption import compute, consume, evaluate, find_consumption, preview
from erpnext.stock.doctype.item.test_item import make_item
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from erpnext.stock.stock_ledger import NegativeStockError
from erpnext.tests.utils import ERPNextTestSuite


class TestConsumptionRecipe(ERPNextTestSuite):
	def test_formula_follows_the_quantity(self):
		self.assertEqual(evaluate("units", {"units": 3}), 3)
		self.assertEqual(evaluate("ceil(units / 2)", {"units": 3}), 2)

	def test_condition_leaves_a_row_out(self):
		rows = [
			{"item_code": "Box", "qty_formula": "1"},
			{"item_code": "Foam", "qty_formula": "units", "condition": "units >= 3"},
		]
		self.assertEqual([r["item_code"] for r in compute(rows, {"units": 2})], ["Box"])
		self.assertEqual([r["item_code"] for r in compute(rows, {"units": 3})], ["Box", "Foam"])

	def test_last_box_of_an_order_uses_the_remainder(self):
		rows = [
			{"item_code": "Box", "qty_formula": "1"},
			{"item_code": "Insert", "qty_formula": "units"},
		]
		result = preview(rows, "4, 3")
		by_item = {row["item_code"]: row["qty"] for row in result["rows"]}
		self.assertEqual(by_item["Box"], {4: 1, 3: 1})
		self.assertEqual(by_item["Insert"], {4: 4, 3: 3})

	def test_formula_cannot_reach_python(self):
		with self.assertRaises(Exception):
			evaluate("__import__('os').getcwd()", {"units": 1})

	def test_bad_formula_is_refused_on_save(self):
		recipe = frappe.get_doc(
			{
				"doctype": "Consumption Recipe",
				"recipe_name": "_Test Bad Recipe",
				"items": [{"item_code": "_Test Item", "qty_formula": "units +"}],
			}
		)
		self.assertRaises(frappe.ValidationError, recipe.insert)


class TestConsume(ERPNextTestSuite):
	def setUp(self):
		self.company = frappe.db.get_single_value("Global Defaults", "default_company")
		self.warehouse = frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": "Consume Test " + frappe.generate_hash(length=6),
				"company": self.company,
			}
		).insert()
		self.box = make_item(properties={"is_stock_item": 1}).name
		self.foam = make_item(properties={"is_stock_item": 1}).name
		self.recipe = frappe.get_doc(
			{
				"doctype": "Consumption Recipe",
				"recipe_name": "Consume Test " + frappe.generate_hash(length=6),
				"items": [
					{"item_code": self.box, "qty_formula": "1"},
					{"item_code": self.foam, "qty_formula": "units", "condition": "units >= 3"},
				],
			}
		).insert()

	def stock_up(self, qty=100):
		for item in (self.box, self.foam):
			make_stock_entry(item_code=item, qty=qty, to_warehouse=self.warehouse.name, rate=1)

	def source(self):
		return "Test Source " + frappe.generate_hash(length=6)

	def test_issues_what_the_recipe_says_for_the_units(self):
		self.stock_up()
		entry = consume(
			self.recipe.name, {"units": 3}, "Warehouse", self.source(), warehouse=self.warehouse.name
		)
		self.assertEqual(entry.docstatus, 1)
		self.assertEqual({row.item_code: row.qty for row in entry.items}, {self.box: 1, self.foam: 3})

	def test_condition_leaves_foam_out_of_a_small_box(self):
		self.stock_up()
		entry = consume(
			self.recipe.name, {"units": 2}, "Warehouse", self.source(), warehouse=self.warehouse.name
		)
		self.assertEqual([row.item_code for row in entry.items], [self.box])

	def test_second_call_for_the_same_source_posts_nothing(self):
		self.stock_up()
		source = self.source()
		first = consume(self.recipe.name, {"units": 3}, "Warehouse", source, warehouse=self.warehouse.name)
		second = consume(self.recipe.name, {"units": 3}, "Warehouse", source, warehouse=self.warehouse.name)
		self.assertEqual(first.name, second.name)
		self.assertEqual(
			frappe.db.count("Stock Entry", {"consumption_source_name": source, "docstatus": 1}), 1
		)

	def test_cancelling_the_source_cancels_the_consumption(self):
		self.stock_up()
		transfer = make_stock_entry(
			item_code=self.box,
			qty=1,
			from_warehouse=self.warehouse.name,
			to_warehouse=self.warehouse.name,
			rate=1,
		)
		entry = consume(
			self.recipe.name, {"units": 1}, "Stock Entry", transfer.name, warehouse=self.warehouse.name
		)
		transfer.cancel()
		self.assertEqual(frappe.db.get_value("Stock Entry", entry.name, "docstatus"), 2)
		self.assertIsNone(find_consumption("Stock Entry", transfer.name))

	def test_shortage_blocks_and_leaves_nothing_behind(self):
		source = self.source()
		with self.assertRaises(NegativeStockError):
			consume(self.recipe.name, {"units": 3}, "Warehouse", source, warehouse=self.warehouse.name)
		self.assertIsNone(find_consumption("Warehouse", source))

	def test_shortage_can_leave_a_draft_instead(self):
		source = self.source()
		entry = consume(
			self.recipe.name,
			{"units": 3},
			"Warehouse",
			source,
			warehouse=self.warehouse.name,
			on_shortage="draft",
		)
		self.assertEqual(entry.docstatus, 0)
		self.assertEqual(find_consumption("Warehouse", source), entry.name)

	def test_recipe_that_comes_to_nothing_posts_nothing(self):
		recipe = frappe.get_doc(
			{
				"doctype": "Consumption Recipe",
				"recipe_name": "Consume Test Empty " + frappe.generate_hash(length=6),
				"items": [{"item_code": self.foam, "qty_formula": "units", "condition": "units > 10"}],
			}
		).insert()
		self.assertIsNone(
			consume(recipe.name, {"units": 2}, "Warehouse", self.source(), warehouse=self.warehouse.name)
		)
