# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A revision, which stops being editable the moment it is submitted.

Immutability is the framework's, not ours: `docstatus = 1` closes the record, and the only
fields that stay open are the ones whose value legitimately changes *after* the revision
exists — its status, the date it came into force, the date a newer revision replaced it,
and a comment. Everything that describes the revision itself, files included, is frozen.

The effective date is in that set because a revision is normally submitted before anyone
decides when it starts applying: `make_effective` stamps it on a record that is already
closed, and the ordering rule is re-checked on that path too, since `validate` does not
run after submit.

`cancel` is granted to nobody. A cancelled revision would be a historical record hidden
from the register, which is exactly what the ISO requirement forbids; a revision that
turned out wrong is superseded by another, and both stay visible.

The journal is written from here for the events that belong to the revision itself: a new
revision appearing, and its status moving — in particular the move that puts it in force,
which is recorded against the document so the document's own history reads in order.

Only one revision per document may be in force. The rule is enforced on every write path
including the post-submit one, because `revision_status` is editable after submit and that
is precisely how a revision becomes effective.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import today

from erpnext.technical_documentation.audit import (
	log_event,
	log_revision_effective,
)
from erpnext.technical_documentation.constants import (
	AUDIT_NEW_REVISION,
	AUDIT_STATUS_CHANGED,
	DOCUMENT_DOCTYPE,
	REVISION_DOCTYPE,
	REVISION_EFFECTIVE,
	REVISION_SUPERSEDED,
)


class TechnicalDocumentRevision(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		additional_attachment: DF.Attach | None
		amended_from: DF.Link | None
		approval_date: DF.Date | None
		approved_by: DF.Link | None
		change_basis: DF.SmallText | None
		change_description: DF.SmallText | None
		checked_by: DF.Link | None
		comment: DF.SmallText | None
		creation_date: DF.Date | None
		effective_date: DF.Date | None
		end_date: DF.Date | None
		pdf_file: DF.Attach | None
		prepared_by: DF.Link | None
		revision_number: DF.Data
		revision_status: DF.Literal[
			"\u0427\u0435\u0440\u043d\u0435\u0442\u043a\u0430",
			"\u0417\u0430\u0442\u0432\u0435\u0440\u0434\u0436\u0435\u043d\u0430",
			"\u0427\u0438\u043d\u043d\u0430",
			"\u0417\u0430\u043c\u0456\u043d\u0435\u043d\u0430",
			"\u0421\u043a\u0430\u0441\u043e\u0432\u0430\u043d\u0430",
		]
		revision_title: DF.Data | None
		signed_scan: DF.Attach | None
		technical_document: DF.Link
		word_file: DF.Attach | None
	# end: auto-generated types

	def validate(self):
		self.validate_dates()
		self.validate_single_effective()

	def after_insert(self):
		log_event(self.technical_document, AUDIT_NEW_REVISION, revision=self.name)

	def on_update(self):
		self.log_status_change()

	def on_update_after_submit(self):
		self.validate_dates()
		self.validate_single_effective()
		self.log_status_change()

	def log_status_change(self):
		before = self.get_doc_before_save()
		if not before or before.revision_status == self.revision_status:
			return

		if self.revision_status == REVISION_EFFECTIVE:
			log_revision_effective(self.technical_document, self.name)
			return

		log_event(
			self.technical_document,
			AUDIT_STATUS_CHANGED,
			revision=self.name,
			field_changed="revision_status",
			value_before=before.revision_status,
			value_after=self.revision_status,
		)

	def validate_dates(self):
		if self.effective_date and self.end_date and self.end_date < self.effective_date:
			frappe.throw(_("Expiry date cannot be earlier than the effective date"))

	def validate_single_effective(self):
		if self.revision_status != REVISION_EFFECTIVE:
			return

		other = frappe.db.get_value(
			REVISION_DOCTYPE,
			{
				"technical_document": self.technical_document,
				"revision_status": REVISION_EFFECTIVE,
				"docstatus": ("<", 2),
				"name": ("!=", self.name),
			},
			"name",
		)
		if other:
			frappe.throw(
				_("Revision {0} is already in force for document {1}").format(
					frappe.bold(other), frappe.bold(self.technical_document)
				)
			)


@frappe.whitelist()
def make_effective(revision: str) -> str:
	"""Put a revision into force, and move everything that follows from it in one step.

	Three records change together: the revision that was in force becomes superseded and
	gets an end date, this one becomes effective, and the document's pointer moves to it.
	Doing it by hand means three saves in the right order — the single-effective rule
	rejects the middle one if the first is forgotten — which is why the pointer is
	read-only on the form and this is the only way to move it.

	Each step goes through `save()` rather than `db.set_value`, so the journal records the
	same events it would record for a manual change, and the register's own rules get to
	refuse the move rather than being bypassed by it.
	"""
	doc = frappe.get_doc(REVISION_DOCTYPE, revision)
	frappe.has_permission(DOCUMENT_DOCTYPE, "write", doc=doc.technical_document, throw=True)

	if doc.docstatus != 1:
		frappe.throw(_("Only a submitted revision can be put into force"))

	supersede_current(doc)

	doc.revision_status = REVISION_EFFECTIVE
	doc.effective_date = doc.effective_date or today()
	doc.save()

	document = frappe.get_doc(DOCUMENT_DOCTYPE, doc.technical_document)
	document.current_revision = doc.name
	document.save()

	return doc.name


def supersede_current(revision):
	name = frappe.db.get_value(
		REVISION_DOCTYPE,
		{
			"technical_document": revision.technical_document,
			"revision_status": REVISION_EFFECTIVE,
			"docstatus": 1,
			"name": ("!=", revision.name),
		},
		"name",
	)
	if not name:
		return

	previous = frappe.get_doc(REVISION_DOCTYPE, name)
	previous.revision_status = REVISION_SUPERSEDED
	previous.end_date = previous.end_date or today()
	previous.save()
