"""Keep the participants of a record's chat in step with the record's assignments.

An assignee always belongs to the chat about the record. The chat itself adds the missing ones
whenever it is opened or written to (`employee_chat._sync_assignees`); this hook covers the
moment in between, so a freshly assigned person sees an existing conversation in their list
straight away. Nobody is removed on unassignment — they stay until they leave.
"""

import frappe


def on_todo_change(doc, method=None):
	if doc.status != "Open" or not doc.allocated_to or not doc.reference_type or not doc.reference_name:
		return
	if doc.reference_type.startswith("Chat ") or not frappe.db.table_exists("Chat Thread"):
		return

	from erpnext.crm.doctype.chat_thread.chat_thread import document_dedup_key
	from erpnext.crm.page.employee_chat.employee_chat import _append_participant, _fanout

	name = frappe.db.get_value(
		"Chat Thread", {"dedup_key": document_dedup_key(doc.reference_type, doc.reference_name)}, "name"
	)
	if not name:
		return
	thread = frappe.get_doc("Chat Thread", name)
	if not _append_participant(thread, doc.allocated_to):
		return
	thread.save(ignore_permissions=True)
	_fanout(thread, "chat_message", {"thread": name, "system": True})
