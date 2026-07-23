# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ChatMessage(Document):
	pass


def get_permission_query_conditions(user=None):
	"""Only messages in threads the user participates in are visible (list/report views)."""
	user = user or frappe.session.user
	if user == "Administrator":
		return ""
	return (
		"`tabChat Message`.thread in"
		" (select parent from `tabChat Participant`"
		" where parenttype = 'Chat Thread' and user = {user})"
	).format(user=frappe.db.escape(user))


def has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(
		frappe.db.exists(
			"Chat Participant",
			{"parenttype": "Chat Thread", "parent": doc.thread, "user": user},
		)
	)
