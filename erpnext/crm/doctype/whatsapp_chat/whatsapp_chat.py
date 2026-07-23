# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime

# The chat list only renders a one-line preview; storing more just bloats the row.
PREVIEW_LENGTH = 200


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
	chat.last_preview = (doc.get("message") or "")[:PREVIEW_LENGTH]
	chat.last_content_type = doc.get("content_type")

	chat.save(ignore_permissions=True)
	return chat.name


def backfill_previews(chats):
	"""Fill last_preview/last_content_type (and a missing title) for chats created
	before those fields existed. Costs a query per chat, but only ever runs once per
	conversation — afterwards the list is a single read."""
	touched = False
	for chat in chats:
		needs_preview = chat.get("last_preview") is None
		needs_title = not chat.get("title")
		if not chat.get("phone") or not (needs_preview or needs_title):
			continue

		update = {}
		if needs_preview:
			last = frappe.get_all(
				"WhatsApp Message",
				or_filters=[
					["WhatsApp Message", "from", "=", chat["phone"]],
					["WhatsApp Message", "to", "=", chat["phone"]],
				],
				fields=["message", "content_type"],
				order_by="creation desc",
				limit=1,
			)
			chat["last_preview"] = ((last[0]["message"] if last else "") or "")[:PREVIEW_LENGTH]
			chat["last_content_type"] = last[0]["content_type"] if last else None
			update["last_preview"] = chat["last_preview"]
			update["last_content_type"] = chat["last_content_type"]

		if needs_title:
			# Fall back to the WhatsApp profile name seen on the last incoming message.
			profile = frappe.get_all(
				"WhatsApp Message",
				filters=[
					["WhatsApp Message", "from", "=", chat["phone"]],
					["WhatsApp Message", "type", "=", "Incoming"],
					["WhatsApp Message", "profile_name", "is", "set"],
				],
				fields=["profile_name"],
				order_by="creation desc",
				limit=1,
			)
			if profile:
				chat["title"] = profile[0]["profile_name"]
				update["title"] = chat["title"]

		if update:
			frappe.db.set_value(
				"WhatsApp Chat", chat["name"], update, update_modified=False
			)
			touched = True

	if touched:
		frappe.db.commit()
