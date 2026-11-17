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


class TestLabelLayoutBlocks(FrappeTestCase):
	def _render(self, layout, **doc):
		import frappe

		return frappe.render_template(compile_layout(layout), {"doc": frappe._dict(doc)})

	def test_repeat_draws_a_block_per_item(self):
		out = self._render(
			{
				"elements": [
					{
						"type": "repeat",
						"x": 0,
						"y": 0,
						"w": 40,
						"h": 30,
						"list": "serials",
						"show": "text",
						"item_h": 5,
					}
				]
			},
			serials=["S1", "S2", "S3"],
		)
		self.assertEqual([s for s in ("S1", "S2", "S3") if s in out], ["S1", "S2", "S3"])
		self.assertIn("top:", out)

	def test_repeat_field_of_child_rows_and_limit(self):
		out = self._render(
			{
				"elements": [
					{
						"type": "repeat",
						"x": 0,
						"y": 0,
						"w": 40,
						"h": 30,
						"list": "items",
						"value": "serial_no",
						"show": "barcode",
						"max_items": 1,
					}
				]
			},
			items=[{"serial_no": "A1"}, {"serial_no": "A2"}],
		)
		self.assertIn('data="A1"', out)
		self.assertNotIn("A2", out)

	def test_column_styles_bold_and_superscript(self):
		html = compile_layout(
			{
				"elements": [
					{
						"type": "table",
						"x": 0,
						"y": 0,
						"w": 40,
						"h": 10,
						"cols": [10, 30],
						"col_styles": [{"font_size_pt": 5}, {"font_size_pt": 9}],
						"rows": [{"cells": [{"text": "a"}, {"text": "**b**^^tm^^"}]}],
					}
				]
			}
		)
		self.assertIn("font-size:21px", html)
		self.assertIn("font-size:38px", html)
		self.assertIn("<b>b</b>", html)
		self.assertIn("<sup", html)

	def test_show_if(self):
		layout = {
			"elements": [
				{"type": "text", "x": 0, "y": 0, "w": 9, "h": 5, "text": "HIDDEN", "show_if": "doc.flag"}
			]
		}
		self.assertNotIn("HIDDEN", self._render(layout))
		self.assertIn("HIDDEN", self._render(layout, flag=1))
		with self.assertRaises(Exception):
			compile_layout({"elements": [{"type": "text", "show_if": "x %}{{ y"}]})
