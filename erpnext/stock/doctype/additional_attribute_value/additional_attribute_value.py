# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class AdditionalAttributeValue(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		abbr: DF.Data | None
		attribute: DF.Link
		description: DF.SmallText | None
		disabled: DF.Check
		value: DF.Data
	# end: auto-generated types

	def validate(self):
		self.validate_duplicate_value()

	def validate_duplicate_value(self):
		duplicate = frappe.db.exists(
			"Additional Attribute Value",
			{"attribute": self.attribute, "value": self.value, "name": ("!=", self.name)},
		)
		if duplicate:
			frappe.throw(
				_("Value {0} already exists for attribute {1}").format(
					frappe.bold(self.value), frappe.bold(self.attribute)
				),
				title=_("Duplicate Value"),
			)
