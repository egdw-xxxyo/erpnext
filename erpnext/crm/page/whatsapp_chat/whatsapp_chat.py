import json
import re

import frappe
from frappe import _
from frappe.utils import add_days, now, now_datetime, nowdate

from erpnext.crm import whatsapp_access as wa_access

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


def _require_wa_access(ptype="read"):
	"""Guard every WhatsApp Chat endpoint: the caller must hold the matching role
	permission on WhatsApp Message (read for viewing, create for sending) and be
	assigned to at least one business number."""
	if not frappe.has_permission("WhatsApp Message", ptype) or not wa_access.accounts_for():
		frappe.throw(_("Not permitted to access WhatsApp chats"), frappe.PermissionError)


def notify_new_message(doc, method=None):
	"""On every WhatsApp Message: keep the conversation object in sync and push a
	realtime event so the WhatsApp Chat page updates instantly."""
	number = doc.get("from") if doc.get("type") == "Incoming" else doc.get("to")
	chat_name = None

	try:
		from erpnext.crm.doctype.whatsapp_chat.whatsapp_chat import sync_chat_from_message

		chat_name = sync_chat_from_message(doc)
		# The media file the fork downloaded is attached to the message; re-point it at
		# the conversation so the chat overview (and the chat form) owns it.
		if doc.get("attach"):
			link_attachment_to_chat(doc.get("attach"), chat_name)
	except Exception:
		frappe.log_error(title="WhatsApp Chat sync failed", message=frappe.get_traceback())

	account = doc.get("whatsapp_account")
	payload = {
		"name": doc.name,
		"chat": chat_name,
		"number": number,
		"whatsapp_account": account,
		"type": doc.get("type"),
		"content_type": doc.get("content_type"),
		"preview": frappe.utils.strip_html(doc.get("message") or "")[:120],
	}
	# Fan out only to users who see this business number — a global broadcast would
	# leak customer numbers to every logged-in desk user.
	for user in wa_access.users_for_account(account):
		frappe.publish_realtime(
			event="whatsapp_message",
			message=payload,
			user=user,
			after_commit=True,
		)


def _ensure_chats():
	"""Backfill WhatsApp Chat objects for any conversation that has messages but no
	chat yet (e.g. threads that predate the conversation model)."""
	from erpnext.crm.doctype.whatsapp_chat.whatsapp_chat import sync_chat_from_message

	# The chat list is polled every few seconds — keep the backfill scan off the hot
	# path once it has run.
	if frappe.cache().get_value("whatsapp_chats_backfilled"):
		return

	pairs = set(
		frappe.db.sql(
			"""
			select distinct whatsapp_account, if(type = 'Incoming', `from`, `to`) as number
			from `tabWhatsApp Message`
			where whatsapp_account is not null
			"""
		)
	)
	existing = set(frappe.db.sql("select whatsapp_account, phone from `tabWhatsApp Chat`"))
	for account, number in pairs - existing:
		if not number:
			continue
		msg = frappe.get_all(
			"WhatsApp Message",
			filters={"whatsapp_account": account, "from": number, "type": "Incoming"},
			fields=["name"],
			order_by="creation desc",
			limit=1,
		) or frappe.get_all(
			"WhatsApp Message",
			filters={"whatsapp_account": account, "to": number},
			fields=["name"],
			order_by="creation desc",
			limit=1,
		)
		if msg:
			sync_chat_from_message(frappe.get_doc("WhatsApp Message", msg[0]["name"]))
	frappe.db.commit()
	# New conversations get their chat from notify_new_message, so the scan only
	# needs to run once per cache lifetime.
	frappe.cache().set_value("whatsapp_chats_backfilled", 1, expires_in_sec=3600)


