# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A modification of the product one specification describes.

The link to the document is checked against the type, not just against existence: only a
type that declares `has_modifications` has modifications at all, and without the check the
register happily hangs a product modification off an instruction or a contract — the link
field alone cannot tell them apart.

The modification is also where the NATO code and the package of documents behind it live.
They were a record of their own in the prototype, which forced every modification with a
code to carry a second card whose only real content was that code; the procedure around
the code is not something the register tracks, so what is left of it is the code, the date
it was issued and the documents it was issued against.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext.technical_documentation.attributes import build_summary, validate_attribute_rows
from erpnext.technical_documentation.constants import DOCUMENT_DOCTYPE
from erpnext.technical_documentation.doctype.product_subtype.product_subtype import (
	validate_type_and_subtype,
)
from erpnext.technical_documentation.doctype.technical_document.technical_document import (
	document_type_flags,
)


class ProductModification(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.technical_documentation.doctype.product_modification_attribute.product_modification_attribute import (
			ProductModificationAttribute,
		)
		from erpnext.technical_documentation.doctype.product_modification_document.product_modification_document import (
			ProductModificationDocument,
		)

		attribute_summary: DF.Data | None
		attributes: DF.Table[ProductModificationAttribute]
		company: DF.Link | None
		discontinued_date: DF.Date | None
		documents: DF.Table[ProductModificationDocument]
		full_name: DF.Data
		introduction_date: DF.Date | None
		modification_code: DF.Data
		note: DF.SmallText | None
		nsn_code: DF.Data | None
		nsn_date: DF.Date | None
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
		validate_type_and_subtype(self)
		validate_attribute_rows(self.attributes, self.product_type, self.product_subtype)
		self.fill_package_types()
		self.validate_package_revisions()
		self.attribute_summary = build_summary(self.attributes)

	def validate_document_has_modifications(self):
		if not document_type_flags(self.technical_document).get("has_modifications"):
			frappe.throw(
				_("Document {0} is of a type that has no product modifications").format(
					frappe.bold(self.technical_document)
				)
			)

	def fill_package_types(self):
		"""The type in a package row is read off the document, never asserted beside it.

		The row shows the type first because that is how a package is read — «інструкція з
		пакування: ІПАК-2026-00001» — and the form narrows the document list by it. What the
		row stores is still the document's own type: a row that names one type and a document
		of another is not something to reject, it is a copy of a fact that has one source.
		"""
		for row in self.documents:
			row.document_type = frappe.db.get_value(DOCUMENT_DOCTYPE, row.technical_document, "document_type")

	def validate_package_revisions(self):
		"""A package row may name a revision, but only one of the document it points at."""
		for row in self.documents:
			if not row.document_revision:
				continue

			if (
				frappe.db.get_value(
					"Technical Document Revision", row.document_revision, "technical_document"
				)
				!= row.technical_document
			):
				frappe.throw(
					_("Row {0}: revision {1} belongs to another document").format(
						row.idx, frappe.bold(row.document_revision)
					)
				)
