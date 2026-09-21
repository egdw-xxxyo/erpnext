import unittest
from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.utils import get_datetime, today

from erpnext.utilities.todo import ensure_default_filters, upgrade_overdue_filters, upgrade_today_filters


class TestToDoPresets(unittest.TestCase):
	def setUp(self):
		self.user = frappe.session.user
		frappe.set_user("Administrator")
		frappe.db.savepoint("todo_presets_test")
		self.addCleanup(self.rollback)
		self.noon = get_datetime(today() + " 12:00:00")
		self.clock = patch("erpnext.utilities.todo.now_datetime", return_value=self.noon)
		self.clock.start()
		self.addCleanup(self.clock.stop)
		self.records = {}
		cases = {
			"unset": (0, None),
			"start_today": (-1, self.noon.replace(hour=0)),
			"before_now": (-2, self.noon - timedelta(seconds=1)),
			"exact_now": (-3, self.noon),
			"end_today": (1, self.noon.replace(hour=23, minute=59, second=59)),
			"tomorrow": (0, self.noon.replace(hour=0) + timedelta(days=1)),
			"yesterday": (0, self.noon.replace(hour=0) - timedelta(seconds=1)),
			"other_user": (0, self.noon - timedelta(seconds=1)),
			"exact_24h": (-3, self.noon + timedelta(hours=24)),
			"after_24h": (-3, self.noon + timedelta(hours=24, seconds=1)),
		}
		for key, (days, deadline) in cases.items():
			doc = frappe.get_doc(
				{
					"doctype": "ToDo",
					"description": f"ToDo preset test: {key}",
					"allocated_to": "Guest" if key == "other_user" else "Administrator",
					"date": (self.noon + timedelta(days=days)).date(),
					"deadline": deadline,
				}
			).insert()
			self.records[key] = doc.name
		ensure_default_filters()
		upgrade_today_filters()
		upgrade_overdue_filters()
		self.presets = frappe.get_all(
			"List Filter",
			filters={"name": ["like", "todo-default-%"], "for_user": "Administrator"},
			fields=["name", "filters"],
		)

	def rollback(self):
		frappe.db.rollback(save_point="todo_presets_test")
		frappe.set_user(self.user)

	def matching(self, fieldname, operator, value=None):
		preset = next(
			row
			for row in self.presets
			if any(
				f[1:3] == [fieldname, operator] and (value is None or f[3] == value)
				for f in frappe.parse_json(row.filters)
			)
		)
		filters = frappe.parse_json(preset.filters)
		filters.append(["ToDo", "name", "in", list(self.records.values())])
		names = frappe.get_list("ToDo", filters=filters, pluck="name", limit_page_length=0)
		return {key for key, name in self.records.items() if name in names}

	def test_recent_assignment_calendar_boundaries(self):
		self.assertEqual(
			self.matching("date", "last three days"),
			{"unset", "start_today", "before_now", "tomorrow", "yesterday"},
		)

	def test_overdue_excludes_empty_and_exact_now(self):
		self.assertEqual(self.matching("deadline", "before now"), {"start_today", "before_now", "yesterday"})
		with patch("erpnext.utilities.todo.now_datetime", return_value=self.noon + timedelta(seconds=1)):
			self.assertIn("exact_now", self.matching("deadline", "before now"))

	def test_overdue_excludes_completed_and_cancelled_tasks(self):
		frappe.db.set_value("ToDo", self.records["before_now"], "status", "Closed")
		frappe.db.set_value("ToDo", self.records["yesterday"], "status", "Cancelled")
		self.assertEqual(self.matching("deadline", "before now"), {"start_today"})
		frappe.db.set_value("ToDo", self.records["before_now"], "status", "Open")
		self.assertEqual(self.matching("deadline", "before now"), {"start_today", "before_now"})

	def test_existing_overdue_preset_is_upgraded(self):
		preset = next(row for row in self.presets if "before now" in row.filters)
		conditions = [f for f in frappe.parse_json(preset.filters) if f[1] != "status"]
		frappe.db.set_value("List Filter", preset.name, "filters", frappe.as_json(conditions))
		upgrade_overdue_filters()
		upgrade_overdue_filters()
		updated = frappe.parse_json(frappe.db.get_value("List Filter", preset.name, "filters"))
		self.assertEqual(updated, [*conditions, ["ToDo", "status", "=", "Open"]])

	def test_today_means_next_24_hours(self):
		self.assertEqual(
			self.matching("deadline", "next 24 hours"),
			{"exact_now", "end_today", "tomorrow", "exact_24h"},
		)
		with patch("erpnext.utilities.todo.now_datetime", return_value=self.noon + timedelta(seconds=1)):
			self.assertEqual(
				self.matching("deadline", "next 24 hours"),
				{"end_today", "tomorrow", "exact_24h", "after_24h"},
			)

	def test_existing_today_preset_is_upgraded(self):
		preset = next(row for row in self.presets if "next 24 hours" in row.filters)
		old_filters = [
			["ToDo", "allocated_to", "=", "Administrator"],
			["ToDo", "deadline", "Timespan", "today"],
			["ToDo", "priority", "=", "High"],
		]
		frappe.db.set_value("List Filter", preset.name, "filters", frappe.as_json(old_filters))
		upgrade_today_filters()
		upgrade_today_filters()
		updated = frappe.parse_json(frappe.db.get_value("List Filter", preset.name, "filters"))
		self.assertEqual(
			updated,
			[old_filters[0], ["ToDo", "deadline", "next 24 hours", "Next 24 Hours"], old_filters[2]],
		)

	def test_missing_deadline(self):
		self.assertEqual(self.matching("deadline", "is", "not set"), {"unset"})

	def test_presets_are_idempotent_and_personal(self):
		ensure_default_filters()
		self.assertEqual(len(self.presets), 4)
		self.assertEqual(
			frappe.db.count("List Filter", {"name": ["like", "todo-default-%"], "for_user": "Administrator"}),
			4,
		)
		for preset in self.presets:
			self.assertIn(["ToDo", "allocated_to", "=", "Administrator"], frappe.parse_json(preset.filters))

	def test_default_filters_cannot_be_deleted_by_other_users(self):
		frappe.set_user("Guest")
		for preset in self.presets:
			with self.assertRaises(frappe.PermissionError):
				frappe.delete_doc("List Filter", preset.name, ignore_permissions=True)
			self.assertTrue(frappe.db.exists("List Filter", preset.name))

	def test_administrator_can_delete_default_filter(self):
		name = self.presets[0].name
		frappe.delete_doc("List Filter", name)
		self.assertFalse(frappe.db.exists("List Filter", name))

	def test_personal_filter_can_still_be_deleted(self):
		doc = frappe.get_doc(
			{
				"doctype": "List Filter",
				"reference_doctype": "ToDo",
				"filter_name": "Temporary personal filter test",
				"for_user": "Administrator",
				"filters": "[]",
			}
		).insert()
		frappe.delete_doc("List Filter", doc.name)
		self.assertFalse(frappe.db.exists("List Filter", doc.name))