@frappe.whitelist()
def get_chats(account=None, mode="work"):
	"""The conversation list, optionally of one number. `work` (WhatsApp Chat page, bubble)
	lists the numbers the caller answers; `watch` (WhatsApp Chat Monitor) the numbers
	they spectate, read-only."""
	_require_wa_access()
	_ensure_chats()

	watch = mode == "watch"
	allowed = wa_access.watch_accounts() if watch else wa_access.work_accounts()
	accounts = [a for a in ([account] if account else allowed) if a in allowed]
	if not accounts:
		return []

	chats = frappe.get_all(
		"WhatsApp Chat",
		filters={"whatsapp_account": ["in", accounts]},
		fields=[
			"name",
			"whatsapp_account",
			"phone",
			"contact",
			"title",
			"last_message_on",
			"last_preview",
			"last_content_type",
			"finished",
			"archived",
		],
		order_by="last_message_on desc",
	)

	from erpnext.crm.doctype.whatsapp_chat.whatsapp_chat import backfill_previews, is_obsolete

	# The preview is denormalised onto the chat by sync_chat_from_message(), so the
	# list costs one query instead of one per conversation. Rows that predate those
	# fields are filled in once, on first read.
	backfill_previews(chats)

	from erpnext.crm.whatsapp_person import people_for

	labels = wa_access.account_labels()
	people = people_for([c["phone"] for c in chats])
	unread = _unread_counts([c["name"] for c in chats])
	states = frappe.get_all(
		"WhatsApp Chat Read",
		filters={"user": frappe.session.user},
		fields=["chat", "muted", "last_read_on"],
	)
	muted = {s.chat for s in states if s.muted}
	now_dt = now_datetime()
	# The client needs its own read cursor to place the "New messages" divider and scroll
	# to the first unread message on open.
	cursor = {s.chat: str(s.last_read_on) if s.last_read_on else None for s in states}
	for c in chats:
		c["preview"] = c.pop("last_preview", None) or ""
		c["preview_content_type"] = c.pop("last_content_type", None)
		if not c.get("title"):
			c["title"] = c["phone"]
		c["number_label"] = labels.get(c["whatsapp_account"], {}).get("label") or c["whatsapp_account"]
		c["read_only"] = 1 if watch else 0
		c["image"] = (people.get(c["phone"]) or {}).get("image")
		c["unread"] = unread.get(c["name"], 0)
		c["muted"] = 1 if c["name"] in muted else 0
		c["my_last_read"] = cursor.get(c["name"])
		c["obsolete"] = 1 if is_obsolete(c, now_dt) else 0
	return chats


@frappe.whitelist()
def get_my_numbers():
	"""The numbers the caller answers and the ones they follow, with their labels."""
	_require_wa_access()
	return {"work": wa_access.my_accounts(), "watch": wa_access.my_watch_accounts()}


# Unread counting only looks this far back: a conversation nobody ever opened would
# otherwise report its entire history as unread, and count it on every list poll.
UNREAD_WINDOW_DAYS = 90


def _unread_counts(chat_names):
	"""Incoming messages newer than the current user's read cursor, per conversation.

	One grouped query for the whole list — the read cursor lives in `WhatsApp Chat Read`
	(one row per user per chat), so this is the WhatsApp equivalent of the unread count
	Employee Chat derives from `Chat Participant.last_read_on`."""
	if not chat_names:
		return {}

	rows = frappe.db.sql(
		"""
		select c.name as chat, count(*) as unread
		from `tabWhatsApp Chat` c
		join `tabWhatsApp Message` m
			on m.whatsapp_account = c.whatsapp_account and m.`from` = c.phone
		left join `tabWhatsApp Chat Read` r
			on r.chat = c.name and r.user = %(user)s
		where c.name in %(chats)s
			and m.type = 'Incoming'
			and m.creation > %(window)s
			and (r.last_read_on is null or m.creation > r.last_read_on)
		group by c.name
		""",
		{
			"user": frappe.session.user,
			"chats": tuple(chat_names),
			"window": add_days(nowdate(), -UNREAD_WINDOW_DAYS),
		},
		as_dict=True,
	)
	return {r.chat: r.unread for r in rows}


def _set_chat_state(chat, values):
	"""Upsert the current user's state row (read cursor / mute) for a conversation."""
	name = f"{chat}::{frappe.session.user}"
	if frappe.db.exists("WhatsApp Chat Read", name):
		frappe.db.set_value("WhatsApp Chat Read", name, values, update_modified=False)
	else:
		frappe.get_doc(
			dict(
				{
					"doctype": "WhatsApp Chat Read",
					"chat": chat,
					"user": frappe.session.user,
				},
				**values,
			)
		).insert(ignore_permissions=True)
	return name


@frappe.whitelist()
def set_muted(chat, muted):
	"""Mute/unmute a conversation for the current user only — it silences the
	notification sound, nothing else."""
	chat = wa_access.require_chat(chat).name
	muted = 1 if int(muted or 0) else 0
	_set_chat_state(chat, {"muted": muted})
	return {"muted": muted}


