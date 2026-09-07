import frappe


def execute():
	"""Renumber `Task Depends On` rows whose `idx` collides inside the same parent.

	Rows removed server-side kept their `idx`, so the hole they left was reused by the
	next append and two different tasks ended up sharing a row number.
	"""
	affected = frappe.db.sql(
		"""
		select distinct parent
		from `tabTask Depends On`
		where parenttype = 'Task'
		group by parent, idx
		having count(*) > 1
		""",
		pluck="parent",
	)

	if not affected:
		return

	rows = 0
	for parent in affected:
		names = frappe.get_all(
			"Task Depends On",
			filters={"parent": parent, "parenttype": "Task"},
			pluck="name",
			order_by="idx asc, creation asc",
		)
		for idx, name in enumerate(names, 1):
			frappe.db.set_value("Task Depends On", name, "idx", idx, update_modified=False)
		rows += len(names)

	print(f"Renumbered {rows} Task Depends On rows across {len(affected)} tasks")
