import json
import re

import frappe
from frappe import _
from frappe.utils import add_days, now, nowdate

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
	"""Guard every WhatsApp Chat endpoint: the caller must hold the matching
	permission on WhatsApp Message (read for viewing, create for sending)."""
	if not frappe.has_permission("WhatsApp Message", ptype):
		frappe.throw(_("Not permitted to access WhatsApp chats"), frappe.PermissionError)


def notify_new_message(doc, method=None):
	"""On every WhatsApp Message: keep the conversation object in sync and push a
	realtime event so the WhatsApp Chat page updates instantly."""
	number = doc.get("from") if doc.get("type") == "Incoming" else doc.get("to")

	try:
		from erpnext.crm.doctype.whatsapp_chat.whatsapp_chat import sync_chat_from_message

		chat_name = sync_chat_from_message(doc)
		# The media file the fork downloaded is attached to the message; re-point it at
		# the conversation so the chat overview (and the chat form) owns it.
		if doc.get("attach"):
			link_attachment_to_chat(doc.get("attach"), chat_name)
	except Exception:
		frappe.log_error(title="WhatsApp Chat sync failed", message=frappe.get_traceback())

	payload = {"name": doc.name, "number": number, "type": doc.get("type")}
	# Fan out only to users who may read WhatsApp Messages — a global broadcast would
	# leak customer numbers to every logged-in desk user.
	for user in _users_with_wa_access():
		frappe.publish_realtime(
			event="whatsapp_message",
			message=payload,
			user=user,
			after_commit=True,
		)


def _users_with_wa_access():
	"""Enabled users holding a role that can read WhatsApp Message."""
	roles = frappe.get_all(
		"Custom DocPerm",
		filters={"parent": "WhatsApp Message", "read": 1},
		pluck="role",
	) or []
	roles += frappe.get_all(
		"DocPerm",
		filters={"parent": "WhatsApp Message", "read": 1},
		pluck="role",
	) or []
	if not roles:
		return []

	users = frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": ["in", list(set(roles))]},
		pluck="parent",
	)
	users = set(users) | {"Administrator"}
	enabled = set(
		frappe.get_all("User", filters={"enabled": 1, "name": ["in", list(users)]}, pluck="name")
	)
	return enabled


def _ensure_chats():
	"""Backfill WhatsApp Chat objects for any conversation that has messages but no
	chat yet (e.g. threads that predate the conversation model)."""
	from erpnext.crm.doctype.whatsapp_chat.whatsapp_chat import sync_chat_from_message

	# The chat list is polled every few seconds — keep the backfill scan off the hot
	# path once it has run.
	if frappe.cache().get_value("whatsapp_chats_backfilled"):
		return

	numbers = {
		row[0]
		for row in frappe.db.sql(
			"""
			select distinct if(type = 'Incoming', `from`, `to`) as number
			from `tabWhatsApp Message`
			"""
		)
	}
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
	# New conversations get their chat from notify_new_message, so the scan only
	# needs to run once per cache lifetime.
	frappe.cache().set_value("whatsapp_chats_backfilled", 1, expires_in_sec=3600)


