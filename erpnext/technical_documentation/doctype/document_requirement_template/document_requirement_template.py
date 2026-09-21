# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class DocumentRequirementTemplate(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.technical_documentation.doctype.document_requirement_item.document_requirement_item import (
			DocumentRequirementItem,
		)

		product_type: DF.Link | None
		requirements: DF.Table[DocumentRequirementItem]
		template_name: DF.Data
	# end: auto-generated types

	pass
