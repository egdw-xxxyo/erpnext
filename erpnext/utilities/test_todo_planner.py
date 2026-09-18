import unittest
from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.utils import get_datetime, today

from erpnext.utilities.todo_planner import get_tasks


class TestToDoPlanner(unittest.TestCase):
	def setUp(self):
		self.user = frappe.session.user
		frappe.set_user("Administrator")
		frappe.db.savepoint("todo_planner_test")
		self.addCleanup(self.cleanup)
		self.start = get_datetime(today())
		self.end = self.start + timedelta(days=7)
		self.records = {}
		for key, deadline, status in (
			("start", self.start, "Open"),
			("end", self.end, "Open"),
			("before", self.start - timedelta(seconds=1), "Open"),
			("closed", self.start, "Closed"),
			("cancelled", self.start, "Cancelled"),
			("unset", None, "Open"),
			("unset_closed", None, "Closed"),
		):
			doc = frappe.get_doc(
				{
					"doctype": "ToDo",
					"description": f"Planner test {key}",
					"allocated_to": "Administrator",
					"deadline": deadline,
					"status": status,
					"date": today(),
				}
			).insert()
			self.records[key] = doc.name
		self.filters = [["ToDo", "name", "in", list(self.records.values())]]

	def cleanup(self):
		frappe.db.rollback(save_point="todo_planner_test")
		frappe.set_user(self.user)

	def fetch(self, **kwargs):
		return get_tasks(self.start, self.end, filters=self.filters, **kwargs)

	def names(self, **kwargs):
		return {task.name for task in self.fetch(**kwargs)["tasks"]}

	def test_range_is_half_open_and_defaults_to_open(self):
		self.assertEqual(self.names(), {self.records["start"]})

	def test_include_completed_excludes_cancelled(self):
		self.assertEqual(self.names(include_closed=1), {self.records["start"], self.records["closed"]})

	def test_overdue_excludes_completed_and_future(self):
		with patch("erpnext.utilities.todo_planner.now_datetime", return_value=self.start):
			self.assertEqual(self.names(section="overdue", include_closed=1), {self.records["before"]})

	def test_unscheduled(self):
		self.assertEqual(self.names(section="unscheduled"), {self.records["unset"]})

	def test_overdue_uses_time_and_remains_in_calendar(self):
		deadline = self.start.replace(hour=8, minute=21)
		frappe.db.set_value("ToDo", self.records["start"], "deadline", deadline)
		for now, expected in ((deadline, False), (deadline + timedelta(seconds=1), True)):
			with self.subTest(now=now), patch(
				"erpnext.utilities.todo_planner.now_datetime", return_value=now
			):
				calendar = self.fetch()["tasks"]
				self.assertEqual(calendar[0].name, self.records["start"])
				self.assertEqual(calendar[0].is_overdue, expected)
				self.assertEqual(self.records["start"] in self.names(section="overdue"), expected)

	def test_explicit_status_filter_is_respected(self):
		self.filters.append(["ToDo", "status", "=", "Closed"])
		self.assertEqual(self.names(), {self.records["closed"]})

	def test_pagination(self):
		with patch("erpnext.utilities.todo_planner.PAGE_SIZE", 1):
			first = self.fetch(include_closed=1)
			second = self.fetch(include_closed=1, offset=1)
			self.assertTrue(first["has_more"])
			self.assertFalse(second["has_more"])
			self.assertNotEqual(first["tasks"][0].name, second["tasks"][0].name)

	def test_assignee_filter(self):
		self.filters.append(["ToDo", "allocated_to", "=", "Guest"])
		self.assertEqual(self.names(), set())

	def test_guest_cannot_read_tasks(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			self.fetch()

	def test_invalid_range_and_section(self):
		with self.assertRaises(frappe.ValidationError):
			get_tasks(self.end, self.start)
		with self.assertRaises(frappe.ValidationError):
			self.fetch(section="unknown")

	def test_foreign_filters_rejected(self):
		self.filters = [["User", "name", "=", "Administrator"]]
		with self.assertRaises(frappe.ValidationError):
			self.fetch()
