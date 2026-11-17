import json

from frappe.tests.utils import FrappeTestCase

from erpnext.devices.label_layout import compile_layout


class TestLabelLayout(FrappeTestCase):
	def test_text_is_escaped_but_placeholders_kept(self):
		html = compile_layout(
			{
				"elements": [
					{"type": "text", "x": 1, "y": 1, "w": 10, "h": 5, "text": "<b>{{ doc.name }} {% x %}"}
				]
			}
		)
		self.assertIn("&lt;b&gt;", html)
		self.assertIn("{{ doc.name }}", html)
		self.assertNotIn("{% x %}", html)

	def test_field_and_input_render(self):
		import frappe

		layout = {
			"elements": [
				{"type": "field", "x": 0, "y": 0, "w": 10, "h": 5, "field": "serial_no", "prefix": "SN "},
				{"type": "input", "x": 0, "y": 5, "w": 10, "h": 5, "input": "operator"},
			]
		}
		out = frappe.render_template(
			compile_layout(json.dumps(layout)), {"doc": frappe._dict(serial_no="A<1", operator="Ivan")}
		)
		self.assertIn("SN A&lt;1", out)
		self.assertIn("Ivan", out)

	def test_table_loop(self):
		import frappe

		layout = {
			"elements": [
				{
					"type": "table",
					"x": 0,
					"y": 0,
					"w": 40,
					"h": 10,
					"cols": [20, 20],
					"loop": "items",
					"rows": [
						{"cells": [{"text": "Item"}, {"text": "Qty"}]},
						{"cells": [{"text": "{{ row.item_code }}"}, {"text": "{{ row.qty }}"}]},
					],
				}
			]
		}
		out = frappe.render_template(
			compile_layout(layout),
			{"doc": frappe._dict(items=[{"item_code": "X1", "qty": 3}, {"item_code": "X2", "qty": 4}])},
		)
		self.assertIn("X1", out)
		self.assertIn("X2", out)

	def test_rejects_bad_names_and_types(self):
		with self.assertRaises(Exception):
			compile_layout({"elements": [{"type": "field", "field": "a}}{{x"}]})
		with self.assertRaises(Exception):
			compile_layout({"elements": [{"type": "script"}]})
