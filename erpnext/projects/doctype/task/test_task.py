# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import unittest

import frappe
from frappe.utils import add_days, getdate, nowdate

from erpnext.projects.doctype.task.task import (
	CircularReferenceError,
	ParentIsGroupError,
	TaskOwnedByAnotherGroupError,
)


class TestTask(unittest.TestCase):
	def test_circular_reference(self):
		task1 = create_task("_Test Task 1", add_days(nowdate(), -15), add_days(nowdate(), -10))
		task2 = create_task("_Test Task 2", add_days(nowdate(), 11), add_days(nowdate(), 15), task1.name)
		task3 = create_task("_Test Task 3", add_days(nowdate(), 11), add_days(nowdate(), 15), task2.name)

		task1.reload()
		task1.append("depends_on", {"task": task3.name})

		self.assertRaises(CircularReferenceError, task1.save)

		task1.set("depends_on", [])
		task1.save()

		task4 = create_task("_Test Task 4", nowdate(), add_days(nowdate(), 15), task1.name)

		task3.append("depends_on", {"task": task4.name})

	def test_reschedule_dependent_task(self):
		project = frappe.get_value("Project", {"project_name": "_Test Project"})

		task1 = create_task("_Test Task 1", nowdate(), add_days(nowdate(), 10))

		task2 = create_task("_Test Task 2", add_days(nowdate(), 11), add_days(nowdate(), 15), task1.name)
		task2.get("depends_on")[0].project = project
		task2.save()

		task3 = create_task("_Test Task 3", add_days(nowdate(), 11), add_days(nowdate(), 15), task2.name)
		task3.get("depends_on")[0].project = project
		task3.save()

		task1.update({"exp_end_date": add_days(nowdate(), 20)})
		task1.save()

		self.assertEqual(
			frappe.db.get_value("Task", task2.name, "exp_start_date"), getdate(add_days(nowdate(), 21))
		)
		self.assertEqual(
			frappe.db.get_value("Task", task2.name, "exp_end_date"), getdate(add_days(nowdate(), 25))
		)

		self.assertEqual(
			frappe.db.get_value("Task", task3.name, "exp_start_date"), getdate(add_days(nowdate(), 26))
		)
		self.assertEqual(
			frappe.db.get_value("Task", task3.name, "exp_end_date"), getdate(add_days(nowdate(), 30))
		)

	def test_close_assignment(self):
		if not frappe.db.exists("Task", "Test Close Assignment"):
			task = frappe.new_doc("Task")
			task.subject = "Test Close Assignment"
			task.insert()

		def assign():
			from frappe.desk.form import assign_to

			assign_to.add(
				{
					"assign_to": ["test@example.com"],
					"doctype": task.doctype,
					"name": task.name,
					"description": "Close this task",
				}
			)

		def get_owner_and_status():
			return frappe.db.get_value(
				"ToDo",
				filters={
					"reference_type": task.doctype,
					"reference_name": task.name,
					"description": "Close this task",
				},
				fieldname=("allocated_to", "status"),
				as_dict=True,
			)

		assign()
		todo = get_owner_and_status()
		self.assertEqual(todo.allocated_to, "test@example.com")
		self.assertEqual(todo.status, "Open")

		# assignment should be
		task.load_from_db()
		task.status = "Completed"
		task.save()
		todo = get_owner_and_status()
		self.assertEqual(todo.allocated_to, "test@example.com")
		self.assertEqual(todo.status, "Closed")

	def test_overdue(self):
		from erpnext.projects.doctype.task.task import get_overdue_filters

		task = create_task("Testing Overdue", add_days(nowdate(), -10), add_days(nowdate(), -5))

		# overdue is derived, the status must stay untouched
		self.assertEqual(frappe.db.get_value("Task", task.name, "status"), "New")
		self.assertTrue(task.is_overdue())
		self.assertIn(task.name, frappe.get_all("Task", filters=get_overdue_filters(), pluck="name"))

		task.status = "Completed"
		task.save()
		self.assertFalse(task.is_overdue())

	def test_parent_task_must_be_group(self):
		parent_task = create_task(
			subject="_Test Parent Task Non Group",
			is_group=0,
		)

		child_task = create_task(
			subject="_Test Child Task",
			parent_task=parent_task.name,
			save=False,
		)

		self.assertRaises(ParentIsGroupError, child_task.save)

	def test_group_progress_excludes_cancelled_tasks(self):
		group_task = create_task(subject="_Test Group Progress", is_group=1)

		statuses = ["Completed"] + ["New"] * 9 + ["Cancelled"] * 5
		for index, status in enumerate(statuses):
			child = create_task(subject=f"_Test Group Progress Child {index}", parent_task=group_task.name)
			child.status = status
			child.save()

		group_task.reload()
		self.assertEqual(group_task.progress, 10)

	def test_group_progress_without_countable_tasks(self):
		group_task = create_task(subject="_Test Empty Group Progress", is_group=1)

		group_task.reload()
		self.assertEqual(group_task.progress, 0)

		child = create_task(subject="_Test Empty Group Child", parent_task=group_task.name)
		child.status = "Cancelled"
		child.save()

		group_task.reload()
		self.assertEqual(group_task.progress, 0)

	def test_group_progress_ignores_manual_input(self):
		group_task = create_task(subject="_Test Manual Group Progress", is_group=1)
		child = create_task(subject="_Test Manual Group Child", parent_task=group_task.name)
		child.status = "Completed"
		child.save()

		group_task.reload()
		group_task.progress = 42
		group_task.save()

		self.assertEqual(group_task.progress, 100)

	def test_manual_progress_kept_for_regular_task(self):
		task = create_task(subject="_Test Manual Progress")

		task.progress = 42
		task.save()

		self.assertEqual(frappe.db.get_value("Task", task.name, "progress"), 42)

	def test_depends_on_details_are_refreshed(self):
		dependency = create_task(subject="_Test Dependency Details", end=add_days(nowdate(), 5), is_group=0)
		task = create_task(subject="_Test Dependent Details", end=add_days(nowdate(), 5))
		task.append("depends_on", {"task": dependency.name})
		task.save()

		dependency.status = "Completed"
		dependency.save()

		task.reload()
		task.run_method("onload")
		row = task.depends_on[0]
		self.assertEqual(row.status, "Completed")
		self.assertEqual(row.progress, 100)
		self.assertEqual(row.exp_end_date, getdate(add_days(nowdate(), 5)))

	def test_dependency_on_group_becomes_child(self):
		group_task = create_task(subject="_Test Sync Group", is_group=1)
		task = create_task(subject="_Test Sync Child")

		group_task.append("depends_on", {"task": task.name})
		group_task.save()

		self.assertEqual(frappe.db.get_value("Task", task.name, "parent_task"), group_task.name)

		task.reload()
		task.status = "Completed"
		task.save()

		group_task.reload()
		self.assertEqual(group_task.progress, 100)

	def test_dependency_on_regular_task_stays_a_dependency(self):
		task = create_task(subject="_Test Plain Dependant")
		dependency = create_task(subject="_Test Plain Dependency")

		task.append("depends_on", {"task": dependency.name})
		task.save()

		self.assertIsNone(frappe.db.get_value("Task", dependency.name, "parent_task"))

	def test_removing_dependency_detaches_child(self):
		group_task = create_task(subject="_Test Detach Group", is_group=1)
		task = create_task(subject="_Test Detach Child", parent_task=group_task.name)

		group_task.reload()
		group_task.set("depends_on", [])
		group_task.save()

		self.assertFalse(frappe.db.get_value("Task", task.name, "parent_task"))

	def test_changing_parent_cleans_up_previous_group(self):
		first_group = create_task(subject="_Test Move Group 1", is_group=1)
		second_group = create_task(subject="_Test Move Group 2", is_group=1)
		task = create_task(subject="_Test Move Child", parent_task=first_group.name)

		task.reload()
		task.parent_task = second_group.name
		task.save()

		first_group.reload()
		second_group.reload()
		self.assertNotIn(task.name, [row.task for row in first_group.depends_on])
		self.assertIn(task.name, [row.task for row in second_group.depends_on])

	def test_task_cannot_belong_to_two_groups(self):
		first_group = create_task(subject="_Test Owned Group 1", is_group=1)
		second_group = create_task(subject="_Test Owned Group 2", is_group=1)
		task = create_task(subject="_Test Owned Child", parent_task=first_group.name)

		second_group.append("depends_on", {"task": task.name})

		self.assertRaises(TaskOwnedByAnotherGroupError, second_group.save)

	def test_clearing_parent_removes_depends_on_row(self):
		group_task = create_task(subject="_Test Clear Parent Group", is_group=1)
		task = create_task(subject="_Test Clear Parent Child", parent_task=group_task.name)

		task.reload()
		task.status = "Completed"
		task.completed_on = nowdate()
		task.parent_task = None
		task.save()

		group_task.reload()
		self.assertNotIn(task.name, [row.task for row in group_task.depends_on])
		self.assertNotIn(task.name, group_task.depends_on_tasks or "")

	def test_stale_depends_on_row_is_pruned_on_child_save(self):
		group_task = create_task(subject="_Test Stale Group", is_group=1)
		task = create_task(subject="_Test Stale Child")

		# a row that bypasses the sync logic, like the ones left behind by older versions
		row = frappe.get_doc(
			{
				"doctype": "Task Depends On",
				"parent": group_task.name,
				"parenttype": "Task",
				"parentfield": "depends_on",
				"task": task.name,
				"idx": 99,
			}
		)
		row.db_insert()

		task.reload()
		task.save()

		self.assertFalse(frappe.db.exists("Task Depends On", row.name))

	def test_detached_task_can_be_deleted(self):
		group_task = create_task(subject="_Test Deletable Group", is_group=1)
		task = create_task(subject="_Test Deletable Child", parent_task=group_task.name)

		task.reload()
		task.status = "Completed"
		task.completed_on = nowdate()
		task.parent_task = None
		task.save()

		frappe.delete_doc("Task", task.name)
		self.assertFalse(frappe.db.exists("Task", task.name))


def create_task(
	subject,
	start=None,
	end=None,
	depends_on=None,
	project=None,
	parent_task=None,
	is_group=0,
	is_template=0,
	begin=0,
	duration=0,
	save=True,
	priority=None,
):
	if not frappe.db.exists("Task", subject):
		task = frappe.new_doc("Task")
		task.status = "New"
		task.subject = subject
		task.exp_start_date = start or nowdate()
		task.exp_end_date = end or nowdate()
		task.project = (
			project or None if is_template else frappe.get_value("Project", {"project_name": "_Test Project"})
		)
		task.is_template = is_template
		task.start = begin
		task.duration = duration
		task.is_group = is_group
		task.parent_task = parent_task
		task.priority = priority
		if save:
			task.save()
	else:
		task = frappe.get_doc("Task", subject)

	if depends_on:
		task.append("depends_on", {"task": depends_on})
		if save:
			task.save()
	return task
