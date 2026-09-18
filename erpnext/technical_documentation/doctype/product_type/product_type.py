# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ProductType(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.technical_documentation.doctype.product_attribute_assignment.product_attribute_assignment import (
			ProductAttributeAssignment,
		)

		attributes: DF.Table[ProductAttributeAssignment]
		product_type: DF.Data
	# end: auto-generated types

	pass
