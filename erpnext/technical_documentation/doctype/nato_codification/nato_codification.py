# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""One codification procedure, for one modification of one specification.

The record names both the document and the modification, and nothing in a pair of link
fields keeps them consistent: without the check below a codification can point at one
specification while its modification belongs to another, and the panel on the document
form would then show a codification that has nothing to do with that document. The
modification is the narrower fact, so the document follows from it rather than the other
way round.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext.technical_documentation.constants import MODIFICATION_DOCTYPE


class NATOCodification(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.technical_documentation.doctype.nato_codification_document.nato_codification_document import (
			NATOCodificationDocument,
		)

		codification_documents: DF.Table[NATOCodificationDocument]
		comment: DF.SmallText | None
		company: DF.Link | None
		end_date: DF.Date | None
		nsn_code: DF.Data | None
		other_codes: DF.SmallText | None
		product_modification: DF.Link
		start_date: DF.Date | None
		status: DF.Literal[
			"Не розпочато",
			"Підготовка документів",
			"На випробуваннях",
			"На кодифікації",
			"Кодифіковано",
			"Відхилено",
			"Скасовано",
		]
		technical_document: DF.Link
	# end: auto-generated types

	def validate(self):
		self.validate_modification_belongs_to_document()

	def validate_modification_belongs_to_document(self):
		document = frappe.db.get_value(MODIFICATION_DOCTYPE, self.product_modification, "technical_document")

		if document != self.technical_document:
			frappe.throw(
				_("Modification {0} belongs to document {1}, not to {2}").format(
					frappe.bold(self.product_modification),
					frappe.bold(document),
					frappe.bold(self.technical_document),
				)
			)
