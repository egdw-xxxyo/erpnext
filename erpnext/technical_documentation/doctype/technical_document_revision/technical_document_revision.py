# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A revision, which stops being editable the moment it is submitted.

Immutability is the framework's, not ours: `docstatus = 1` closes the record, and the only
fields that stay open are the ones whose value legitimately changes *after* the revision
exists — its status, the date it came into force, the date a newer revision replaced it,
and a comment. Everything that describes the revision itself is frozen.

Files are the one partial exception: a file slot left empty at submit may be filled later,
because the signed scan, the PDF or an annex often only exists after approval. A slot that
already holds a file is never rewritten or cleared — replacing the file of an approved
revision would rewrite history, so a corrected file means a new revision. The doctype also
protects attached files, so the File record behind a filled slot cannot be deleted either.
Every file added this way is written to the journal.

The effective date is in that set because `make_effective` works on a record that is
already closed. An expiry date earlier than the effective date is allowed: it reads as a
revision that was planned to come into force and was replaced before it did.

`cancel` is granted to nobody. A cancelled revision would be a historical record hidden
from the register, which is exactly what the ISO requirement forbids; a revision that
turned out wrong is superseded by another, and both stay visible.

The journal is written from here for the events that belong to the revision itself: a new
revision appearing, and its status moving — in particular the move that puts it in force,
which is recorded against the document so the document's own history reads in order.

Only one revision per document may be in force. The rule is enforced on every write path
including the post-submit one, because `revision_status` changes after submit and that is
precisely how a revision becomes effective.
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
	AUDIT_FILE_ADDED,
	AUDIT_NEW_REVISION,
	AUDIT_STATUS_CHANGED,
	DOCUMENT_DOCTYPE,
	REVISION_APPROVED,
	REVISION_CANCELLED,
	REVISION_DOCTYPE,
	REVISION_DRAFT,
	REVISION_EFFECTIVE,
	REVISION_FILE_FIELDS,
	REVISION_SUPERSEDED,
)

SUBMIT_REQUIRED_FIELDS = ("approval_date", "effective_date", "prepared_by", "checked_by")


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
		entered_as_superseded: DF.Check
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
		if self.docstatus == 0:
			self.revision_status = REVISION_DRAFT
		self.validate_single_effective()

	def before_submit(self):
		self.validate_submit_required()
		self.revision_status = REVISION_SUPERSEDED if self.entered_as_superseded else REVISION_APPROVED

	def validate_submit_required(self):
		required = SUBMIT_REQUIRED_FIELDS + (("end_date",) if self.entered_as_superseded else ())
		missing = [
			_(self.meta.get_label(field), context=self.doctype) for field in required if not self.get(field)
		]
		if missing:
			frappe.throw(
				_("Fill in before submitting: {0}").format(", ".join(missing)),
				title=_("Missing Fields"),
			)

	def before_cancel(self):
		self.revision_status = REVISION_CANCELLED

	def on_cancel(self):
		self.log_status_change()

	def on_discard(self):
		previous = self.revision_status
		self.db_set("revision_status", REVISION_CANCELLED)
		self.log_status_move(previous)

	def after_insert(self):
		log_event(self.technical_document, AUDIT_NEW_REVISION, revision=self.name)

	def on_update(self):
		self.log_status_change()

	def before_update_after_submit(self):
		self.validate_files_only_added()

	def on_update_after_submit(self):
		self.validate_single_effective()
		self.log_status_change()
		self.log_added_files()

	def changed_files(self):
		before = self.get_doc_before_save()
		if not before:
			return []

		return [
			(fieldname, before.get(fieldname), self.get(fieldname))
			for fieldname in REVISION_FILE_FIELDS
			if (before.get(fieldname) or None) != (self.get(fieldname) or None)
		]

	def validate_files_only_added(self):
		rewritten = [fieldname for fieldname, old, _new in self.changed_files() if old]
		if rewritten:
			frappe.throw(
				_(
					"A file already attached to a submitted revision cannot be replaced or removed: {0}"
				).format(", ".join(frappe.bold(_(self.meta.get_label(fieldname))) for fieldname in rewritten))
			)

	def log_added_files(self):
		for fieldname, _old, new in self.changed_files():
			log_event(
				self.technical_document,
				AUDIT_FILE_ADDED,
				revision=self.name,
				field_changed=fieldname,
				value_after=new,
			)

	def log_status_change(self):
		before = self.get_doc_before_save()
		if before:
			self.log_status_move(before.revision_status)

	def log_status_move(self, previous):
		if previous == self.revision_status:
			return

		if self.revision_status == REVISION_EFFECTIVE:
			log_revision_effective(self.technical_document, self.name)
			return

		log_event(
			self.technical_document,
			AUDIT_STATUS_CHANGED,
			revision=self.name,
			field_changed="revision_status",
			value_before=previous,
			value_after=self.revision_status,
		)

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