def conversation_state(chat):
	"""Finished / obsolete marks of a chat, for the side panel and the list."""
	from erpnext.crm.doctype.whatsapp_chat.whatsapp_chat import is_obsolete

	row = frappe.db.get_value(
		"WhatsApp Chat",
		chat,
		["finished", "finished_on", "finished_by", "archived", "archived_on", "last_message_on"],
		as_dict=True,
	)
	return {
		"finished": row.finished or 0,
		"finished_on": str(row.finished_on) if row.finished_on else None,
		"finished_by": row.finished_by,
		"finished_by_name": frappe.utils.get_fullname(row.finished_by) if row.finished_by else None,
		"archived": row.archived or 0,
		"obsolete": 1 if is_obsolete(row) else 0,
	}


def _set_conversation(chat, values):
	frappe.db.set_value("WhatsApp Chat", chat.name, values, update_modified=False)
	state = conversation_state(chat.name)
	for user in wa_access.users_for_account(chat.whatsapp_account):
		frappe.publish_realtime(
			event="whatsapp_chat_state",
			message={"chat": chat.name, "whatsapp_account": chat.whatsapp_account, **state},
			user=user,
			after_commit=True,
		)
	return state


@frappe.whitelist()
def set_finished(chat, finished=1):
	"""Mark the conversation finished (the issue is resolved) or open it again. The
	customer's next message opens it by itself."""
	chat = wa_access.require_chat(chat, write=True)
	if int(finished or 0):
		values = {"finished": 1, "finished_on": now(), "finished_by": frappe.session.user}
	else:
		values = {"finished": 0, "finished_on": None, "finished_by": None}
	return _set_conversation(chat, values)


@frappe.whitelist()
def set_obsolete(chat, obsolete=1):
	"""Move the chat to the collapsed obsolete group of the list, or back. Any new message
	brings it back by itself."""
	chat = wa_access.require_chat(chat, write=True)
	if int(obsolete or 0):
		values = {"archived": 1, "archived_on": now()}
	else:
		values = {"archived": 0, "archived_on": None}
		# A finished chat that went quiet long ago would stay in the group otherwise.
		if chat.finished:
			values.update({"finished": 0, "finished_on": None, "finished_by": None})
	return _set_conversation(chat, values)


@frappe.whitelist()
def mark_read(chat, upto=None):
	"""Advance the current user's read cursor for this conversation.

	`upto` (a message creation timestamp) marks read only up to a specific message — used
	by progressive read-on-scroll so messages still below the fold stay unread. The cursor
	only ever moves forward. With no `upto` the whole conversation is marked read as of now."""
	chat = wa_access.require_chat(chat).name
	ts = upto or now()

	current = frappe.db.get_value("WhatsApp Chat Read", f"{chat}::{frappe.session.user}", "last_read_on")
	if current and str(current) >= str(ts):
		# Never move the cursor backwards.
		return {"last_read_on": str(current)}

	_set_chat_state(chat, {"last_read_on": ts})

	# The customer sees blue ticks only when someone who answers the number has read it;
	# a spectator reading along leaves the messages unread on their side.
	chat_doc = frappe.get_doc("WhatsApp Chat", chat)
	if wa_access.can_access(chat_doc.whatsapp_account, write=True):
		from erpnext.crm.whatsapp_meta import queue_read_receipt

		queue_read_receipt(chat_doc, upto=ts)

	# Other tabs of the same user (chat page, chat bubble) drop their badge at once.
	frappe.publish_realtime(
		event="whatsapp_read",
		message={"chat": chat, "last_read_on": ts},
		user=frappe.session.user,
		after_commit=True,
	)
	return {"last_read_on": str(ts)}


# Meta keeps "typing…" up to 25 s after one indicator; re-sending sooner is wasted calls.
META_TYPING_TTL = 20


