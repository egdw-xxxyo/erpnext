# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""The single door through which anything is written to the audit journal.

Track Changes stays on and keeps recording field diffs; this journal records the business
events a diff cannot reconstruct. A diff says `current_revision` went from one name to
another — it cannot say that a revision was put into force, by whom, or against which
revision it was weighed.

Everything here runs with `ignore_permissions`: a user who may only read a document still
produces journal entries by acting on it, and a user who may write to it still must not be
able to write to the journal directly. The flag is what the journal doctype checks, so an
entry created any other way is refused.
"""

import frappe
from frappe.utils import now

from erpnext.technical_documentation.constants import (
	AUDIT_ARCHIVED,
	AUDIT_CANCELLED,
	AUDIT_DOCTYPE,
	AUDIT_MADE_EFFECTIVE,
	AUDIT_RESPONSIBLE_CHANGED,
	AUDIT_STATUS_CHANGED,
	DOCUMENT_ARCHIVED,
	DOCUMENT_CANCELLED,
)

STATUS_EVENTS = {
	DOCUMENT_ARCHIVED: AUDIT_ARCHIVED,
	DOCUMENT_CANCELLED: AUDIT_CANCELLED,
}

AUDIT_FLAG = "in_technical_documentation_audit"


def log_event(document, event, **values):
	entry = frappe.get_doc(
		{
			"doctype": AUDIT_DOCTYPE,
			"document": document,
			"event": event,
			"event_time": now(),
			"user": frappe.session.user,
			**values,
		}
	)

	frappe.flags[AUDIT_FLAG] = True
	try:
		entry.insert(ignore_permissions=True)
	finally:
		frappe.flags[AUDIT_FLAG] = False

	return entry.name


def log_field_change(doc, fieldname, event):
	before = doc.get_doc_before_save()
	if not before:
		return

	old, new = before.get(fieldname), doc.get(fieldname)
	if old == new:
		return

	log_event(
		doc.name,
		STATUS_EVENTS.get(new, event),
		field_changed=fieldname,
		value_before=old,
		value_after=new,
	)


def log_document_changes(doc):
	log_field_change(doc, "status", AUDIT_STATUS_CHANGED)
	log_field_change(doc, "responsible", AUDIT_RESPONSIBLE_CHANGED)


def log_revision_effective(document, revision):
	"""A revision going into force and the document's pointer moving to it are one event.

	Both write paths call this, and whichever runs first records it. The guard compares
	against the latest entry rather than any entry, so a revision restored to force after
	being superseded is recorded again — that is a real event, not a repeat.
	"""
	latest = frappe.db.get_value(
		AUDIT_DOCTYPE,
		{"document": document, "event": AUDIT_MADE_EFFECTIVE},
		"revision",
		order_by="event_time desc, creation desc",
	)
	if latest == revision:
		return

	return log_event(document, AUDIT_MADE_EFFECTIVE, revision=revision)


def get_entries(document):
	return frappe.get_all(
		AUDIT_DOCTYPE,
		filters={"document": document},
		fields=[
			"event",
			"event_time",
			"user",
			"revision",
			"field_changed",
			"value_before",
			"value_after",
			"comment",
		],
		order_by="event_time desc, creation desc",
	)
