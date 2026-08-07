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
		self._set_template_name()
		self._resolve_specification_template()

	def _resolve_specification_template(self):
		if not self.get("specification_number_template"):
			return
		from erpnext.stock.doctype.specification_number_template.specification_number_template import (
			resolve_specification_template,
		)

		resolved = resolve_specification_template(self)
		if resolved:
			self.set("custom_шифр", resolved)

	def autoname(self):
		from frappe.model.naming import set_name_by_naming_series

		set_name_by_naming_series(self)
		self._set_template_name()

	def _set_template_name(self):
		parts = []
		for row in self.attributes or []:
			if not row.attribute or not row.attribute_value:
				continue
			vals = frappe.db.get_value(
				"Item Attribute Value",
				{"parent": row.attribute, "attribute_value": row.attribute_value},
				["short_name", "abbr"],
				as_dict=True,
			)
			label = (
				(vals.short_name if vals and vals.short_name else None)
				or (vals.abbr if vals and vals.abbr else None)
				or row.attribute_value
			)
			parts.append(label)
		if parts:
			self.template_name = " ".join(parts)
