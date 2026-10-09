import frappe

from erpnext.manufacturing.consumption import compute, evaluate, preview
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
