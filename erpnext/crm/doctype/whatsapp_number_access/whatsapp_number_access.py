# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class WhatsAppNumberAccess(Document):
	def on_change(self):
		frappe.cache.delete_value("whatsapp_access_map")

	def on_trash(self):
		frappe.cache.delete_value("whatsapp_access_map")
