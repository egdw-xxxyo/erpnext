# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ChatThread(Document):
	def validate(self):
		self.set_dedup_key()

	def set_dedup_key(self):
		"""For direct (1:1) threads store a stable key of the sorted participant users so
		a second attempt to open the same pair reuses the existing thread. Groups have no
		dedup key (multiple groups with the same members are allowed)."""
		if self.thread_type == "Direct":
			users = [p.user for p in self.participants if p.user]
			self.dedup_key = make_dedup_key(users, self.is_secret) if users else None
		else:
			self.dedup_key = None

	def is_participant(self, user):
		return any(p.user == user for p in self.participants)


def make_dedup_key(users, is_secret=0):
	"""A secret thread is a separate conversation from the plain one with the same pair,
	so the flag is part of the key — otherwise the second one would hit the unique index."""
	key = "|".join(sorted({u for u in users if u}))
	return key + "|secret" if is_secret else key


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
		" where parenttype = 'Chat Thread' and user = {user})"
	).format(user=frappe.db.escape(user))


def has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return any(p.user == user for p in doc.participants)
