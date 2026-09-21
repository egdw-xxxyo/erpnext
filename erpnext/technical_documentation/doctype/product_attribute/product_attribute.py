# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A property a product type can declare, and the values that property may take.

Modelled on `Item Attribute`, because the register is asked for the same thing the item
master already solves: a vocabulary someone maintains without a developer, so that two
modifications described as "Оптика" are found by one search instead of three spellings.

An attribute is either a list of values or a numeric range, never both — which of the two
it is decides how the value is validated on a modification and what the attribute search
offers in the list view. An attribute that is neither — no range, no listed values — is
free text: the modification writes whatever it likes and the search offers «starts with»
and «contains». That is the state to reach for when the values cannot be enumerated, and
it is a deliberate emptiness rather than an unfinished attribute, which is why both fields
say so on the form.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class ProductAttribute(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.technical_documentation.doctype.product_attribute_value.product_attribute_value import (
			ProductAttributeValue,
		)

		attribute_name: DF.Data
		attribute_values: DF.Table[ProductAttributeValue]
		disabled: DF.Check
		from_range: DF.Float
		increment: DF.Float
		numeric_values: DF.Check
		to_range: DF.Float
	# end: auto-generated types

	def validate(self):
		self.validate_range()
		self.validate_duplicate_values()

	def validate_range(self):
		if not self.numeric_values:
			return

		# An empty upper bound means "no upper bound", as validate_range in attributes.py reads it.
		if flt(self.to_range) and flt(self.from_range) > flt(self.to_range):
			frappe.throw(_("The start of the range cannot be greater than its end"))

		if flt(self.increment) < 0:
			frappe.throw(_("The increment cannot be negative"))

	def validate_duplicate_values(self):
		seen = set()
		for row in self.attribute_values:
			value = (row.attribute_value or "").strip()
			if value in seen:
				frappe.throw(_("Value {0} is listed twice").format(frappe.bold(value)))

			seen.add(value)
			row.attribute_value = value
