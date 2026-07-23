"""Attach existing chat media to its conversation.

Attachments sent before the chat overview existed were uploaded to Home/Attachments
without a parent document (Employee Chat) or attached to the individual message
(WhatsApp). Re-point them at the Chat Thread / WhatsApp Chat so the overview and the
document attachment sidebar list them.
"""

import frappe


def execute():
	if frappe.db.table_exists("Chat Message"):
		frappe.db.sql(
			"""
			update `tabFile` f
			join `tabChat Message` m on m.attach = f.file_url
			set f.attached_to_doctype = 'Chat Thread', f.attached_to_name = m.thread
			where m.attach is not null and m.attach != ''
				and (f.attached_to_doctype is null or f.attached_to_doctype != 'Chat Thread')
			"""
		)

	if frappe.db.table_exists("WhatsApp Chat") and frappe.db.table_exists("WhatsApp Message"):
		frappe.db.sql(
			"""
			update `tabFile` f
			join `tabWhatsApp Message` m on m.attach = f.file_url
			join `tabWhatsApp Chat` c
				on c.phone = if(m.type = 'Incoming', m.`from`, m.`to`)
			set f.attached_to_doctype = 'WhatsApp Chat', f.attached_to_name = c.name
			where m.attach is not null and m.attach != ''
				and (f.attached_to_doctype is null or f.attached_to_doctype != 'WhatsApp Chat')
			"""
		)
