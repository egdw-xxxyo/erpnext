"""ToDo reminders: at `remind_at` the assignee gets a bell notification (and, through the
Notification Log push hook, a push on the mobile app)."""

import frappe
from frappe.utils import now_datetime, strip_html


def reset_reminder(doc, method=None):
	"""ToDo validate hook: a moved reminder time fires again."""
	if doc.has_value_changed("remind_at"):
		doc.reminder_sent = 0


def send_due_reminders():
	todo = frappe.qb.DocType("ToDo")
	due = (
		frappe.qb.from_(todo)
		.select(todo.name, todo.allocated_to, todo.description)
		.where(
			(todo.status == "Open")
			& (todo.reminder_sent == 0)
			& todo.remind_at.isnotnull()
			& (todo.remind_at <= now_datetime())
			& todo.allocated_to.isnotnull()
			& (todo.allocated_to != "")
		)
		.limit(500)
		.run(as_dict=True)
	)
	for row in due:
		# Mark first: a failing notification must not re-fire every five minutes.
		frappe.db.set_value("ToDo", row.name, "reminder_sent", 1, update_modified=False)
		try:
			frappe.get_doc(
				{
					"doctype": "Notification Log",
					"for_user": row.allocated_to,
					"type": "Alert",
					"document_type": "ToDo",
					"document_name": row.name,
					"subject": (strip_html(row.description or "") or row.name)[:140],
				}
			).insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(f"ToDo reminder {row.name} failed")
		frappe.db.commit()
