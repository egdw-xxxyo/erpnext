# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import json

import frappe
from frappe import _, throw
from frappe.desk.form.assign_to import clear, close_all_assignments
from frappe.model.mapper import get_mapped_doc
from frappe.utils import (
	add_days,
	cstr,
	date_diff,
	flt,
	get_fullname,
	get_link_to_form,
	getdate,
	today,
)
from frappe.utils.data import format_date
from frappe.utils.nestedset import NestedSet


class CircularReferenceError(frappe.ValidationError):
	pass


class ParentIsGroupError(frappe.ValidationError):
	pass


class TaskOwnedByAnotherGroupError(frappe.ValidationError):
	pass


class Task(NestedSet):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.projects.doctype.task_depends_on.task_depends_on import TaskDependsOn

		act_end_date: DF.Date | None
		act_start_date: DF.Date | None
		actual_time: DF.Float
		closing_date: DF.Date | None
		color: DF.Color | None
		company: DF.Link | None
		completed_by: DF.Link | None
		completed_on: DF.Date | None
		department: DF.Link | None
		depends_on: DF.Table[TaskDependsOn]
		depends_on_tasks: DF.Code | None
		description: DF.TextEditor | None
		duration: DF.Int
		exp_end_date: DF.Date | None
		exp_start_date: DF.Date | None
		expected_time: DF.Float
		is_group: DF.Check
		is_milestone: DF.Check
		is_template: DF.Check
		issue: DF.Link | None
		lft: DF.Int
		old_parent: DF.Data | None
		parent_task: DF.Link | None
		priority: DF.Literal["Low", "Medium", "High", "Urgent"]
		progress: DF.Percent
		project: DF.Link | None
		review_date: DF.Date | None
		rgt: DF.Int
		start: DF.Int
		status: DF.Literal[
			"New", "In Progress", "Awaiting Info", "Blocked", "In Review", "Completed", "Cancelled"
		]
		subject: DF.Data
		task_weight: DF.Float
		template_task: DF.Data | None
		total_billing_amount: DF.Currency
		total_costing_amount: DF.Currency
		type: DF.Link | None
	# end: auto-generated types

	nsm_parent_field = "parent_task"

	def onload(self):
		self.refresh_depends_on_details()

	def get_customer_details(self):
		cust = frappe.db.sql("select customer_name from `tabCustomer` where name=%s", self.customer)
		if cust:
			ret = {"customer_name": cust and cust[0][0] or ""}
			return ret

	def validate(self):
		self.validate_dates()
		self.validate_progress()
		self.validate_status()
		self.update_depends_on()
		self.refresh_depends_on_details()
		self.validate_dependencies_for_template_task()
		self.validate_completed_on()
		self.validate_parent_is_group()
		self.validate_depends_on_ownership()

	def validate_dates(self):
		self.validate_from_to_dates("exp_start_date", "exp_end_date")
		self.validate_from_to_dates("act_start_date", "act_end_date")
		self.validate_parent_expected_end_date()
		self.validate_parent_project_dates()

	def validate_parent_expected_end_date(self):
		if not self.parent_task or not self.exp_end_date:
			return

		parent_exp_end_date = frappe.db.get_value("Task", self.parent_task, "exp_end_date")
		if not parent_exp_end_date:
			return

		if getdate(self.exp_end_date) > getdate(parent_exp_end_date):
			frappe.throw(
				_(
					"Expected End Date should be less than or equal to parent task's Expected End Date {0}."
				).format(format_date(parent_exp_end_date)),
				frappe.exceptions.InvalidDates,
			)

	def validate_parent_project_dates(self):
		if not self.project or frappe.flags.in_test:
			return

		if project_end_date := frappe.db.get_value("Project", self.project, "expected_end_date"):
			project_end_date = getdate(project_end_date)
			for fieldname in ("exp_start_date", "exp_end_date", "act_start_date", "act_end_date"):
				task_date = self.get(fieldname)
				if task_date and date_diff(project_end_date, getdate(task_date)) < 0:
					frappe.throw(
						_("{0}'s {1} cannot be after {2}'s Expected End Date.").format(
							frappe.bold(frappe.get_desk_link("Task", self.name)),
							_(self.meta.get_label(fieldname)),
							frappe.bold(frappe.get_desk_link("Project", self.project)),
						),
						frappe.exceptions.InvalidDates,
					)

	def validate_status(self):
		if self.status != self.get_db_value("status") and self.status == "Completed":
			for d in self.depends_on:
				if frappe.db.get_value("Task", d.task, "status") not in ("Completed", "Cancelled"):
					frappe.throw(
						_(
							"Cannot complete task {0} as its dependant task {1} are not completed / cancelled."
						).format(frappe.bold(self.name), frappe.bold(d.task))
					)

			close_all_assignments(self.doctype, self.name)

	def validate_progress(self):
		if self.is_group:
			self.progress = get_group_progress(self.name)
			return

		if flt(self.progress or 0) > 100:
			frappe.throw(_("Progress % for a task cannot be more than 100."))

		if self.status == "Completed":
			self.progress = 100

	def validate_dependencies_for_template_task(self):
		if self.is_template:
			self.validate_parent_template_task()
			self.validate_depends_on_tasks()

	def validate_parent_template_task(self):
		if self.parent_task:
			if not frappe.db.get_value("Task", self.parent_task, "is_template"):
				frappe.throw(
					_("Parent Task {0} is not a Template Task").format(
						get_link_to_form("Task", self.parent_task)
					)
				)

	def validate_depends_on_tasks(self):
		if self.depends_on:
			for task in self.depends_on:
				if not frappe.db.get_value("Task", task.task, "is_template"):
					frappe.throw(
						_("Dependent Task {0} is not a Template Task").format(
							get_link_to_form("Task", task.task)
						)
					)

	def validate_completed_on(self):
		if self.completed_on and getdate(self.completed_on) > getdate():
			frappe.throw(_("Completed On cannot be greater than Today"))

	def validate_parent_is_group(self):
		if self.parent_task:
			if not frappe.db.get_value("Task", self.parent_task, "is_group"):
				frappe.throw(
					_("Parent Task {0} must be a Group Task").format(
						get_link_to_form("Task", self.parent_task)
					),
					ParentIsGroupError,
				)

	def validate_depends_on_ownership(self):
		if not self.is_group:
			return

		for row in self.depends_on:
			owner_task = frappe.db.get_value("Task", row.task, "parent_task")
			if owner_task and owner_task != self.name:
				frappe.throw(
					_("Task {0} already belongs to Group Task {1}.").format(
						get_link_to_form("Task", row.task), get_link_to_form("Task", owner_task)
					),
					TaskOwnedByAnotherGroupError,
				)

	def update_depends_on(self):
		depends_on_tasks = ""
		for d in self.depends_on:
			if d.task and d.task not in depends_on_tasks:
				depends_on_tasks += d.task + ","
		self.depends_on_tasks = depends_on_tasks

	def refresh_depends_on_details(self):
		details = get_task_details([row.task for row in self.depends_on if row.task])
		for row in self.depends_on:
			row.update(details.get(row.task, {}))

	def update_nsm_model(self):
		frappe.utils.nestedset.update_nsm(self)

	def on_update(self):
		self.update_nsm_model()
		self.check_recursion()
		self.reschedule_dependent_tasks()
		self.update_project()
		self.unassign_todo()
		self.populate_depends_on()
		self.detach_from_previous_parent()
		self.prune_stale_group_membership()
		self.sync_child_tasks()
		self.update_parent_group_progress()

	def get_previous_depends_on(self):
		previous = self.get_doc_before_save()
		return {row.task for row in previous.depends_on if row.task} if previous else set()

	def sync_child_tasks(self):
		"""Keep `depends_on` of a Group Task and `parent_task` of its children in sync."""
		if self.flags.ignore_child_task_sync:
			return

		previous_tasks = self.get_previous_depends_on()
		current_tasks = {row.task for row in self.depends_on if row.task}

		if self.is_group:
			for task_name in current_tasks - previous_tasks:
				set_parent_task(task_name, self.name)

		for task_name in previous_tasks - current_tasks:
			if frappe.db.get_value("Task", task_name, "parent_task") == self.name:
				set_parent_task(task_name, None)

	def detach_from_previous_parent(self):
		previous = self.get_doc_before_save()
		previous_parent = previous.parent_task if previous else None
		if previous_parent and previous_parent != self.parent_task:
			remove_depends_on_row(previous_parent, self.name)

	def prune_stale_group_membership(self):
		"""Drop rows in other Group Tasks that still claim this task as their child.

		The child is the source of truth for `parent_task`, so any Group Task holding a
		`depends_on` row for a task that no longer belongs to it keeps a stale link, which
		in turn blocks deleting or cancelling that task.
		"""
		if self.flags.ignore_child_task_sync:
			return

		holders = frappe.get_all(
			"Task Depends On",
			filters={"task": self.name, "parenttype": "Task"},
			pluck="parent",
		)

		for group in set(holders) - {self.parent_task, self.name}:
			if frappe.db.get_value("Task", group, "is_group"):
				remove_depends_on_row(group, self.name)

	def update_parent_group_progress(self):
		previous = self.get_doc_before_save()
		parents = {self.parent_task, previous.parent_task if previous else None}
		for parent_task in parents - {None, ""}:
			update_group_progress(parent_task)

	def unassign_todo(self):
		if self.status == "Completed":
			close_all_assignments(self.doctype, self.name)
		if self.status == "Cancelled":
			clear(self.doctype, self.name)

	def update_time_and_costing(self):
		tl = frappe.db.sql(
			"""select min(from_time) as start_date, max(to_time) as end_date,
			sum(billing_amount) as total_billing_amount, sum(costing_amount) as total_costing_amount,
			sum(hours) as time from `tabTimesheet Detail` where task = %s and docstatus=1""",
			self.name,
			as_dict=1,
		)[0]
		if self.status == "New":
			self.status = "In Progress"
		self.total_costing_amount = tl.total_costing_amount
		self.total_billing_amount = tl.total_billing_amount
		self.actual_time = tl.time
		self.act_start_date = tl.start_date
		self.act_end_date = tl.end_date

	def update_project(self):
		if self.project and not self.flags.from_project:
			frappe.get_cached_doc("Project", self.project).update_project()

	def check_recursion(self):
		if self.flags.ignore_recursion_check:
			return
		check_list = [["task", "parent"], ["parent", "task"]]
		for d in check_list:
			task_list, count = [self.name], 0
			while len(task_list) > count:
				tasks = frappe.db.sql(
					" select {} from `tabTask Depends On` where {} = {} ".format(d[0], d[1], "%s"),
					cstr(task_list[count]),
				)
				count = count + 1
				for b in tasks:
					if b[0] == self.name:
						frappe.throw(_("Circular Reference Error"), CircularReferenceError)
					if b[0]:
						task_list.append(b[0])

				if count == 15:
					break

	def reschedule_dependent_tasks(self):
		end_date = self.exp_end_date or self.act_end_date
		if end_date:
			for task_name in frappe.db.sql(
				"""
				select name from `tabTask` as parent
				where parent.project = %(project)s
					and parent.name in (
						select parent from `tabTask Depends On` as child
						where child.task = %(task)s and child.project = %(project)s)
			""",
				{"project": self.project, "task": self.name},
				as_dict=1,
			):
				task = frappe.get_doc("Task", task_name.name)
				if (
					task.exp_start_date
					and task.exp_end_date
					and task.exp_start_date < getdate(end_date)
					and task.status == "New"
				):
					task_duration = date_diff(task.exp_end_date, task.exp_start_date)
					task.exp_start_date = add_days(end_date, 1)
					task.exp_end_date = add_days(task.exp_start_date, task_duration)
					task.flags.ignore_recursion_check = True
					task.save()

	def has_webform_permission(self):
		project_user = frappe.db.get_value(
			"Project User", {"parent": self.project, "user": frappe.session.user}, "user"
		)
		if project_user:
			return True

	def populate_depends_on(self):
		if self.parent_task and frappe.db.exists("Task", self.parent_task):
			parent = frappe.get_doc("Task", self.parent_task)
			if self.name not in [row.task for row in parent.depends_on]:
				parent.append(
					"depends_on", {"doctype": "Task Depends On", "task": self.name, "subject": self.subject}
				)
				parent.save()

	def on_trash(self):
		if check_if_child_exists(self.name):
			throw(_("Child Task exists for this Task. You can not delete this Task."))

		self.update_nsm_model()

	def after_delete(self):
		self.update_project()
		update_group_progress(self.parent_task)

	def is_overdue(self):
		"""Overdue is derived from the expected end date, it is not a status."""
		if self.status in ("Cancelled", "Completed") or not self.exp_end_date:
			return False

		return getdate(self.exp_end_date) < getdate(today())


