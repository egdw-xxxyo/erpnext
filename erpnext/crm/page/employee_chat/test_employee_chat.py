# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
import json

import frappe
from frappe.desk.form import assign_to

from erpnext.crm.page.employee_chat import employee_chat as chat
from erpnext.tests.utils import ERPNextTestSuite

WRITER = "chat_writer@example.com"
READER = "chat_reader@example.com"
ASSIGNEE = "chat_assignee@example.com"
OUTSIDER = "chat_outsider@example.com"


def make_user(email, roles):
	if frappe.db.exists("User", email):
		return
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"enabled": 1,
		}
	)
	for role in roles:
		user.append("roles", {"role": role})
	user.insert(ignore_permissions=True)


class TestDocumentChat(ERPNextTestSuite):
	def setUp(self):
		frappe.set_user("Administrator")
		for email in (WRITER, READER, ASSIGNEE):
			make_user(email, ["System Manager", "Projects User"])
		make_user(OUTSIDER, [])
		self.task = frappe.get_doc({"doctype": "Task", "subject": "Chat membership"}).insert()

	def tearDown(self):
		frappe.set_user("Administrator")

	def open_as(self, user):
		frappe.set_user(user)
		return chat.open_document_thread("Task", self.task.name)

	def members(self, thread):
		return {p.user for p in frappe.get_doc("Chat Thread", thread).participants}

	def test_opening_does_not_join_but_writing_does(self):
		res = self.open_as(READER)
		self.assertFalse(res["is_member"])
		self.assertEqual(res["thread"]["is_member"], 0)
		self.assertNotIn(READER, self.members(res["name"]))
		self.assertEqual(chat.get_messages(res["name"]), [])
		self.assertEqual(chat.get_threads(), [])

		chat.send_message(res["name"], message="hello")
		self.assertIn(READER, self.members(res["name"]))
		self.assertEqual([t["name"] for t in chat.get_threads()], [res["name"]])

	def test_assignee_is_a_participant_and_cannot_leave(self):
		thread = self.open_as(WRITER)["name"]
		chat.send_message(thread, message="first")
		assign_to.add({"doctype": "Task", "name": self.task.name, "assign_to": [ASSIGNEE]})
		self.assertIn(ASSIGNEE, self.members(thread))

		frappe.set_user(ASSIGNEE)
		info = chat.get_thread_info(thread)
		mine = next(p for p in info["participants"] if p["is_me"])
		self.assertTrue(mine["is_assignee"])
		self.assertFalse(info["can_leave"])
		self.assertRaises(frappe.ValidationError, chat.leave_thread, thread)

	def test_everyone_in_the_chat_is_notified(self):
		thread = self.open_as(WRITER)["name"]
		chat.send_message(thread, message="first")
		frappe.set_user(READER)
		chat.send_message(thread, message="second")
		doc = frappe.get_doc("Chat Thread", thread)
		self.assertEqual(chat._notify_users(doc, READER), {WRITER, READER})

	def test_leaving_removes_the_chat_from_the_list(self):
		thread = self.open_as(WRITER)["name"]
		chat.send_message(thread, message="first")
		self.assertTrue(chat.get_thread_info(thread)["can_leave"])
		chat.leave_thread(thread)
		self.assertNotIn(WRITER, self.members(thread))
		self.assertEqual(chat.get_threads(), [])
		# Still readable from the record.
		self.assertEqual(len(chat.get_messages(thread)), 1)

	def test_adding_needs_access_to_the_record(self):
		thread = self.open_as(WRITER)["name"]
		chat.send_message(thread, message="first")
		chat.add_participant(thread, READER)
		self.assertIn(READER, self.members(thread))
		self.assertRaises(frappe.ValidationError, chat.add_participant, thread, OUTSIDER)

	def test_mention_joins_and_notifies(self):
		thread = self.open_as(WRITER)["name"]
		text = "@reader look"
		entities = [{"offset": 0, "length": 7, "doctype": "User", "name": READER}]
		payload = chat.send_message(thread, message=text, entities=json.dumps(entities))
		self.assertEqual(payload["entities"], entities)
		self.assertIn(READER, self.members(thread))
		log = frappe.get_all(
			"Notification Log",
			filters={"for_user": READER, "type": "Mention", "document_name": self.task.name},
			fields=["from_user", "document_type"],
		)
		self.assertEqual(len(log), 1)
		self.assertEqual(log[0].from_user, WRITER)

		outsider = [{"offset": 0, "length": 7, "doctype": "User", "name": OUTSIDER}]
		self.assertRaises(
			frappe.ValidationError, chat.send_message, thread, message=text, entities=json.dumps(outsider)
		)

	def test_search_finds_messages_of_this_chat_only(self):
		thread = self.open_as(WRITER)["name"]
		chat.send_message(thread, message="Привіт, 100% готово")
		chat.send_message(thread, message="інше")
		self.assertEqual(len(chat.search_messages(thread, "привіт")), 1)
		self.assertEqual(len(chat.search_messages(thread, "100%")), 1)
		# A wildcard is searched for literally.
		self.assertEqual(chat.search_messages(thread, "%%"), [])
		frappe.set_user(OUTSIDER)
		self.assertRaises(frappe.PermissionError, chat.search_messages, thread, "привіт")

	def test_entities_are_kept_inside_the_text(self):
		text = "@a and @b"
		rows = [
			{"offset": 0, "length": 2, "doctype": "User", "name": WRITER},
			{"offset": 1, "length": 3, "doctype": "User", "name": READER},
			{"offset": 7, "length": 9, "doctype": "User", "name": READER},
			{"offset": 7, "length": 2, "doctype": "User", "name": "nobody@example.com"},
			{"offset": 7, "length": 2, "doctype": "User", "name": READER},
		]
		self.assertEqual(
			chat._parse_entities(json.dumps(rows), text),
			[
				{"offset": 0, "length": 2, "doctype": "User", "name": WRITER},
				{"offset": 7, "length": 2, "doctype": "User", "name": READER},
			],
		)

	def test_mention_rank(self):
		values = ["petrenko@example.com", "Ivan", "Petrenko", "Ivan Petrenko", "vanya"]
		self.assertEqual(chat._mention_rank("vanya", values), 0)
		self.assertEqual(chat._mention_rank("petr", values), 1)
		self.assertEqual(chat._mention_rank("example", values), 2)
		self.assertEqual(chat._mention_rank("tren", values), 3)
		self.assertEqual(chat._mention_rank("zzz", values), 4)