@frappe.whitelist()
def get_chats(manager=None):
	"""Return the conversation list, optionally filtered by an assigned manager."""
	_require_wa_access()
	_ensure_chats()

	chats = frappe.get_all(
		"WhatsApp Chat",
		fields=[
			"name",
			"phone",
			"contact",
			"title",
			"last_message_on",
			"last_preview",
			"last_content_type",
		],
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

	from erpnext.crm.doctype.whatsapp_chat.whatsapp_chat import backfill_previews

	# The preview is denormalised onto the chat by sync_chat_from_message(), so the
	# list costs one query instead of one per conversation. Rows that predate those
	# fields are filled in once, on first read.
	backfill_previews(chats)

	unread = _unread_counts([c["phone"] for c in chats if c.get("phone")])
	states = frappe.get_all(
		"WhatsApp Chat Read",
		filters={"user": frappe.session.user},
		fields=["chat", "muted", "last_read_on"],
	)
	muted = {s.chat for s in states if s.muted}
	# The client needs its own read cursor to place the "New messages" divider and scroll
	# to the first unread message on open.
	cursor = {s.chat: str(s.last_read_on) if s.last_read_on else None for s in states}
	for c in chats:
		c["preview"] = c.pop("last_preview", None) or ""
		c["preview_content_type"] = c.pop("last_content_type", None)
		if not c.get("title"):
			c["title"] = c["phone"]
		c["unread"] = unread.get(c["phone"], 0)
		c["muted"] = 1 if c["name"] in muted else 0
		c["my_last_read"] = cursor.get(c["name"])
	return chats


# Unread counting only looks this far back: a conversation nobody ever opened would
# otherwise report its entire history as unread, and count it on every list poll.
UNREAD_WINDOW_DAYS = 90


def _unread_counts(phones):
	"""Incoming messages newer than the current user's read cursor, per conversation.

	One grouped query for the whole list — the read cursor lives in `WhatsApp Chat Read`
	(one row per user per chat), so this is the WhatsApp equivalent of the unread count
	Employee Chat derives from `Chat Participant.last_read_on`."""
	if not phones:
		return {}

	rows = frappe.db.sql(
		"""
		select m.`from` as phone, count(*) as unread
		from `tabWhatsApp Message` m
		left join `tabWhatsApp Chat Read` r
			on r.chat = m.`from` and r.user = %(user)s
		where m.type = 'Incoming'
			and m.`from` in %(phones)s
			and m.creation > %(window)s
			and (r.last_read_on is null or m.creation > r.last_read_on)
		group by m.`from`
		""",
		{
			"user": frappe.session.user,
			"phones": tuple(phones),
			"window": add_days(nowdate(), -UNREAD_WINDOW_DAYS),
		},
		as_dict=True,
	)
	return {r.phone: r.unread for r in rows}


def _set_chat_state(phone, values):
	"""Upsert the current user's state row (read cursor / mute) for a conversation."""
	chat = frappe.db.exists("WhatsApp Chat", {"phone": _digits(phone)})
	if not chat:
		return None

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
def set_muted(phone, muted):
	"""Mute/unmute a conversation for the current user only — it silences the
	notification sound, nothing else."""
	_require_wa_access()
	muted = 1 if int(muted or 0) else 0
	if not _set_chat_state(phone, {"muted": muted}):
		return {}
	return {"muted": muted}


@frappe.whitelist()
def mark_read(phone, upto=None):
	"""Advance the current user's read cursor for this conversation.

	`upto` (a message creation timestamp) marks read only up to a specific message — used
	by progressive read-on-scroll so messages still below the fold stay unread. The cursor
	only ever moves forward. With no `upto` the whole conversation is marked read as of now."""
	_require_wa_access()
	phone = _digits(phone)
	ts = upto or now()

	chat = frappe.db.exists("WhatsApp Chat", {"phone": phone})
	if chat:
		current = frappe.db.get_value(
			"WhatsApp Chat Read", f"{chat}::{frappe.session.user}", "last_read_on"
		)
		if current and str(current) >= str(ts):
			# Never move the cursor backwards.
			return {"last_read_on": str(current)}

	if not _set_chat_state(phone, {"last_read_on": ts}):
		return {}

	# Other tabs of the same user (chat page, chat bubble) drop their badge at once.
	frappe.publish_realtime(
		event="whatsapp_read",
		message={"phone": phone, "last_read_on": ts},
		user=frappe.session.user,
		after_commit=True,
	)
	return {"last_read_on": str(ts)}


@frappe.whitelist()
def get_managers():
	"""Users who can own WhatsApp conversations (Sales / System roles)."""
	_require_wa_access()
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
	_require_wa_access()
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
def get_chat_overview(phone, limit=200):
	"""Chat overview: who the dialog is with, what is linked to it, and everything
	shared in it — media, documents and links."""
	_require_wa_access()
	phone = _digits(phone)
	context = get_chat_context(phone)
	chat = _chat_for_phone(phone)
	limit = int(limit)

	rows = frappe.db.sql(
		"""
		select name, type, `from`, `to`, message, profile_name, content_type, attach, creation
		from `tabWhatsApp Message`
		where `from` = %(phone)s or `to` = %(phone)s
		order by creation desc
		limit %(limit)s
		""",
		{"phone": phone, "limit": limit * 4},
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

	muted = frappe.db.get_value(
		"WhatsApp Chat Read", f"{chat.name}::{frappe.session.user}", "muted"
	) if chat else 0

	return {
		"phone": phone,
		"title": (chat.title if chat else None) or phone,
		"muted": muted or 0,
		"contact": context.get("contact"),
		"managers": context.get("managers", []),
		"linked": context.get("linked", []),
		"derived": context.get("derived", []),
		"media": media,
		"files": files,
		"links": links,
	}


@frappe.whitelist()
def link_entity(phone, link_doctype, link_name):
	_require_wa_access("create")
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
	_require_wa_access("create")
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
	"""Recent messages for a number, oldest-first, for the read-only form panel."""
	_require_wa_access()
	phone = _digits(phone)
	if not phone:
		return []
	return get_messages(phone, limit=limit)


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
]


@frappe.whitelist()
def get_messages(phone, before=None, after=None, limit=50):
	"""Keyset-paginated history for one conversation, oldest-first in the returned
	batch. Pass `before` (creation of the oldest loaded message) to page backwards,
	or `after` (creation of the newest loaded message) to fetch what arrived since."""
	_require_wa_access()
	phone = _digits(phone)
	if not phone:
		return []

	limit = int(limit)
	params = {"phone": phone, "limit": limit}

	# An OR over `from`/`to` degrades into an index_merge plus a filesort over the
	# whole conversation. Running the two sides as separate index range scans lets
	# (from|to, creation) satisfy the ordering, so each branch reads at most `limit`
	# rows straight off the index.
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
		"(select {fields} from `tabWhatsApp Message` where `{side}` = %(phone)s{keyset}"
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

	if not after:
		rows.reverse()
	return rows


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
	_require_wa_access("create")
	phone = _digits(phone)
	if not phone or not (message or "").strip():
		frappe.throw(_("Nothing to send"))
	fields = {"to": phone, "message": message, "content_type": "text"}
	if reply_to_message_id:
		fields["is_reply"] = 1
		fields["reply_to_message_id"] = reply_to_message_id
	return _insert_outgoing(fields)


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
				"ffmpeg", "-y", "-i", src_path,
				"-vn", "-c:a", "libopus", "-b:a", "32k", "-ar", "48000",
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
def send_media(phone, attach, content_type, caption=None, reply_to_message_id=None):
	"""Send an image/video/audio/document by its uploaded file URL."""
	_require_wa_access("create")
	phone = _digits(phone)
	if not phone or not attach:
		frappe.throw(_("Nothing to send"))
	if content_type not in ("image", "video", "audio", "document"):
		frappe.throw(_("Unsupported media type"))
	if content_type == "audio":
		attach = _ensure_whatsapp_audio(attach)
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
	_require_wa_access("create")
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
def send_template(phone, template, body_params=None):
	"""Send an approved template message (bypasses the 24h window). body_params is an
	optional JSON object/dict of placeholder values, in template field order."""
	_require_wa_access("create")
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
	_require_wa_access("create")
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
	_require_wa_access("create")
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
	_require_wa_access("create")
	note = frappe.new_doc("Note")
	note.title = title
	if content:
		note.content = content
	note.insert(ignore_permissions=True)
	return {"doctype": "Note", "name": note.name}


@frappe.whitelist()
def create_event(phone, subject, starts_on):
	"""Create a calendar Event linked to this dialog's contact."""
	_require_wa_access("create")
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
	_require_wa_access("create")
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