def set_parent_task(task_name, parent_task):
	if not frappe.db.exists("Task", task_name):
		return

	task = frappe.get_doc("Task", task_name)
	if task.parent_task == parent_task:
		return

	task.parent_task = parent_task
	task.save()


def remove_depends_on_row(parent_task, task_name):
	if not frappe.db.exists("Task", parent_task):
		return

	parent = frappe.get_doc("Task", parent_task)
	remaining = [row for row in parent.depends_on if row.task != task_name]
	if len(remaining) == len(parent.depends_on):
		return

	parent.set("depends_on", remaining)
	parent.flags.ignore_child_task_sync = True
	parent.save()


def get_group_progress(task_name):
	"""Share of completed child tasks, cancelled ones excluded from the total."""
	tally = {
		row.status: row.count
		for row in frappe.get_all(
			"Task",
			filters={"parent_task": task_name},
			fields=["status", "count(name) as count"],
			group_by="status",
		)
	}
	considered = sum(count for status, count in tally.items() if status != "Cancelled")

	return flt(tally.get("Completed", 0) / considered * 100, 2) if considered else 0.0


def update_group_progress(task_name):
	if not task_name or not frappe.db.get_value("Task", task_name, "is_group"):
		return

	frappe.db.set_value("Task", task_name, "progress", get_group_progress(task_name), update_modified=False)


