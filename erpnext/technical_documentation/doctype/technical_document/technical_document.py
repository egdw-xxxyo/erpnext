# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The card of a document, and the one place that says which revision is in force.

Lifecycle events go to the journal from here rather than from a hook: status, responsible
and the pointer to the revision in force are the three facts about a document that people
ask "who changed this, and when" about, and a field diff cannot answer it in those terms.

`current_revision` is a pointer, not a computation: the register never decides on its own
that the newest revision is the effective one, because "latest" and "in force" are
different facts and conflating them is the mistake ISO 9001 asks the register to make
impossible. What the code does guarantee is that the pointer cannot name something that
was never put into force — a revision of another document, a draft, or one already
superseded.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext.technical_documentation.audit import (
	log_document_changes,
	log_event,
	log_revision_effective,
)
from erpnext.technical_documentation.constants import (
	AUDIT_CREATED,
	DOCUMENT_DOCTYPE,
	REVISION_DOCTYPE,
	REVISION_EFFECTIVE,
	TYPE_DOCTYPE,
)
from erpnext.technical_documentation.doctype.product_subtype.product_subtype import (
	validate_type_and_subtype,
)


class TechnicalDocument(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.technical_documentation.doctype.technical_document_completeness_row.technical_document_completeness_row import (
			TechnicalDocumentCompletenessRow,
		)
		from erpnext.technical_documentation.doctype.technical_document_modification_row.technical_document_modification_row import (
			TechnicalDocumentModificationRow,
		)
		from erpnext.technical_documentation.doctype.technical_document_revision_row.technical_document_revision_row import (
			TechnicalDocumentRevisionRow,
		)

		company: DF.Link
		completeness_rows: DF.Table[TechnicalDocumentCompletenessRow]
		current_revision: DF.Link | None
		current_revision_effective_date: DF.Date | None
		document_code: DF.Data | None
		document_date: DF.Date | None
		document_title: DF.Data
		document_type: DF.Link
		external_number: DF.Data | None
		modification_rows: DF.Table[TechnicalDocumentModificationRow]
		next_review_date: DF.Date | None
		note: DF.SmallText | None
		product_model: DF.Data | None
		product_subtype: DF.Link | None
		product_type: DF.Link | None
		requirement_template: DF.Link | None
		responsible: DF.Link
		responsible_department: DF.Data | None
		revision_rows: DF.Table[TechnicalDocumentRevisionRow]
		section: DF.Link
		status: DF.Literal[
			"\u0427\u0435\u0440\u043d\u0435\u0442\u043a\u0430",
			"\u0427\u0438\u043d\u043d\u0438\u0439",
			"\u0417\u0430\u043c\u0456\u043d\u0435\u043d\u0438\u0439",
			"\u0421\u043a\u0430\u0441\u043e\u0432\u0430\u043d\u0438\u0439",
			"\u0410\u0440\u0445\u0456\u0432\u043d\u0438\u0439",
		]
		valid_until: DF.Date | None
	# end: auto-generated types

	def onload(self):
		self.set_onload("type_flags", type_flags(self.document_type))

	def validate(self):
		validate_type_and_subtype(self)
		self.validate_current_revision()

	def after_insert(self):
		log_event(self.name, AUDIT_CREATED)

	def on_update(self):
		log_document_changes(self)
		self.log_current_revision_change()

	def log_current_revision_change(self):
		before = self.get_doc_before_save()
		if not before or before.current_revision == self.current_revision or not self.current_revision:
			return

		log_revision_effective(self.name, self.current_revision)

	def validate_current_revision(self):
		if not self.current_revision:
			return

		revision = frappe.db.get_value(
			REVISION_DOCTYPE,
			self.current_revision,
			["technical_document", "docstatus", "revision_status", "effective_date"],
			as_dict=True,
		)

		if not revision or revision.technical_document != self.name:
			frappe.throw(
				_("Revision {0} belongs to another document").format(frappe.bold(self.current_revision))
			)

		if revision.docstatus != 1:
			frappe.throw(
				_("Revision {0} is not submitted and cannot be the current one").format(
					frappe.bold(self.current_revision)
				)
			)

		if revision.revision_status != REVISION_EFFECTIVE:
			frappe.throw(
				_("Revision {0} has status {1} and cannot be the current one").format(
					frappe.bold(self.current_revision), frappe.bold(revision.revision_status)
				)
			)

		self.current_revision_effective_date = revision.effective_date


def type_flags(document_type):
	"""Which extension sections the form shows, decided by the type and nothing else."""
	flags = frappe.db.get_value(
		TYPE_DOCTYPE,
		document_type,
		["has_product_classification", "has_modifications", "requires_completeness"],
		as_dict=True,
	)
	return flags or frappe._dict()


def document_type_flags(document):
	"""The extension flags of a document, read through the type it carries."""
	return type_flags(frappe.db.get_value(DOCUMENT_DOCTYPE, document, "document_type"))
