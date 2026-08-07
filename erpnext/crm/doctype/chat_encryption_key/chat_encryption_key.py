# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ChatEncryptionKey(Document):
	pass


def get_permission_query_conditions(user=None):
	"""A user only ever sees their own key record. The wrapped private key is useless
	without the passphrase, but there is no reason to expose it either."""
	user = user or frappe.session.user
	if user == "Administrator":
		return ""
	return f"`tabChat Encryption Key`.user = {frappe.db.escape(user)}"


def has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	return user == "Administrator" or doc.user == user