def get_task_details(task_names):
	"""Fields mirrored into the `depends_on` grid of the tasks that reference these."""
	if not task_names:
		return {}

	return {
		task.name: {
			"subject": task.subject,
			"status": task.status,
			"progress": task.progress,
			"exp_end_date": task.exp_end_date,
			"responsible": get_assignees(task._assign),
		}
		for task in frappe.get_all(
			"Task",
			filters={"name": ("in", task_names)},
			fields=["name", "subject", "status", "progress", "exp_end_date", "_assign"],
		)
	}


def get_assignees(assignments):
	return ", ".join(get_fullname(user) for user in frappe.parse_json(assignments or "[]"))


@frappe.whitelist()
def check_if_child_exists(name):
	child_tasks = frappe.get_all("Task", filters={"parent_task": name})
	child_tasks = [get_link_to_form("Task", task.name) for task in child_tasks]
	return child_tasks


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_project(doctype, txt, searchfield, start, page_len, filters):
	from erpnext.controllers.queries import get_match_cond

	meta = frappe.get_meta(doctype)
	searchfields = meta.get_search_fields()
	search_columns = ", " + ", ".join(searchfields) if searchfields else ""
	search_cond = " or " + " or ".join(field + " like %(txt)s" for field in searchfields)

	return frappe.db.sql(
		f""" select name {search_columns} from `tabProject`
		where %(key)s like %(txt)s
			%(mcond)s
			{search_cond}
		order by name
		limit %(page_len)s offset %(start)s""",
		{
			"key": searchfield,
			"txt": "%" + txt + "%",
			"mcond": get_match_cond(doctype),
			"start": start,
			"page_len": page_len,
		},
	)


