# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class WhatsAppChatRead(Document):
	"""Per-user read cursor for one WhatsApp conversation — the WhatsApp counterpart of
	`Chat Participant.last_read_on`. Named `{chat}::{user}` so the pair is unique by
	construction and can be fetched without a query on the fields."""

	pass
