# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class FCMDeviceToken(Document):
	pass


def get_permission_query_conditions(user=None):
	"""A user only ever sees their own device tokens (Administrator/System Manager see all)."""
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return ""
	return f"`tabFCM Device Token`.user = {frappe.db.escape(user)}"


def has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	return user == "Administrator" or "System Manager" in frappe.get_roles(user) or doc.user == user
