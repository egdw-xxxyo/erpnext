import json

from frappe.tests.utils import FrappeTestCase

from erpnext.devices.label_ai import TOOLS, Session


class TestLabelAITools(FrappeTestCase):
	def _session(self, **draft):
		events = []
		return Session("Test", {"inputs": [], **draft}, lambda **p: events.append(p)), events

	def test_tools_match_handlers(self):
		s, _ = self._session()
		for tool in TOOLS:
			if tool["name"] in ("get_doctype_fields", "get_documents"):
				continue
			self.assertTrue(hasattr(s, "tool_" + tool["name"]), tool["name"])

	def test_edit_validates_and_publishes_draft(self):
		s, events = self._session(editor_mode="Visual")
		layout = {"v": 1, "elements": [{"type": "text", "x": 1, "y": 1, "w": 10, "h": 5, "text": "Hi"}]}
		out, err = s.execute("edit_label_template", {"layout_json": layout})
		self.assertFalse(err, out)
		self.assertEqual(json.loads(s.draft["layout_json"])["elements"][0]["text"], "Hi")
		self.assertEqual(events[-1]["type"], "draft")
		self.assertTrue(s.changed)

	def test_edit_rejects_bad_layout_and_fields(self):
		s, _ = self._session()
		_out, err = s.execute("edit_label_template", {"layout_json": {"elements": [{"type": "script"}]}})
		self.assertTrue(err)
		_out, err = s.execute("edit_label_template", {"name": "x"})
		self.assertTrue(err)
		_out, err = s.execute("edit_label_template", {"inputs": [{"fieldname": "a b", "label": "A"}]})
		self.assertTrue(err)
		self.assertFalse(s.changed)


class TestLabelAIDataTools(FrappeTestCase):
	def _session(self, **draft):
		layout = {"v": 1, "elements": []}
		base = {
			"editor_mode": "Visual",
			"layout_json": json.dumps(layout),
			"inputs": [],
			"preview_data": '{"name": "X1", "qty": 3}',
		}
		return Session("Test", {**base, **draft}, lambda **p: None)

	def test_set_data_setup_reports_values_and_errors(self):
		s = self._session()
		out, err = s.execute(
			"set_data_setup",
			{
				"setup": '{# two #}{% set double = doc.qty * 2 %}{% set _ = doc.update({"tag": "T-" ~ doc.name}) %}'
			},
		)
		self.assertFalse(err, out)
		test = json.loads(out)["test"]
		self.assertEqual(test["doc_changes"], {"tag": "T-X1"})
		self.assertEqual(test["variables"]["double"], 6)
		self.assertIsNone(test["error"])
		out, err = s.execute("test_data_setup", {})
		self.assertEqual(json.loads(out)["doc_changes"], {"tag": "T-X1"})

		out, _err = s.execute("set_data_setup", {"setup": "{% set x = %}"})
		self.assertTrue(json.loads(out)["test"]["error"])

	def test_element_tools(self):
		s = self._session()
		out, err = s.execute(
			"add_label_elements",
			{"elements": [{"type": "field", "field": "name", "x": 0, "y": 0, "w": 20, "h": 5}]},
		)
		self.assertFalse(err, out)
		el_id = json.loads(out)["added"][0]
		out, err = s.execute("update_label_element", {"id": el_id, "changes": {"x": 5, "style": {"bold": 1}}})
		self.assertFalse(err, out)
		el = json.loads(s.draft["layout_json"])["elements"][0]
		self.assertEqual((el["x"], el["style"]["bold"]), (5, 1))
		s.execute("remove_label_elements", {"ids": [el_id]})
		self.assertEqual(json.loads(s.draft["layout_json"])["elements"], [])

	def test_add_print_input_replaces_by_fieldname(self):
		s = self._session()
		s.execute("add_print_input", {"fieldname": "qty", "label": "Qty", "fieldtype": "Int"})
		s.execute(
			"add_print_input", {"fieldname": "qty", "label": "Quantity", "fieldtype": "Int", "reqd": True}
		)
		self.assertEqual(
			[(r["fieldname"], r["label"], r["reqd"]) for r in s.draft["inputs"]], [("qty", "Quantity", 1)]
		)


class TestLabelAIPastedImages(FrappeTestCase):
	def test_only_last_image_turns_keep_pixels(self):
		from erpnext.devices.label_ai import _clean_history

		img = {"media_type": "image/png", "data": "iVBORw0KGgo=", "name": "a.png"}
		raw = [
			{"role": "user", "content": "one", "images": [img]},
			{"role": "assistant", "content": "ok"},
			{"role": "user", "content": "two", "images": [img]},
			{"role": "assistant", "content": "ok"},
			{"role": "user", "content": "three", "images": [img, {"media_type": "text/html", "data": "x"}]},
		]
		history, pasted = _clean_history(raw)
		self.assertEqual(len(pasted), 3)
		kinds = [[b["type"] for b in m["content"]] for m in history if isinstance(m["content"], list)]
		self.assertNotIn("image", kinds[0])
		self.assertIn("image", kinds[1])
		self.assertIn("image", kinds[2])
