import json
import unittest

from erpnext.access_control.denial_rules import denial_context, slug_to_name, with_raised


class TestMethodContext(unittest.TestCase):
	def test_open_document(self):
		self.assertEqual(
			denial_context(
				"/api/method/frappe.desk.form.load.getdoc", "GET", {"doctype": "Quotation", "name": "Q-1"}
			),
			{
				"kind": "doctype",
				"doctype": "Quotation",
				"name": "Q-1",
				"ptype": "read",
				"method": "frappe.desk.form.load.getdoc",
			},
		)

	def test_save_new_document_is_create(self):
		doc = json.dumps({"doctype": "Lead", "__islocal": 1, "name": "new-lead-1"})
		context = denial_context(
			"/api/method/frappe.desk.form.save.savedocs", "POST", {"doc": doc, "action": "Save"}
		)
		self.assertEqual((context["doctype"], context["name"], context["ptype"]), ("Lead", None, "create"))

	def test_submit_and_cancel_actions(self):
		doc = json.dumps({"doctype": "Quotation", "name": "Q-1"})
		path = "/api/method/frappe.desk.form.save.savedocs"
		self.assertEqual(denial_context(path, "POST", {"doc": doc, "action": "Submit"})["ptype"], "submit")
		self.assertEqual(denial_context(path, "POST", {"doc": doc, "action": "Update"})["ptype"], "write")

	def test_delete_from_list_takes_first_item(self):
		context = denial_context(
			"/api/method/frappe.desk.reportview.delete_items",
			"POST",
			{"doctype": "ToDo", "items": '["T-1", "T-2"]'},
		)
		self.assertEqual((context["name"], context["ptype"]), ("T-1", "delete"))

	def test_page_and_report(self):
		self.assertEqual(
			denial_context("/api/method/frappe.desk.desk_page.getpage", "GET", {"name": "sales-invoice"})[
				"kind"
			],
			"page_or_doctype",
		)
		self.assertEqual(
			denial_context(
				"/api/method/frappe.desk.query_report.run", "POST", {"report_name": "General Ledger"}
			)["report"],
			"General Ledger",
		)

	def test_print(self):
		context = denial_context(
			"/api/method/frappe.www.printview.get_html_and_style", "GET", {"doc": "Quotation", "name": "Q-1"}
		)
		self.assertEqual((context["doctype"], context["ptype"]), ("Quotation", "print"))

	def test_unknown_method_with_doctype_is_read(self):
		context = denial_context("/api/method/custom.thing", "POST", {"doctype": "Item", "docname": "I-1"})
		self.assertEqual((context["doctype"], context["name"], context["ptype"]), ("Item", "I-1", "read"))

	def test_unknown_method_without_doctype_is_other(self):
		self.assertEqual(
			denial_context("/api/method/frappe.only_for_thing", "POST", {}),
			{"kind": "other", "method": "frappe.only_for_thing"},
		)

	def test_legacy_cmd_parameter(self):
		context = denial_context("/", "POST", {"cmd": "frappe.client.delete", "doctype": "Item", "name": "I"})
		self.assertEqual(context["ptype"], "delete")


class TestResourceContext(unittest.TestCase):
	def test_rest_verbs(self):
		self.assertEqual(denial_context("/api/resource/Item/I-1", "PUT", {})["ptype"], "write")
		self.assertEqual(denial_context("/api/resource/Item", "POST", {})["ptype"], "create")
		self.assertEqual(denial_context("/api/v2/document/Item/I-1", "DELETE", {})["ptype"], "delete")

	def test_unrelated_path(self):
		self.assertIsNone(denial_context("/app/item", "GET", {}))


RAISED = {"kind": "doctype", "doctype": "Consolidated Purchase Order", "name": None, "ptype": "read"}


class TestRaisedDenial(unittest.TestCase):
	def test_unknown_method_takes_raised_check(self):
		requested = denial_context("/api/method/erpnext.accounts.custom.check", "POST", {"doc": "{}"})
		self.assertEqual(
			with_raised(requested, RAISED),
			{**RAISED, "method": "erpnext.accounts.custom.check"},
		)

	def test_unknown_method_with_doctype_takes_raised_check(self):
		requested = denial_context("/api/method/erpnext.custom.run", "GET", {"doctype": "Item"})
		self.assertEqual(with_raised(requested, RAISED)["doctype"], "Consolidated Purchase Order")

	def test_known_method_keeps_request(self):
		requested = denial_context(
			"/api/method/frappe.desk.form.load.getdoc", "GET", {"doctype": "Quotation", "name": "Q-1"}
		)
		self.assertEqual(with_raised(requested, RAISED), requested)

	def test_resource_keeps_request(self):
		requested = denial_context("/api/resource/ToDo/T-1", "GET", {})
		self.assertEqual(with_raised(requested, RAISED), requested)

	def test_nothing_raised_keeps_request(self):
		requested = denial_context("/api/method/erpnext.accounts.custom.check", "POST", {})
		self.assertEqual(with_raised(requested, None), requested)

	def test_unrelated_path_takes_raised_check(self):
		self.assertEqual(with_raised(None, RAISED), RAISED)


class TestSlug(unittest.TestCase):
	def test_slug_to_name(self):
		self.assertEqual(slug_to_name("sales-invoice"), "sales invoice")