@frappe.whitelist()
def notify_typing(chat):
	"""A manager is typing: colleagues on the same number see who, and the customer sees
	"typing…" (which, on Meta's side, also marks their messages read)."""
	chat = wa_access.require_chat(chat, write=True)
	me = frappe.session.user
	payload = {"chat": chat.name, "user": me, "full_name": frappe.utils.get_fullname(me)}
	for user in wa_access.users_for_account(chat.whatsapp_account):
		if user != me:
			frappe.publish_realtime(event="whatsapp_typing", message=payload, user=user)

	key = f"whatsapp_typing:{chat.name}"
	if frappe.cache.get_value(key):
		return
	frappe.cache.set_value(key, 1, expires_in_sec=META_TYPING_TTL)
	from erpnext.crm.whatsapp_meta import queue_read_receipt

	queue_read_receipt(chat, typing=True)


def _number_info(chat):
	"""Which business number a chat runs on and who answers it — for the chat header
	and context panel."""
	label = wa_access.account_labels().get(chat.whatsapp_account, {})
	return {
		"whatsapp_account": chat.whatsapp_account,
		"number_label": label.get("label") or chat.whatsapp_account,
		"account_name": label.get("account_name") or chat.whatsapp_account,
		"verified_name": label.get("verified_name"),
		"number_image": label.get("profile_image"),
		"read_only": 0 if wa_access.can_access(chat.whatsapp_account, write=True) else 1,
		"managers": wa_access.responsible_users(chat.whatsapp_account),
	}


@frappe.whitelist()
def get_chat_context(chat):
	"""Everything linked to this dialog: explicit links + entities derived from the
	resolved Contact, plus the business number and its responsible managers."""
	chat = wa_access.require_chat(chat)

	seen = set()
	linked = []
	for row in chat.links:
		key = (row.link_doctype, row.link_name)
		if row.link_name and key not in seen:
			seen.add(key)
			linked.append({"doctype": row.link_doctype, "name": row.link_name, "label": row.link_name})

	derived = []
	if chat.contact:
		for doctype, fieldname in DERIVED_SOURCES:
			for rec in frappe.get_all(doctype, filters={fieldname: chat.contact}, pluck="name"):
				key = (doctype, rec)
				if key not in seen:
					seen.add(key)
					derived.append({"doctype": doctype, "name": rec, "label": rec})

	return {
		"contact": chat.contact,
		"linked": linked,
		"derived": derived,
		"conversation": conversation_state(chat.name),
		**_number_info(chat),
	}


@frappe.whitelist()
def find_chats(phone):
	"""The caller's chats with this customer number, newest first — one per business number."""
	_require_wa_access()
	phone = _digits(phone)
	if not phone:
		return []
	accounts = list(wa_access.accounts_for())
	return frappe.get_all(
		"WhatsApp Chat",
		filters={"phone": phone, "whatsapp_account": ["in", accounts]},
		fields=["name", "whatsapp_account", "title"],
		order_by="last_message_on desc",
	)


@frappe.whitelist()
def start_chat(phone, account=None):
	"""Open (creating if needed) the chat with `phone` on a business number the caller
	answers. Without `account` the caller's only writable number is used."""
	_require_wa_access("create")
	phone = _digits(phone)
	if not phone:
		frappe.throw(_("Enter a phone number"))
	if not account:
		writable = sorted(wa_access.accounts_for(write=True))
		if len(writable) != 1:
			frappe.throw(_("Choose the WhatsApp number to write from"))
		account = writable[0]
	wa_access.require_account(account, write=True)

	from erpnext.crm.doctype.whatsapp_chat.whatsapp_chat import get_or_create_chat

	return get_or_create_chat(account, phone).name


URL_RE = re.compile(r"https?://[^\s<>\"']+")

# Content types whose attachment belongs in the "Media" tab of the overview; anything
# else with an attachment is a document/file.
MEDIA_CONTENT_TYPES = ("image", "sticker", "video", "audio")


def link_attachment_to_chat(file_url, chat_name):
	"""Point a message attachment at the WhatsApp Chat, so a conversation's media is
	reachable from the dialog itself and not only from the individual message."""
	if not file_url or not chat_name:
		return
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		return
	frappe.db.set_value(
		"File",
		name,
		{"attached_to_doctype": "WhatsApp Chat", "attached_to_name": chat_name},
		update_modified=False,
	)


