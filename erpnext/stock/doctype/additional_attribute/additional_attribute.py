# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext.stock.additional_attributes import MANDATORY_CACHE_KEY


class AdditionalAttribute(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		attribute_name: DF.Data
		description: DF.SmallText | None
		disabled: DF.Check
		mandatory: DF.Check
	# end: auto-generated types

	def validate(self):
		self.validate_mandatory_not_disabled()

	def validate_mandatory_not_disabled(self):
		if self.mandatory and self.disabled:
			frappe.throw(_("A disabled attribute cannot be mandatory"))

	def on_update(self):
		frappe.cache().delete_value(MANDATORY_CACHE_KEY)

	def on_trash(self):
		frappe.cache().delete_value(MANDATORY_CACHE_KEY)
