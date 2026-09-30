# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_time

DEFAULT_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")


class WhatsAppChatSettings(Document):
	def onload(self):
		if not self.working_hours:
			for day in DEFAULT_DAYS:
				self.append(
					"working_hours", {"weekday": day, "start_time": "09:00:00", "end_time": "18:00:00"}
				)

	def validate(self):
		for row in self.working_hours:
			if get_time(row.end_time) <= get_time(row.start_time):
				frappe.throw(_("Row {0}: End Time must be after Start Time").format(row.idx))