@frappe.whitelist()
def get_chat_overview(chat, limit=200):
	"""Chat overview: who the dialog is with, what is linked to it, and everything
	shared in it — media, documents and links."""
	chat = wa_access.require_chat(chat)
	phone = chat.phone
	context = get_chat_context(chat.name)
	limit = int(limit)

	rows = frappe.db.sql(
		"""
		select name, type, `from`, `to`, message, profile_name, content_type, attach, creation
		from `tabWhatsApp Message`
		where whatsapp_account = %(account)s and (`from` = %(phone)s or `to` = %(phone)s)
		order by creation desc
		limit %(limit)s
		""",
		{"account": chat.whatsapp_account, "phone": phone, "limit": limit * 4},
		as_dict=True,
	)

	media, files, links = [], [], []
	for r in rows:
		out = r.type == "Outgoing"
		item = {
			"name": r.name,
			"content_type": r.content_type,
			"attach": r.attach,
			"caption": re.sub(r"<[^>]*>", "", r.message or "").strip(),
			"sender_name": _("You") if out else (r.profile_name or phone),
			"creation": str(r.creation),
		}
		if r.attach:
			if r.content_type in MEDIA_CONTENT_TYPES:
				if len(media) < limit:
					media.append(item)
			elif len(files) < limit:
				meta = frappe.db.get_value(
					"File", {"file_url": r.attach}, ["file_name", "file_size"], as_dict=True
				)
				item["file_name"] = (meta.file_name if meta else None) or r.attach.split("/")[-1]
				item["file_size"] = meta.file_size if meta else None
				files.append(item)
		for url in URL_RE.findall(item["caption"]):
			if len(links) < limit:
				links.append(dict(item, url=url))

	muted = frappe.db.get_value("WhatsApp Chat Read", f"{chat.name}::{frappe.session.user}", "muted")

	return {
		"chat": chat.name,
		"phone": phone,
		"title": chat.title or phone,
		"muted": muted or 0,
		"contact": context.get("contact"),
		"managers": context.get("managers", []),
		"number_label": context.get("number_label"),
		"account_name": context.get("account_name"),
		"verified_name": context.get("verified_name"),
		"number_image": context.get("number_image"),
		"whatsapp_account": chat.whatsapp_account,
		"read_only": context.get("read_only"),
		"linked": context.get("linked", []),
		"derived": context.get("derived", []),
		"media": media,
		"files": files,
		"links": links,
	}


@frappe.whitelist()
def link_entity(chat, link_doctype, link_name):
	chat = wa_access.require_chat(chat, write=True)
	if link_doctype not in LINKABLE_DOCTYPES:
		frappe.throw(_("Cannot link {0}").format(link_doctype))
	if chat.add_link(link_doctype, link_name):
		chat.save(ignore_permissions=True)
	return get_chat_context(chat.name)


@frappe.whitelist()
def unlink_entity(chat, link_doctype, link_name):
	chat = wa_access.require_chat(chat, write=True)
	chat.links = [r for r in chat.links if not (r.link_doctype == link_doctype and r.link_name == link_name)]
	chat.save(ignore_permissions=True)
	return get_chat_context(chat.name)


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
	_require_wa_access()
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
	"""Recent messages with a number across the caller's business numbers, oldest-first,
	for the read-only form panel. Each message carries the number it went through."""
	_require_wa_access()
	phone = _digits(phone)
	if not phone:
		return []
	labels = wa_access.account_labels()
	rows = []
	for chat in find_chats(phone):
		for m in get_messages(chat.name, limit=limit):
			m["number_label"] = labels.get(chat.whatsapp_account, {}).get("label") or chat.whatsapp_account
			rows.append(m)
	rows.sort(key=lambda m: m["creation"])
	return rows[-int(limit) :]


MESSAGE_FIELDS = [
	"name",
	"type",
	"`from`",
	"`to`",
	"message",
	"profile_name",
	"creation",
	"status",
	"status_error",
	"content_type",
	"attach",
	"message_id",
	"reply_to_message_id",
	"is_reply",
	"owner",
]


