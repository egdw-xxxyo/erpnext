import frappe
from frappe.utils.nestedset import rebuild_tree


def execute():
	"""Repair Group Task membership that never reached the child task.

	A `Task Depends On` row of a Group Task means "this task is my child", but rows
	created before the two-way sync — or while the holder was not a group yet — left the
	child's `parent_task` empty. Such a task is missing from the group in the tree and in
	its progress, and the row still blocks deleting it.

	Orphans are adopted by the group holding the row. Children whose `parent_task` points
	at a task that is not a Group Task are released instead: `validate_parent_is_group`
	rejects every later save of those, so they cannot be edited at all.
	"""
	adopted = adopt_orphans()
	released = release_children_of_non_groups()

	if adopted or released:
		rebuild_tree("Task")
		frappe.db.commit()

	print(f"Task parents repaired: {adopted} adopted, {released} released")


def adopt_orphans() -> int:
	orphans = frappe.db.sql(
		"""
		select tdo.task, tdo.parent
		from `tabTask Depends On` tdo
		inner join `tabTask` holder on holder.name = tdo.parent
		inner join `tabTask` child on child.name = tdo.task
		where tdo.parenttype = 'Task'
			and holder.is_group = 1
			and ifnull(child.parent_task, '') = ''
		order by tdo.idx
		""",
		as_dict=True,
	)

	seen = {}
	for row in orphans:
		# A task can only belong to one group; the first row wins, like the form does.
		seen.setdefault(row.task, row.parent)

	for task, parent in seen.items():
		set_parent(task, parent)

	return len(seen)


def release_children_of_non_groups() -> int:
	children = frappe.db.sql(
		"""
		select child.name
		from `tabTask` child
		inner join `tabTask` parent on parent.name = child.parent_task
		where ifnull(child.parent_task, '') <> ''
			and parent.is_group = 0
		""",
		pluck="name",
	)

	for child in children:
		set_parent(child, "")

	return len(children)


def set_parent(task: str, parent: str) -> None:
	frappe.db.set_value(
		"Task",
		task,
		{"parent_task": parent, "old_parent": parent},
		update_modified=False,
	)
