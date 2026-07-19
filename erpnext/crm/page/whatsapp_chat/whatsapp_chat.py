import json
import re

import frappe
from frappe import _

# Doctypes whose forms can be reached from a chat's context panel and that carry a
# `contact_person` link we can use for reverse lookups.
DERIVED_SOURCES = [
	("Opportunity", "contact_person"),
	("Quotation", "contact_person"),
	("Sales Order", "contact_person"),
]

LINKABLE_DOCTYPES = [
	"Lead",
	"Contact",
	"Customer",
	"Opportunity",
	"Quotation",
	"Sales Order",
]


def notify_new_message(doc, method=None):
	"""On every WhatsApp Message: keep the conversation object in sync and push a
	realtime event so the WhatsApp Chat page updates instantly."""
	number = doc.get("from") if doc.get("type") == "Incoming" else doc.get("to")

	try:
		from erpnext.crm.doctype.whatsapp_chat.whatsapp_chat import sync_chat_from_message

		sync_chat_from_message(doc)
	except Exception:
		frappe.log_error(title="WhatsApp Chat sync failed", message=frappe.get_traceback())

	frappe.publish_realtime(
		event="whatsapp_message",
		message={"name": doc.name, "number": number, "type": doc.get("type")},
		after_commit=True,
	)


def _ensure_chats():
	"""Backfill WhatsApp Chat objects for any conversation that has messages but no
	chat yet (e.g. threads that predate the conversation model)."""
	from erpnext.crm.doctype.whatsapp_chat.whatsapp_chat import sync_chat_from_message

	numbers = set()
	for row in frappe.get_all("WhatsApp Message", fields=["`from`", "`to`", "type"]):
		numbers.add(row["from"] if row["type"] == "Incoming" else row["to"])
	numbers.discard(None)

	existing = set(frappe.get_all("WhatsApp Chat", pluck="phone"))
	for number in numbers - existing:
		msg = frappe.get_all(
			"WhatsApp Message",
			filters=[["WhatsApp Message", "from", "=", number], ["WhatsApp Message", "type", "=", "Incoming"]],
			fields=["name"],
			order_by="creation desc",
			limit=1,
		) or frappe.get_all(
			"WhatsApp Message",
			filters={"to": number},
			fields=["name"],
			order_by="creation desc",
			limit=1,
		)
		if msg:
			sync_chat_from_message(frappe.get_doc("WhatsApp Message", msg[0]["name"]))
	frappe.db.commit()


@frappe.whitelist()
def get_chats(manager=None):
	"""Return the conversation list, optionally filtered by an assigned manager."""
	_ensure_chats()

	chats = frappe.get_all(
		"WhatsApp Chat",
		fields=["name", "phone", "contact", "title", "last_message_on"],
		order_by="last_message_on desc",
	)

	if manager:
		allowed = set(
			frappe.get_all(
				"WhatsApp Chat Manager",
				filters={"parenttype": "WhatsApp Chat", "user": manager},
				pluck="parent",
			)
		)
		chats = [c for c in chats if c["name"] in allowed]

	for c in chats:
		last = frappe.get_all(
			"WhatsApp Message",
			or_filters=[
				["WhatsApp Message", "from", "=", c["phone"]],
				["WhatsApp Message", "to", "=", c["phone"]],
			],
			fields=["message", "content_type"],
			order_by="creation desc",
			limit=1,
		)
		c["preview"] = (last[0]["message"] if last else "") or ""
	return chats


@frappe.whitelist()
def get_managers():
	"""Users who can own WhatsApp conversations (Sales / System roles)."""
	users = frappe.get_all(
		"Has Role",
		filters={
			"parenttype": "User",
			"role": ["in", ["Sales User", "Sales Manager", "System Manager"]],
		},
		pluck="parent",
		distinct=True,
	)
	users = [u for u in users if u not in ("Administrator", "Guest")]
	return frappe.get_all(
		"User",
		filters={"name": ["in", users], "enabled": 1},
		fields=["name", "full_name"],
		order_by="full_name asc",
	)


def _chat_for_phone(phone):
	name = frappe.db.exists("WhatsApp Chat", {"phone": phone})
	return frappe.get_doc("WhatsApp Chat", name) if name else None


@frappe.whitelist()
def get_chat_context(phone):
	"""Everything linked to this dialog: explicit links + entities derived from the
	resolved Contact, plus the assigned managers."""
	chat = _chat_for_phone(phone)
	if not chat:
		return {"contact": None, "linked": [], "derived": [], "managers": []}

	seen = set()
	linked = []
	for row in chat.links:
		key = (row.link_doctype, row.link_name)
		if row.link_name and key not in seen:
			seen.add(key)
			linked.append(
				{"doctype": row.link_doctype, "name": row.link_name, "label": row.link_name}
			)

	derived = []
	if chat.contact:
		for doctype, fieldname in DERIVED_SOURCES:
			for rec in frappe.get_all(doctype, filters={fieldname: chat.contact}, pluck="name"):
				key = (doctype, rec)
				if key not in seen:
					seen.add(key)
					derived.append({"doctype": doctype, "name": rec, "label": rec})

	managers = [{"user": m.user, "full_name": m.full_name} for m in chat.assigned_managers]

	return {"contact": chat.contact, "linked": linked, "derived": derived, "managers": managers}


