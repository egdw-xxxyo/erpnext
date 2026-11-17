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
