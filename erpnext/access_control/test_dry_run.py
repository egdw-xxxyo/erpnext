import json
import unittest
from types import SimpleNamespace

import frappe

from erpnext.access_control.dry_run import framework_supports_dry_run, parse_steps, simulate
from erpnext.access_control.impersonation import SESSION_KEY

SAVE = "frappe.desk.form.save.savedocs"
PROBE = "dry-run test probe"


def new_todo_step() -> dict:
	doc = {"doctype": "ToDo", "name": "new-todo-dry-run", "__islocal": 1, "description": PROBE}
	return {"method": SAVE, "args": {"doc": json.dumps(doc), "action": "Save"}}


class TestParseSteps(unittest.TestCase):
	def test_rejects_unknown_method(self):
		with self.assertRaises(frappe.ValidationError):
			parse_steps(json.dumps([{"method": "frappe.client.set_value", "args": {}}]))

	def test_rejects_empty(self):
		with self.assertRaises(frappe.ValidationError):
			parse_steps("[]")

	def test_keeps_method_and_args(self):
		self.assertEqual(parse_steps(json.dumps([new_todo_step()]))[0]["method"], SAVE)

	def test_encodes_nested_args_like_http(self):
		step = {"method": SAVE, "args": {"doc": {"doctype": "ToDo"}, "action": "Save"}}
		args = parse_steps(json.dumps([step]))[0]["args"]
		self.assertEqual(json.loads(args["doc"]), {"doctype": "ToDo"})
		self.assertEqual(args["action"], "Save")


class TestSimulate(unittest.TestCase):
	def setUp(self):
		self.request = getattr(frappe.local, "request", None)
		frappe.local.request = SimpleNamespace(method="POST", path="/api/method/simulate")
		frappe.session.data[SESSION_KEY] = {"by": "Administrator", "reason": "test", "since": ""}

	def tearDown(self):
		frappe.session.data.pop(SESSION_KEY, None)
		frappe.flags.dry_run = None
		frappe.flags.mute_emails = False
		frappe.flags.read_only = False
		frappe.local.request = self.request

	def test_framework_is_patched(self):
		self.assertTrue(framework_supports_dry_run())

	def test_simulated_save_leaves_no_trace(self):
		simulate(json.dumps([new_todo_step()]))
		created = frappe.response.docs[0]["name"]
		self.assertFalse(frappe.db.exists("ToDo", created))
		self.assertFalse(frappe.db.exists("ToDo", {"description": PROBE}))
		self.assertEqual(frappe.response.dry_run["steps"], 1)
		self.assertTrue(frappe.flags.read_only)

	def test_requires_view_session(self):
		frappe.session.data.pop(SESSION_KEY)
		with self.assertRaises(frappe.PermissionError):
			simulate(json.dumps([new_todo_step()]))

	def test_chained_steps_keep_client_names(self):
		simulate(json.dumps([new_todo_step()]))
		first = frappe.parse_json(frappe.as_json(frappe.response.docs[0]))
		recorded = {**new_todo_step(), "names": frappe.response.dry_run["names"]}
		edit = {
			"method": SAVE,
			"args": {"doc": json.dumps({**first, "priority": "High"}), "action": "Save"},
		}
		simulate(json.dumps([recorded, edit]))
		second = frappe.response.docs[0]
		self.assertEqual(second["name"], first["name"])
		self.assertEqual(second["priority"], "High")
		self.assertFalse(frappe.db.exists("ToDo", {"description": PROBE}))