@frappe.whitelist()
def link_entity(phone, link_doctype, link_name):
	if link_doctype not in LINKABLE_DOCTYPES:
		frappe.throw(_("Cannot link {0}").format(link_doctype))
	chat = _chat_for_phone(phone)
	if not chat:
		frappe.throw(_("Chat not found"))
	if chat.add_link(link_doctype, link_name):
		chat.save(ignore_permissions=True)
	return get_chat_context(phone)


@frappe.whitelist()
def unlink_entity(phone, link_doctype, link_name):
	chat = _chat_for_phone(phone)
	if not chat:
		frappe.throw(_("Chat not found"))
	chat.links = [
		r for r in chat.links if not (r.link_doctype == link_doctype and r.link_name == link_name)
	]
	chat.save(ignore_permissions=True)
	return get_chat_context(phone)


def _digits(phone):
	return re.sub(r"\D", "", phone or "")


def _contact_phone(contact):
	if not contact:
		return None
	c = frappe.get_doc("Contact", contact)
	phone = c.mobile_no or c.phone
	if not phone:
		for row in c.phone_nos:
			if row.is_primary_mobile_no or row.is_primary_phone:
				phone = row.phone
				break
		if not phone and c.phone_nos:
			phone = c.phone_nos[0].phone
	return phone


@frappe.whitelist()
def resolve_phone(doctype, docname):
	"""Best-effort WhatsApp number (digits only) for a CRM document."""
	doc = frappe.get_doc(doctype, docname)
	phone = None

	if doctype == "Contact":
		phone = _contact_phone(docname)
	elif doctype == "Lead":
		phone = doc.get("mobile_no") or doc.get("phone")
	elif doc.get("contact_person"):
		phone = _contact_phone(doc.get("contact_person"))

	if not phone and doctype == "Customer":
		contact = frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": "Contact", "link_doctype": "Customer", "link_name": docname},
			pluck="parent",
			limit=1,
		)
		if contact:
			phone = _contact_phone(contact[0])

	if not phone:
		phone = doc.get("contact_mobile") or doc.get("mobile_no")

	return _digits(phone)


@frappe.whitelist()
def get_recent_messages(phone, limit=10):
	"""Recent messages for a number, oldest-first, for the read-only form panel."""
	phone = _digits(phone)
	if not phone:
		return []
	msgs = frappe.get_all(
		"WhatsApp Message",
		or_filters=[
			["WhatsApp Message", "from", "=", phone],
			["WhatsApp Message", "to", "=", phone],
		],
		fields=["type", "message", "creation", "status", "content_type", "attach"],
		order_by="creation desc",
		limit=int(limit),
	)
	return list(reversed(msgs))


def _default_outgoing_account():
	"""Name of the default outgoing WhatsApp Account, or throw if none set."""
	account = frappe.db.get_value("WhatsApp Account", {"is_default_outgoing": 1}, "name")
	if not account:
		frappe.throw(_("No default outgoing WhatsApp Account configured."))
	return account