@frappe.whitelist()
def set_multiple_status(names, status):
	names = json.loads(names)
	for name in names:
		task = frappe.get_doc("Task", name)
		task.status = status
		task.save()


def get_overdue_filters():
	"""Filters for tasks that are past their expected end date and still open."""
	return {
		"status": ["not in", ["Cancelled", "Completed"]],
		"exp_end_date": ["<", today()],
	}


@frappe.whitelist()
def make_timesheet(source_name, target_doc=None, ignore_permissions=False):
	def set_missing_values(source, target):
		target.parent_project = source.project
		target.append(
			"time_logs",
			{
				"hours": source.actual_time,
				"completed": source.status == "Completed",
				"project": source.project,
				"task": source.name,
			},
		)

	doclist = get_mapped_doc(
		"Task",
		source_name,
		{"Task": {"doctype": "Timesheet"}},
		target_doc,
		postprocess=set_missing_values,
		ignore_permissions=ignore_permissions,
	)

	return doclist


@frappe.whitelist()
def get_children(doctype, parent, task=None, project=None, is_root=False):
	filters = [["docstatus", "<", "2"]]

	if task:
		filters.append(["parent_task", "=", task])
	elif parent and not is_root:
		# via expand child
		filters.append(["parent_task", "=", parent])
	else:
		filters.append(['ifnull(`parent_task`, "")', "=", ""])

	if project:
		filters.append(["project", "=", project])

	tasks = frappe.get_list(
		doctype,
		fields=["name as value", "subject as title", "is_group as expandable"],
		filters=filters,
		order_by="name",
	)

	# return tasks
	return tasks


@frappe.whitelist()
def add_node():
	from frappe.desk.treeview import make_tree_args

	args = frappe.form_dict
	args.update({"name_field": "subject"})
	args = make_tree_args(**args)

	if args.parent_task == "All Tasks" or args.parent_task == args.project:
		args.parent_task = None

	frappe.get_doc(args).insert()


@frappe.whitelist()
def add_multiple_tasks(data, parent):
	data = json.loads(data)
	new_doc = {"doctype": "Task", "parent_task": parent if parent != "All Tasks" else ""}
	new_doc["project"] = frappe.db.get_value("Task", {"name": parent}, "project") or ""

	for d in data:
		if not d.get("subject"):
			continue
		new_doc["subject"] = d.get("subject")
		new_task = frappe.get_doc(new_doc)
		new_task.insert()


def on_doctype_update():
	frappe.db.add_index("Task", ["lft", "rgt"])
