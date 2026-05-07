# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class BpAKTemplate(Document):
	def validate(self):
		if self.serial_number_template and not self.serial_no_series:
			self.serial_no_series = frappe.db.get_value(
				"Serial Number Template", self.serial_number_template, "resulting_series"
			)
