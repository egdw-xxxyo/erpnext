# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime


class WhatsAppChat(Document):
	def validate(self):
		self._prune_dead_links()

	def _prune_dead_links(self):
		"""Drop link rows whose target document no longer exists, so a deleted
		linked doc never makes the chat unsaveable."""
		kept = []
		for row in self.links:
			if row.link_doctype and row.link_name and frappe.db.exists(
				row.link_doctype, row.link_name
			):
				kept.append(row)
		if len(kept) != len(self.links):
			self.links = kept

	def add_link(self, link_doctype, link_name):
		"""Idempotently add a Dynamic Link row to this chat."""
		if not link_doctype or not link_name:
			return False
		for row in self.links:
			if row.link_doctype == link_doctype and row.link_name == link_name:
				return False
		self.append("links", {"link_doctype": link_doctype, "link_name": link_name})
		return True


def _peer_number(doc):
	"""The customer's number regardless of message direction."""
	if doc.get("type") == "Incoming":
		return doc.get("from")
	return doc.get("to")


def sync_chat_from_message(doc):
	"""Upsert a WhatsApp Chat for the message's peer number, resolve its Contact,
	seed identity links (Contact + its Lead/Customer) and bump last_message_on.

	Cheap and idempotent — safe to run on every message insert/update.
	"""
	number = _peer_number(doc)
	if not number:
		return None

	name = frappe.db.exists("WhatsApp Chat", {"phone": number})
	if name:
		chat = frappe.get_doc("WhatsApp Chat", name)
	else:
		chat = frappe.new_doc("WhatsApp Chat")
		chat.phone = number
		chat.chat_type = "Personal"

	# Resolve the Contact by phone (reuse Frappe helper).
	if not chat.contact:
		try:
			from frappe.contacts.doctype.contact.contact import get_contact_with_phone_number

			contact = get_contact_with_phone_number(number)
		except Exception:
			contact = None
		if contact:
			chat.contact = contact

	# Title preference: contact full name > incoming profile_name > number.
	contact_name = None
	if chat.contact:
		contact_name = frappe.db.get_value("Contact", chat.contact, "full_name")
	if contact_name:
		chat.title = contact_name
	elif not chat.title:
		chat.title = doc.get("profile_name") or number

	# Seed identity links: the Contact itself + its linked Lead/Customer.
	if chat.contact:
		chat.add_link("Contact", chat.contact)
		for row in frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": "Contact", "parent": chat.contact},
			fields=["link_doctype", "link_name"],
		):
			chat.add_link(row.link_doctype, row.link_name)

	chat.last_message_on = get_datetime(doc.get("creation")) or frappe.utils.now_datetime()

	chat.save(ignore_permissions=True)
	return chat.name
