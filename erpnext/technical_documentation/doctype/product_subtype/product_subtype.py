# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A subtype of a product type, and the rule that a card may not contradict that pairing.

The rule lives here rather than in each card because the subtype is what knows its type.
The forms narrow the subtype field to the chosen type, so a mismatch normally cannot be
entered at all; the check is for what the form cannot cover — an import, a bulk edit, or a
type swapped on a card that already carried a subtype.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class ProductSubtype(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.technical_documentation.doctype.product_attribute_assignment.product_attribute_assignment import (
			ProductAttributeAssignment,
		)

		active: DF.Check
		attributes: DF.Table[ProductAttributeAssignment]
		product_subtype: DF.Data
		product_type: DF.Link
	# end: auto-generated types

	pass


def validate_type_and_subtype(doc):
	"""The subtype must belong to the chosen type; alone, it fills the type in."""
	if not doc.product_subtype:
		return

	product_type = frappe.db.get_value("Product Subtype", doc.product_subtype, "product_type")

	if not doc.product_type:
		doc.product_type = product_type
		return

	if product_type != doc.product_type:
		frappe.throw(
			_("Subtype {0} belongs to product type {1}, not {2}").format(
				frappe.bold(doc.product_subtype), frappe.bold(product_type), frappe.bold(doc.product_type)
			)
		)
