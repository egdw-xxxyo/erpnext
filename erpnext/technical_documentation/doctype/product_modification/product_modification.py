# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A modification of the product one specification describes.

The link to the document is checked against the type, not just against existence: only a
type that declares `has_modifications` has modifications at all, and without the check the
register happily hangs a product modification off an instruction or a contract — the link
field alone cannot tell them apart.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext.technical_documentation.doctype.technical_document.technical_document import (
	document_type_flags,
)


class ProductModification(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		company: DF.Link | None
		discontinued_date: DF.Date | None
		full_name: DF.Data
		introduction_date: DF.Date | None
		modification_code: DF.Data
		note: DF.SmallText | None
		product_subtype: DF.Link | None
		product_type: DF.Link | None
		status: DF.Literal[
			"Чернетка",
			"Чинна",
			"Замінена",
			"Скасована",
			"Архівна",
		]
		technical_document: DF.Link
	# end: auto-generated types

	def validate(self):
		self.validate_document_has_modifications()

	def validate_document_has_modifications(self):
		if not document_type_flags(self.technical_document).get("has_modifications"):
			frappe.throw(
				_("Document {0} is of a type that has no product modifications").format(
					frappe.bold(self.technical_document)
				)
			)