def _insert_outgoing(fields):
	"""Insert an Outgoing WhatsApp Message (fork's before_insert dispatches to Meta)."""
	doc = frappe.get_doc(
		{
			"doctype": "WhatsApp Message",
			"type": "Outgoing",
			"message_type": "Manual",
			"whatsapp_account": _default_outgoing_account(),
			**fields,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def send_text(phone, message, reply_to_message_id=None):
	"""Send a plain text message, optionally as a reply to another message."""
	phone = _digits(phone)
	if not phone or not (message or "").strip():
		frappe.throw(_("Nothing to send"))
	fields = {"to": phone, "message": message, "content_type": "text"}
	if reply_to_message_id:
		fields["is_reply"] = 1
		fields["reply_to_message_id"] = reply_to_message_id
	return _insert_outgoing(fields)


@frappe.whitelist()
def send_media(phone, attach, content_type, caption=None, reply_to_message_id=None):
	"""Send an image/video/audio/document by its uploaded file URL."""
	phone = _digits(phone)
	if not phone or not attach:
		frappe.throw(_("Nothing to send"))
	if content_type not in ("image", "video", "audio", "document"):
		frappe.throw(_("Unsupported media type"))
	fields = {
		"to": phone,
		"attach": attach,
		"content_type": content_type,
		"message": caption or "",
	}
	if reply_to_message_id:
		fields["is_reply"] = 1
		fields["reply_to_message_id"] = reply_to_message_id
	return _insert_outgoing(fields)


@frappe.whitelist()
def send_reaction(phone, message_id, emoji):
	"""React to a message with an emoji (empty emoji removes the reaction)."""
	phone = _digits(phone)
	if not phone or not message_id:
		frappe.throw(_("Nothing to send"))
	return _insert_outgoing(
		{
			"to": phone,
			"content_type": "reaction",
			"message": emoji or "",
			"reply_to_message_id": message_id,
		}
	)


@frappe.whitelist()
def list_templates():
	"""Approved WhatsApp templates that can be sent from the chat, with body-parameter
	metadata so the UI can prompt for each placeholder. Templates are the only way to
	message a number outside Meta's 24h customer-service window."""
	rows = frappe.get_all(
		"WhatsApp Templates",
		filters={"status": "APPROVED"},
		fields=["name", "template_name", "language_code", "header_type", "field_names", "sample_values"],
		order_by="template_name asc",
	)
	for r in rows:
		names = r.get("field_names") or r.get("sample_values") or ""
		r["params"] = [p.strip() for p in names.split(",") if p.strip()]
	return rows


@frappe.whitelist()
def send_template(phone, template, body_params=None):
	"""Send an approved template message (bypasses the 24h window). body_params is an
	optional JSON object/dict of placeholder values, in template field order."""
	phone = _digits(phone)
	if not phone or not template:
		frappe.throw(_("Nothing to send"))
	fields = {"to": phone, "template": template, "content_type": "text"}
	if body_params:
		if isinstance(body_params, str):
			body_params = json.loads(body_params)
		if body_params:
			fields["body_param"] = json.dumps(body_params)
	# Store the rendered template body as the message text so the chat thread
	# shows what was actually sent instead of an empty bubble.
	body = frappe.db.get_value("WhatsApp Templates", template, "template") or ""
	values = list(body_params.values()) if isinstance(body_params, dict) else (body_params or [])
	for i, v in enumerate(values, start=1):
		body = body.replace("{{%d}}" % i, str(v))
	fields["message"] = body or _("[Template] {0}").format(template)
	return _insert_outgoing(fields)


def _party_for_chat(chat):
	"""Resolve an (opportunity_from, party_name) pair from the chat's links —
	prefer a Customer, fall back to a Lead."""
	customer = None
	lead = None
	for row in chat.links:
		if row.link_doctype == "Customer" and not customer:
			customer = row.link_name
		elif row.link_doctype == "Lead" and not lead:
			lead = row.link_name
	if customer:
		return "Customer", customer
	if lead:
		return "Lead", lead
	return None, None


@frappe.whitelist()
def create_opportunity(phone):
	"""Create an Opportunity for this dialog and link it back into the chat."""
	chat = _chat_for_phone(phone)
	if not chat:
		frappe.throw(_("Chat not found"))
	opportunity_from, party_name = _party_for_chat(chat)
	if not party_name:
		frappe.throw(_("Link a Customer or Lead to this chat first."))

	opp = frappe.new_doc("Opportunity")
	opp.opportunity_from = opportunity_from
	opp.party_name = party_name
	if chat.contact:
		opp.contact_person = chat.contact
	opp.insert(ignore_permissions=True)

	if chat.add_link("Opportunity", opp.name):
		chat.save(ignore_permissions=True)
	return {"doctype": "Opportunity", "name": opp.name}


@frappe.whitelist()
def create_todo(phone, description):
	"""Create a task (ToDo) referencing this dialog."""
	chat = _chat_for_phone(phone)
	if not chat:
		frappe.throw(_("Chat not found"))
	todo = frappe.new_doc("ToDo")
	todo.description = description
	todo.reference_type = "Contact" if chat.contact else "WhatsApp Chat"
	todo.reference_name = chat.contact or chat.name
	todo.insert(ignore_permissions=True)
	return {"doctype": "ToDo", "name": todo.name}


@frappe.whitelist()
def create_note(phone, title, content=None):
	"""Create a Note for this dialog."""
	note = frappe.new_doc("Note")
	note.title = title
	if content:
		note.content = content
	note.insert(ignore_permissions=True)
	return {"doctype": "Note", "name": note.name}


@frappe.whitelist()
def create_event(phone, subject, starts_on):
	"""Create a calendar Event linked to this dialog's contact."""
	chat = _chat_for_phone(phone)
	if not chat:
		frappe.throw(_("Chat not found"))
	event = frappe.new_doc("Event")
	event.subject = subject
	event.starts_on = starts_on
	event.event_type = "Private"
	if chat.contact:
		event.append("links", {"link_doctype": "Contact", "link_name": chat.contact})
	event.insert(ignore_permissions=True)
	return {"doctype": "Event", "name": event.name}


@frappe.whitelist()
def set_managers(phone, users):
	"""Replace the assigned-manager list for a chat. `users` is a JSON list."""
	if isinstance(users, str):
		users = frappe.parse_json(users)
	chat = _chat_for_phone(phone)
	if not chat:
		frappe.throw(_("Chat not found"))
	chat.assigned_managers = []
	for u in users or []:
		chat.append("assigned_managers", {"user": u})
	chat.save(ignore_permissions=True)
	return get_chat_context(phone)
