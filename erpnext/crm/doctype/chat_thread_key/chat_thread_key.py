# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ChatThreadKey(Document):
	pass


def get_permission_query_conditions(user=None):
	"""Wrapped thread keys are per-user: only the grantee ever needs to read one."""
	user = user or frappe.session.user
	if user == "Administrator":
		return ""
	return "`tabChat Thread Key`.user = {user}".format(user=frappe.db.escape(user))


def has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	return user == "Administrator" or doc.user == user