class TestChatKinds(ERPNextTestSuite):
	def setUp(self):
		frappe.set_user("Administrator")
		for email in (WRITER, READER, ASSIGNEE):
			make_user(email, ["System Manager"])
		frappe.set_user(WRITER)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_one_direct_chat_per_pair_and_nobody_can_be_added(self):
		first = chat.create_thread([READER])
		again = chat.create_thread([READER])
		self.assertEqual(first["name"], again["name"])
		self.assertTrue(again["existing"])
		self.assertRaises(frappe.ValidationError, chat.add_participant, first["name"], ASSIGNEE)

	def test_groups_are_named_and_may_repeat(self):
		one = chat.create_thread([READER], thread_type="Group", title="Team")
		two = chat.create_thread([READER], thread_type="Group", title="Team")
		self.assertNotEqual(one["name"], two["name"])
		unnamed = chat.create_thread([READER, ASSIGNEE])
		self.assertTrue(frappe.db.get_value("Chat Thread", unnamed["name"], "title"))
		self.assertRaises(frappe.ValidationError, chat.rename_thread, one["name"], " ")

	def test_admin_rights_are_granted_by_an_admin(self):
		thread = chat.create_thread([READER, ASSIGNEE], thread_type="Group", title="Team")["name"]
		frappe.set_user(READER)
		self.assertRaises(frappe.PermissionError, chat.set_participant_role, thread, ASSIGNEE, "Admin")
		frappe.set_user(WRITER)
		chat.set_participant_role(thread, READER, "Admin")
		frappe.set_user(READER)
		chat.rename_thread(thread, "Renamed")
		chat.set_participant_role(thread, WRITER, "Member")
		# The last admin cannot be demoted.
		self.assertRaises(frappe.ValidationError, chat.set_participant_role, thread, READER, "Member")
