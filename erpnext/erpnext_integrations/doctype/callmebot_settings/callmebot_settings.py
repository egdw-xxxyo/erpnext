# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class CallMeBotSettings(Document):
	def validate(self):
		if "System Manager" not in frappe.get_roles():
			frappe.throw(_("Only System Managers can configure CallMeBot Settings."), frappe.PermissionError)

	def has_permission(self, ptype="read", user=None):
		return "System Manager" in frappe.get_roles(user or frappe.session.user)