@frappe.whitelist()
def get_messages(chat, before=None, after=None, limit=50):
	"""Keyset-paginated history for one conversation, oldest-first in the returned
	batch. Pass `before` (creation of the oldest loaded message) to page backwards,
	or `after` (creation of the newest loaded message) to fetch what arrived since."""
	chat = wa_access.require_chat(chat)

	limit = int(limit)
	params = {"phone": chat.phone, "account": chat.whatsapp_account, "limit": limit}

	# An OR over `from`/`to` degrades into an index_merge plus a filesort over the
	# whole conversation. Running the two sides as separate index range scans lets
	# (whatsapp_account, from|to, creation) satisfy the ordering, so each branch reads
	# at most `limit` rows straight off the index.
	keyset = ""
	if before:
		keyset += " and creation < %(before)s"
		params["before"] = before
	if after:
		keyset += " and creation > %(after)s"
		params["after"] = after

	direction = "asc" if after else "desc"
	fields = ", ".join(MESSAGE_FIELDS)
	branch = (
		"(select {fields} from `tabWhatsApp Message`"
		" where whatsapp_account = %(account)s and `{side}` = %(phone)s{keyset}"
		" order by creation {direction} limit %(limit)s)"
	)
	rows = frappe.db.sql(
		"{outgoing} union all {incoming} order by creation {direction} limit %(limit)s".format(
			outgoing=branch.format(fields=fields, side="from", keyset=keyset, direction=direction),
			incoming=branch.format(fields=fields, side="to", keyset=keyset, direction=direction),
			direction=direction,
		),
		params,
		as_dict=True,
	)

	# A number messaging itself would match both branches.
	seen = set()
	rows = [r for r in rows if not (r["name"] in seen or seen.add(r["name"]))]

	# Several managers answer one number: outgoing messages say who sent them.
	names = {}
	for r in rows:
		if r["type"] == "Outgoing":
			if r["owner"] not in names:
				names[r["owner"]] = frappe.utils.get_fullname(r["owner"])
			r["sender_name"] = names[r["owner"]]

	if not after:
		rows.reverse()
	return rows


