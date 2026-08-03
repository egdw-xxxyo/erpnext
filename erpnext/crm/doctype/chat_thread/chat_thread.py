# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ChatThread(Document):
	def validate(self):
		self.set_dedup_key()

	def set_dedup_key(self):
		"""For direct (1:1) threads store a stable key of the sorted participant users so
		a second attempt to open the same pair reuses the existing thread. Document threads
		key off the linked record (one chat per record). Groups have no dedup key (multiple
		groups with the same members are allowed)."""
		if self.thread_type == "Direct":
			users = [p.user for p in self.participants if p.user]
			self.dedup_key = make_dedup_key(users, self.is_secret) if users else None
		elif self.thread_type == "Document":
			# Set at creation from the reference; keep it stable across later saves.
			if self.reference_doctype and self.reference_name:
				self.dedup_key = document_dedup_key(self.reference_doctype, self.reference_name)
		else:
			self.dedup_key = None

	def is_participant(self, user):
		return any(p.user == user for p in self.participants)


def make_dedup_key(users, is_secret=0):
	"""A secret thread is a separate conversation from the plain one with the same pair,
	so the flag is part of the key — otherwise the second one would hit the unique index."""
	key = "|".join(sorted({u for u in users if u}))
	return key + "|secret" if is_secret else key


def document_dedup_key(reference_doctype, reference_name):
	"""Stable, collision-free key for a record's chat — the unique `dedup_key` index then
	enforces one Document thread per record. The `doc::` prefix can't clash with Direct
	keys (joined user emails)."""
	return f"doc::{reference_doctype}::{reference_name}"


def on_reference_deleted(doc, method=None):
	"""Global `on_trash` handler (wired for every doctype): when a record that owns a
	Document chat is deleted, archive its thread and flag the reference as removed. The
	thread, its history and the ghost `reference_label` survive so the conversation stays
	legible."""
	# Never react to our own chat doctypes (they carry no such reference and it avoids noise).
	if (doc.doctype or "").startswith("Chat "):
		return
	threads = frappe.get_all(
		"Chat Thread",
		filters={"reference_doctype": doc.doctype, "reference_name": doc.name},
		pluck="name",
	)
	for name in threads:
		frappe.db.set_value(
			"Chat Thread",
			name,
			{"is_archived": 1, "reference_removed": 1},
			update_modified=False,
		)
		frappe.publish_realtime(
			"chat_reference_removed",
			{"thread": name},
			after_commit=True,
		)


def get_permission_query_conditions(user=None):
	"""Restrict Chat Thread visibility to threads the user participates in. Administrator
	is the only escape hatch (debugging / migrations); even System Managers see only their
	own threads — internal chat is strictly private."""
	user = user or frappe.session.user
	if user == "Administrator":
		return ""
	return (
		"`tabChat Thread`.name in"
		" (select parent from `tabChat Participant`"
		f" where parenttype = 'Chat Thread' and user = {frappe.db.escape(user)})"
	)


def has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return any(p.user == user for p in doc.participants)
