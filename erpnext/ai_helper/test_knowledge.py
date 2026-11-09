import frappe
from frappe.tests import IntegrationTestCase

from erpnext.ai_helper import knowledge, tools

DOCTYPE = "Sales Order"


class TestAIKnowledge(IntegrationTestCase):
	def tearDown(self):
		frappe.db.delete(knowledge.TYPE)
		frappe.db.delete(knowledge.SOLUTION)

	def test_signature_ignores_values(self):
		a = knowledge.signature(DOCTYPE, 'Item <b>"ABC-001"</b> has no stock in warehouse "Main - X" (5 pcs)')
		b = knowledge.signature(
			DOCTYPE, 'Item <b>"ZZZ-777"</b> has no stock in warehouse "Other - Y" (12 pcs)'
		)
		self.assertEqual(a, b)

	def test_signature_differs_by_doctype_and_text(self):
		self.assertNotEqual(
			knowledge.signature(DOCTYPE, "Stock is missing")[0],
			knowledge.signature(None, "Stock is missing")[0],
		)
		self.assertNotEqual(
			knowledge.signature(DOCTYPE, "Stock is missing")[0],
			knowledge.signature(DOCTYPE, "Price is missing")[0],
		)

	def test_traceback_uses_last_line(self):
		trace = "Traceback (most recent call last):\n  File x\nValueError: bad value 12"
		self.assertEqual(knowledge.normalize(trace), "ValueError: bad value #")

	def test_lookup_counts_and_lists_solutions(self):
		context = {"error": "Stock is missing for 5 items", "doctype": DOCTYPE}
		first = knowledge.lookup(context)
		self.assertEqual(first["solutions"], [])
		knowledge.add_solution(first["type"], "Перевірте залишок на складі.")
		second = knowledge.lookup({"error": "Stock is missing for 9 items", "doctype": DOCTYPE})
		self.assertEqual(second["type"], first["type"])
		self.assertEqual(len(second["solutions"]), 1)
		self.assertEqual(frappe.db.get_value(knowledge.TYPE, first["type"], "occurrences"), 2)

	def test_wrong_solution_hidden_and_sent_to_ai(self):
		error_type = knowledge.lookup({"error": "Stock is missing", "doctype": DOCTYPE})["type"]
		name = knowledge.add_solution(error_type, "Видаліть документ.")
		knowledge.rate(error_type, name, "wrong")
		self.assertEqual(knowledge.lookup({"error": "Stock is missing", "doctype": DOCTYPE})["solutions"], [])
		block = knowledge.knowledge_block(error_type)
		self.assertIn("WRONG", block)
		self.assertIn("Видаліть документ.", block)

	def test_similar_solution_is_merged(self):
		error_type = knowledge.lookup({"error": "Stock is missing", "doctype": DOCTYPE})["type"]
		first = knowledge.add_solution(error_type, "Перевірте залишок на складі та повторіть.")
		second = knowledge.add_solution(error_type, "Перевірте залишок на складі та повторіть!")
		self.assertEqual(first, second)
		self.assertEqual(len(knowledge._solutions(error_type)), 1)

	def test_active_cap(self):
		error_type = knowledge.lookup({"error": "Stock is missing", "doctype": DOCTYPE})["type"]
		for i in range(knowledge.MAX_ACTIVE + 2):
			knowledge.add_solution(error_type, f"Крок {i}: " + "абвгд" * (i + 1) * 3)
		self.assertLessEqual(len(knowledge._solutions(error_type, "Active")), knowledge.MAX_ACTIVE)

	def test_rate_rejects_foreign_solution(self):
		a = knowledge.lookup({"error": "First error", "doctype": DOCTYPE})["type"]
		b = knowledge.lookup({"error": "Second error", "doctype": DOCTYPE})["type"]
		name = knowledge.add_solution(a, "Рішення.")
		with self.assertRaises(frappe.ValidationError):
			knowledge.rate(b, name, "wrong")

	def test_logic_tool_returns_controller_source(self):
		logic = tools.get_doctype_logic(DOCTYPE)
		self.assertIn("validate", logic["controller"])

	def test_logic_tool_hides_scripts_without_permission(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				tools.get_doctype_logic(DOCTYPE)
		finally:
			frappe.set_user("Administrator")