def _insert_outgoing(chat, fields):
	"""Insert an Outgoing WhatsApp Message through the chat's business number (the
	fork's before_insert dispatches it to Meta)."""
	doc = frappe.get_doc(
		{
			"doctype": "WhatsApp Message",
			"type": "Outgoing",
			"message_type": "Manual",
			"whatsapp_account": chat.whatsapp_account,
			"to": chat.phone,
			**fields,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def send_text(chat, message, reply_to_message_id=None):
	"""Send a plain text message, optionally as a reply to another message."""
	chat = wa_access.require_chat(chat, write=True)
	if not (message or "").strip():
		frappe.throw(_("Nothing to send"))
	fields = {"message": message, "content_type": "text"}
	if reply_to_message_id:
		fields["is_reply"] = 1
		fields["reply_to_message_id"] = reply_to_message_id
	return _insert_outgoing(chat, fields)


# Audio containers Meta's Cloud API accepts as-is. Anything else (notably webm, which is
# all Chrome's MediaRecorder can produce) is transcoded to ogg/opus before sending.
META_AUDIO_EXT = {"aac", "m4a", "mp4", "amr", "mp3", "mpeg", "ogg", "opus"}


def _ensure_whatsapp_audio(attach):
	"""Return a Meta-compatible audio file URL for `attach`, transcoding to ogg/opus with
	ffmpeg when the uploaded file is in a container Meta rejects. On any failure the
	original url is returned unchanged so the send still attempts (and surfaces Meta's
	own error) rather than being silently dropped."""
	import os
	import subprocess
	import tempfile

	ext = (attach or "").rsplit(".", 1)[-1].lower()
	if ext in META_AUDIO_EXT:
		return attach
	try:
		file_doc = frappe.get_doc("File", {"file_url": attach})
		src_path = file_doc.get_full_path()
	except Exception:
		return attach  # remote / unknown file — let Meta decide

	out_fd, out_path = tempfile.mkstemp(suffix=".ogg")
	os.close(out_fd)
	try:
		subprocess.run(
			[
				"ffmpeg",
				"-y",
				"-i",
				src_path,
				"-vn",
				"-c:a",
				"libopus",
				"-b:a",
				"32k",
				"-ar",
				"48000",
				out_path,
			],
			check=True,
			capture_output=True,
			timeout=120,
		)
		with open(out_path, "rb") as f:
			content = f.read()
	except Exception as e:
		frappe.log_error(title="WhatsApp audio transcode failed", message=str(e))
		return attach
	finally:
		try:
			os.remove(out_path)
		except OSError:
			pass

	from frappe.utils.file_manager import save_file

	base = (file_doc.file_name or "voice").rsplit(".", 1)[0]
	new_file = save_file(
		base + ".ogg",
		content,
		None,
		None,
		folder="Home/Attachments",
		is_private=file_doc.is_private,
		decode=False,
	)
	return new_file.file_url


@frappe.whitelist()
def send_media(chat, attach, content_type, caption=None, reply_to_message_id=None):
	"""Send an image/video/audio/document by its uploaded file URL."""
	chat = wa_access.require_chat(chat, write=True)
	if not attach:
		frappe.throw(_("Nothing to send"))
	if content_type not in ("image", "video", "audio", "document"):
		frappe.throw(_("Unsupported media type"))
	if content_type == "audio":
		attach = _ensure_whatsapp_audio(attach)
	fields = {
		"attach": attach,
		"content_type": content_type,
		"message": caption or "",
	}
	if reply_to_message_id:
		fields["is_reply"] = 1
		fields["reply_to_message_id"] = reply_to_message_id
	return _insert_outgoing(chat, fields)


@frappe.whitelist()
def send_reaction(chat, message_id, emoji):
	"""React to a message with an emoji (empty emoji removes the reaction)."""
	chat = wa_access.require_chat(chat, write=True)
	if not message_id:
		frappe.throw(_("Nothing to send"))
	return _insert_outgoing(
		chat,
		{
			"content_type": "reaction",
			"message": emoji or "",
			"reply_to_message_id": message_id,
		},
	)


def _is_meta_sample_template(name):
	"""Meta's built-in sample/system templates (hello_world, Jasper's Market demos,
	the auto-created 3p integration test template) can't be sent from a real number
	(error 131058) — hide them from the chat template picker."""
	n = (name or "").lower()
	return n in ("hello_world", "3p_direct_integration_test_template") or n.startswith(
		("jaspers_market", "sample_")
	)


@frappe.whitelist()
def list_templates():
	"""Approved WhatsApp templates that can be sent from the chat, with body-parameter
	metadata so the UI can prompt for each placeholder. Templates are the only way to
	message a number outside Meta's 24h customer-service window."""
	_require_wa_access()
	rows = frappe.get_all(
		"WhatsApp Templates",
		filters={"status": "APPROVED"},
		fields=["name", "template_name", "language_code", "header_type", "field_names", "sample_values"],
		order_by="template_name asc",
	)
	rows = [r for r in rows if not _is_meta_sample_template(r.get("template_name"))]
	for r in rows:
		names = r.get("field_names") or r.get("sample_values") or ""
		r["params"] = [p.strip() for p in names.split(",") if p.strip()]
	return rows


@frappe.whitelist()
def send_template(chat, template, body_params=None):
	"""Send an approved template message (bypasses the 24h window). body_params is an
	optional JSON object/dict of placeholder values, in template field order."""
	chat = wa_access.require_chat(chat, write=True)
	if not template:
		frappe.throw(_("Nothing to send"))
	fields = {"template": template, "content_type": "text"}
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
	return _insert_outgoing(chat, fields)


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
def create_opportunity(chat):
	"""Create an Opportunity for this dialog and link it back into the chat."""
	chat = wa_access.require_chat(chat, write=True)
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
def create_todo(chat, description):
	"""Create a task (ToDo) referencing this dialog."""
	chat = wa_access.require_chat(chat, write=True)
	todo = frappe.new_doc("ToDo")
	todo.description = description
	todo.reference_type = "Contact" if chat.contact else "WhatsApp Chat"
	todo.reference_name = chat.contact or chat.name
	todo.insert(ignore_permissions=True)
	return {"doctype": "ToDo", "name": todo.name}


@frappe.whitelist()
def create_note(chat, title, content=None):
	"""Create a Note for this dialog."""
	wa_access.require_chat(chat, write=True)
	note = frappe.new_doc("Note")
	note.title = title
	if content:
		note.content = content
	note.insert(ignore_permissions=True)
	return {"doctype": "Note", "name": note.name}


@frappe.whitelist()
def create_event(chat, subject, starts_on):
	"""Create a calendar Event linked to this dialog's contact."""
	chat = wa_access.require_chat(chat, write=True)
	event = frappe.new_doc("Event")
	event.subject = subject
	event.starts_on = starts_on
	event.event_type = "Private"
	if chat.contact:
		event.append("links", {"link_doctype": "Contact", "link_name": chat.contact})
	event.insert(ignore_permissions=True)
	return {"doctype": "Event", "name": event.name}
