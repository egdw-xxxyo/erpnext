import frappe


def execute():
	"""Drop `Task Depends On` rows of Group Tasks whose task is not their child anymore.

	Clearing `Parent Task` used to leave the row behind in the former parent, and that
	stale link blocks deleting or cancelling the detached task.
	"""
	stale = frappe.db.sql(
		"""
		select tdo.name, tdo.parent
		from `tabTask Depends On` tdo
		inner join `tabTask` parent on parent.name = tdo.parent
		left join `tabTask` child on child.name = tdo.task
		where tdo.parenttype = 'Task'
			and parent.is_group = 1
			and (child.name is null or ifnull(child.parent_task, '') <> tdo.parent)
		""",
		as_dict=True,
	)

	if not stale:
		return

	frappe.db.delete("Task Depends On", {"name": ("in", [row.name for row in stale])})

	for task_name in {row.parent for row in stale}:
		tasks = frappe.get_all(
			"Task Depends On",
			filters={"parent": task_name, "parenttype": "Task"},
			pluck="task",
			order_by="idx",
		)
		depends_on_tasks = "".join(f"{task}," for task in dict.fromkeys(t for t in tasks if t))
		frappe.db.set_value("Task", task_name, "depends_on_tasks", depends_on_tasks, update_modified=False)

	print(f"Removed {len(stale)} stale Task Depends On rows")
