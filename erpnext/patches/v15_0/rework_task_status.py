import frappe

NEW_OPTIONS = ["New", "In Progress", "Awaiting Info", "Blocked", "In Review", "Completed", "Cancelled"]

STATUS_MAP = {
	"Open": "New",
	"Working": "In Progress",
	"Pending Review": "In Review",
	"Overdue": "In Progress",
	"Template": "New",
	"Closed": "Completed",
}


def execute():
	frappe.reload_doctype("Task")

	# customised option lists would re-introduce the removed statuses
	property_setter_name = frappe.db.exists(
		"Property Setter", dict(doc_type="Task", field_name="status", property="options")
	)
	if property_setter_name:
		frappe.delete_doc("Property Setter", property_setter_name, ignore_permissions=True)

	for old_status, new_status in STATUS_MAP.items():
		frappe.db.sql(
			"update `tabTask` set status = %s where status = %s",
			(new_status, old_status),
		)

	# fall back for any other stale value
	frappe.db.sql(
		"""update `tabTask` set status = 'New' where ifnull(status, '') not in {}""".format(
			"(" + ", ".join(["%s"] * len(NEW_OPTIONS)) + ")"
		),
		tuple(NEW_OPTIONS),
	)

	rebuild_task_kanban_boards()


def rebuild_task_kanban_boards():
	"""Kanban columns are generated from the status options, drop the stale ones."""
	boards = frappe.get_all(
		"Kanban Board",
		filters={"reference_doctype": "Task", "field_name": "status"},
		pluck="name",
	)
	if not boards:
		return

	for board in boards:
		doc = frappe.get_doc("Kanban Board", board)
		existing = {column.column_name: column for column in doc.columns}
		doc.columns = []
		for option in NEW_OPTIONS:
			column = existing.get(option)
			doc.append(
				"columns",
				{
					"column_name": option,
					"status": column.status if column else "Active",
					"indicator": column.indicator if column else "Gray",
				},
			)
		doc.save(ignore_permissions=True)
