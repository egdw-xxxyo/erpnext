# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Backend endpoints for the internal Employee Chat desk page.

Storage is deliberately compact: a `Chat Thread` aggregate holds the participant
list (child rows) and last-message metadata, while every message is a flat, raw
`Chat Message` row queried directly (no per-message document overhead, no form).

Privacy is enforced here, in every endpoint, via `_require_participant()` — the raw
`frappe.db` reads bypass the `permission_query_conditions` guards, so the endpoint is
the real gate. Realtime is delivered only to each participant's private `user:` room,
never site-wide.
"""

import json
import re

import frappe
from frappe import _
from frappe.utils import now

URL_RE = re.compile(r"https?://[^\s<>\"']+")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_thread(thread):
	return frappe.get_doc("Chat Thread", thread)


def _require_participant(thread):
	"""Return the Chat Thread doc, or raise PermissionError if the current user is not a
	participant. Administrator is allowed through for support/debugging."""
	doc = _get_thread(thread)
	if frappe.session.user != "Administrator" and not doc.is_participant(frappe.session.user):
		frappe.throw(_("You are not a participant of this chat"), frappe.PermissionError)
	return doc


def _participant_users(thread_doc):
	return [p.user for p in thread_doc.participants if p.user]


def _fanout(thread_doc, event, message):
	"""Emit a realtime event to every participant's private user room."""
	for user in _participant_users(thread_doc):
		frappe.publish_realtime(event=event, message=message, user=user, after_commit=True)


def _user_name(user):
	return frappe.db.get_value("User", user, "full_name") or user


def _preview_text(content_type, message, attach, is_encrypted=False):
	if is_encrypted:
		# The server cannot read the body — and must not store a hint about it either.
		return "🔒 " + _("Encrypted message")
	if content_type == "image":
		return "📷 " + _("Photo")
	if content_type == "file":
		fname = (attach or "").split("/")[-1]
		return "📎 " + (fname or _("File"))
	return (message or "").strip()


def link_attachment_to_thread(file_url, thread):
	"""Point the uploaded File at the Chat Thread, so every attachment of a chat is
	reachable from the thread itself (attachment sidebar, chat overview) instead of
	floating unattached in Home/Attachments."""
	if not file_url:
		return
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		return
	frappe.db.set_value(
		"File",
		name,
		{"attached_to_doctype": "Chat Thread", "attached_to_name": thread},
		update_modified=False,
	)


def _message_payload(row, name_cache=None):
	"""Shape a Chat Message row (dict or doc) into the payload the page renders."""
	name_cache = name_cache if name_cache is not None else {}

	def resolve_name(user):
		if user not in name_cache:
			name_cache[user] = _user_name(user)
		return name_cache[user]

	reactions = row.get("reactions")
	try:
		reactions = json.loads(reactions) if reactions else {}
	except (ValueError, TypeError):
		reactions = {}

	reply_preview = None
	if row.get("reply_to"):
		rt = frappe.db.get_value(
			"Chat Message",
			row["reply_to"],
			["sender", "content_type", "message", "attach", "is_encrypted", "enc_iv"],
			as_dict=True,
		)
		if rt:
			reply_preview = {
				"name": row["reply_to"],
				"sender": rt.sender,
				"sender_name": resolve_name(rt.sender),
				"content_type": rt.content_type,
				"is_encrypted": rt.is_encrypted,
			}
			if rt.is_encrypted:
				# No server-side preview is possible; ship the ciphertext and let the
				# recipient's browser shorten it after decryption.
				reply_preview["ciphertext"] = rt.message
				reply_preview["enc_iv"] = rt.enc_iv
				reply_preview["text"] = ""
			else:
				reply_preview["text"] = _preview_text(rt.content_type, rt.message, rt.attach)[:120]

	return {
		"name": row.get("name"),
		"thread": row.get("thread"),
		"sender": row.get("sender"),
		"sender_name": resolve_name(row.get("sender")),
		"content_type": row.get("content_type") or "text",
		"message": row.get("message") or "",
		"attach": row.get("attach"),
		"reply_to": row.get("reply_to"),
		"reply_preview": reply_preview,
		"reactions": reactions,
		"is_encrypted": row.get("is_encrypted") or 0,
		"enc_iv": row.get("enc_iv"),
		"enc_version": row.get("enc_version") or 0,
		"creation": str(row.get("creation")),
	}


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_threads():
	"""Threads the current user participates in, newest-activity first, each with a
	preview, the other participant(s), and an unread count."""
	me = frappe.session.user
	names = frappe.get_all(
		"Chat Participant",
		filters={"parenttype": "Chat Thread", "user": me},
		fields=["parent", "last_read_on"],
	)
	last_read = {r.parent: r.last_read_on for r in names}
	if not last_read:
		return []

	threads = frappe.get_all(
		"Chat Thread",
		filters={"name": ["in", list(last_read.keys())]},
		fields=[
			"name",
			"thread_type",
			"title",
			"is_secret",
			"last_message_on",
			"last_message_preview",
			"last_sender",
		],
		order_by="last_message_on desc",
	)

	for t in threads:
		parts = frappe.get_all(
			"Chat Participant",
			filters={"parenttype": "Chat Thread", "parent": t["name"]},
			fields=["user", "employee_name", "role", "last_read_on", "muted"],
		)
		t["participants"] = parts
		mine = next((p for p in parts if p.user == me), None)
		t["muted"] = mine.muted if mine else 0
		others = [p for p in parts if p.user != me]
		if t["thread_type"] == "Direct" and others:
			o = others[0]
			t["display_title"] = o.employee_name or _user_name(o.user)
			t["other_user"] = o.user
		else:
			t["display_title"] = t["title"] or ", ".join(
				p.employee_name or p.user for p in others
			)
			t["other_user"] = None

		unread_filters = [
			["Chat Message", "thread", "=", t["name"]],
			["Chat Message", "sender", "!=", me],
		]
		if last_read[t["name"]]:
			unread_filters.append(["Chat Message", "creation", ">", last_read[t["name"]]])
		t["unread"] = frappe.db.count("Chat Message", unread_filters)

	return threads


@frappe.whitelist()
def create_thread(participant_users, thread_type="Direct", title=None, is_secret=0, thread_keys=None):
	"""Create (or, for direct threads, reuse) a chat thread. `participant_users` is a JSON
	list of user emails; the current user is always added.

	For a secret thread the caller also passes `thread_keys` — the thread key already
	wrapped for each participant in the creator's browser. Server-side we only file them."""
	if isinstance(participant_users, str):
		participant_users = frappe.parse_json(participant_users)
	is_secret = int(is_secret or 0)

	me = frappe.session.user
	users = sorted({u for u in (participant_users or []) if u} | {me})
	if len(users) < 2:
		frappe.throw(_("Pick at least one other person to chat with"))

	if thread_type == "Direct" and len(users) != 2:
		thread_type = "Group"

	if is_secret:
		from erpnext.crm import chat_crypto

		missing = [u for u in users if not chat_crypto.is_enrolled(u)]
		if missing:
			frappe.throw(
				_("These people have not enabled secret chats yet: {0}").format(", ".join(missing))
			)

	if thread_type == "Direct":
		from erpnext.crm.doctype.chat_thread.chat_thread import make_dedup_key

		existing = frappe.db.exists("Chat Thread", {"dedup_key": make_dedup_key(users, is_secret)})
		if existing:
			return {"name": existing, "existing": True, "is_secret": is_secret}

	doc = frappe.new_doc("Chat Thread")
	doc.thread_type = thread_type
	doc.is_secret = is_secret
	doc.title = title if thread_type == "Group" else None
	for u in users:
		emp = frappe.db.get_value(
			"Employee", {"user_id": u}, ["name", "employee_name"], as_dict=True
		)
		doc.append(
			"participants",
			{
				"user": u,
				"employee": emp.name if emp else None,
				"employee_name": emp.employee_name if emp else None,
				"role": "Admin" if u == me else "Member",
			},
		)
	doc.insert(ignore_permissions=True)

	if is_secret and thread_keys:
		from erpnext.crm import chat_crypto

		chat_crypto.grant_thread_key(doc.name, thread_keys)

	return {"name": doc.name, "existing": False, "is_secret": is_secret}


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_messages(thread, before=None, limit=50):
	"""Keyset-paginated message history (oldest-first in the returned batch). Pass the
	`creation` of the oldest loaded message as `before` to page backwards."""
	_require_participant(thread)
	filters = [["Chat Message", "thread", "=", thread]]
	if before:
		filters.append(["Chat Message", "creation", "<", before])

	rows = frappe.db.get_all(
		"Chat Message",
		filters=filters,
		fields=[
			"name",
			"thread",
			"sender",
			"content_type",
			"message",
			"attach",
			"reply_to",
			"reactions",
			"is_encrypted",
			"enc_iv",
			"enc_version",
			"creation",
		],
		order_by="creation desc",
		limit=int(limit),
	)
	rows.reverse()
	name_cache = {}
	return [_message_payload(r, name_cache) for r in rows]


@frappe.whitelist()
def send_message(
	thread, message=None, content_type="text", attach=None, reply_to=None, is_encrypted=0, enc_iv=None
):
	"""Insert a message, update the thread's last-message metadata, and push it to every
	participant's private room.

	In a secret thread `message` must already be ciphertext produced in the sender's
	browser. Plaintext is rejected outright rather than stored — a client-side bug must
	not be able to leak a body into the database."""
	doc = _require_participant(thread)
	is_encrypted = int(is_encrypted or 0)

	if doc.is_secret:
		if not is_encrypted or not enc_iv:
			frappe.throw(_("This chat only accepts encrypted messages"))
		if not (message or "").strip():
			frappe.throw(_("Nothing to send"))
	else:
		if is_encrypted:
			frappe.throw(_("This chat is not a secret chat"))
		if content_type == "text" and not (message or "").strip():
			frappe.throw(_("Nothing to send"))
		if content_type in ("image", "file") and not attach:
			frappe.throw(_("Nothing to send"))

	me = frappe.session.user
	msg = frappe.get_doc(
		{
			"doctype": "Chat Message",
			"thread": thread,
			"sender": me,
			"content_type": content_type,
			"message": message or "",
			"attach": attach,
			"reply_to": reply_to,
			"is_encrypted": is_encrypted,
			"enc_iv": enc_iv,
			"enc_version": 1 if is_encrypted else 0,
		}
	)
	msg.insert(ignore_permissions=True)
	if attach:
		link_attachment_to_thread(attach, thread)

	preview = _preview_text(content_type, message, attach, is_encrypted=is_encrypted)
	frappe.db.set_value(
		"Chat Thread",
		thread,
		{"last_message_on": msg.creation, "last_message_preview": preview[:140], "last_sender": me},
		update_modified=False,
	)

	payload = _message_payload(msg.as_dict())
	_fanout(doc, "chat_message", payload)
	return payload


@frappe.whitelist()
def mark_read(thread):
	"""Mark the thread read up to now for the current user; notify others (seen ticks)."""
	doc = _require_participant(thread)
	me = frappe.session.user
	name = frappe.db.get_value(
		"Chat Participant", {"parenttype": "Chat Thread", "parent": thread, "user": me}, "name"
	)
	if not name:
		return
	ts = now()
	frappe.db.set_value("Chat Participant", name, "last_read_on", ts, update_modified=False)
	_fanout(doc, "chat_seen", {"thread": thread, "user": me, "last_read_on": ts})
	return {"last_read_on": ts}


@frappe.whitelist()
def set_muted(thread, muted):
	"""Mute/unmute a thread for the current user only — it silences the notification
	sound, nothing else (the thread still updates and still counts as unread)."""
	_require_participant(thread)
	name = frappe.db.get_value(
		"Chat Participant",
		{"parenttype": "Chat Thread", "parent": thread, "user": frappe.session.user},
		"name",
	)
	if not name:
		return {}
	muted = 1 if int(muted or 0) else 0
	frappe.db.set_value("Chat Participant", name, "muted", muted, update_modified=False)
	return {"muted": muted}


@frappe.whitelist()
def set_reaction(message, emoji):
	"""Add the current user's reaction to a message and broadcast the new reaction map."""
	return _mutate_reaction(message, emoji, add=True)


@frappe.whitelist()
def clear_reaction(message, emoji):
	"""Remove the current user's reaction from a message."""
	return _mutate_reaction(message, emoji, add=False)


def _mutate_reaction(message, emoji, add):
	thread = frappe.db.get_value("Chat Message", message, "thread")
	if not thread:
		frappe.throw(_("Message not found"))
	doc = _require_participant(thread)
	me = frappe.session.user

	raw = frappe.db.get_value("Chat Message", message, "reactions")
	try:
		reactions = json.loads(raw) if raw else {}
	except (ValueError, TypeError):
		reactions = {}

	users = set(reactions.get(emoji, []))
	if add:
		users.add(me)
	else:
		users.discard(me)
	if users:
		reactions[emoji] = sorted(users)
	else:
		reactions.pop(emoji, None)

	frappe.db.set_value(
		"Chat Message", message, "reactions", json.dumps(reactions), update_modified=False
	)
	_fanout(doc, "chat_reaction", {"thread": thread, "message": message, "reactions": reactions})
	return reactions


@frappe.whitelist()
def typing(thread):
	"""Ephemeral typing indicator — notify the other participants, no DB write."""
	doc = _require_participant(thread)
	me = frappe.session.user
	for user in _participant_users(doc):
		if user != me:
			frappe.publish_realtime(
				event="chat_typing", message={"thread": thread, "user": me}, user=user
			)


# ---------------------------------------------------------------------------
# Participants / directory
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_thread_info(thread, limit=200):
	"""Everything the chat overview shows: title, participants and the thread's shared
	content — attachments (images / files) and links.

	In a secret thread the bodies are ciphertext, so nothing can be classified here:
	the attachment rows and the recent text rows are shipped as-is and the browser
	splits them once decrypted."""
	doc = _require_participant(thread)
	limit = int(limit)
	me = frappe.session.user

	participants = []
	for p in doc.participants:
		participants.append(
			{
				"user": p.user,
				"name": p.employee_name or _user_name(p.user),
				"employee": p.employee,
				"role": p.role,
				"is_me": p.user == me,
				"image": frappe.db.get_value("User", p.user, "user_image"),
			}
		)

	others = [p for p in participants if not p["is_me"]]
	if doc.thread_type == "Direct" and others:
		display_title = others[0]["name"]
	else:
		display_title = doc.title or ", ".join(p["name"] for p in others)

	fields = [
		"name",
		"thread",
		"sender",
		"content_type",
		"message",
		"attach",
		"is_encrypted",
		"enc_iv",
		"creation",
	]

	attachments = frappe.db.get_all(
		"Chat Message",
		filters=[
			["Chat Message", "thread", "=", thread],
			["Chat Message", "attach", "is", "set"],
		],
		fields=fields,
		order_by="creation desc",
		limit=limit,
	)

	name_cache = {}
	for row in attachments:
		row["sender_name"] = (
			name_cache.setdefault(row["sender"], _user_name(row["sender"])) if row["sender"] else ""
		)
		if not row["is_encrypted"]:
			meta = frappe.db.get_value(
				"File", {"file_url": row["attach"]}, ["file_name", "file_size"], as_dict=True
			)
			row["file_name"] = (meta.file_name if meta else None) or (row["attach"] or "").split("/")[-1]
			row["file_size"] = meta.file_size if meta else None
		row["creation"] = str(row["creation"])

	links = []
	if doc.is_secret:
		# Ciphertext — hand the recent text messages over and let the page scan them.
		rows = frappe.db.get_all(
			"Chat Message",
			filters=[
				["Chat Message", "thread", "=", thread],
				["Chat Message", "content_type", "=", "text"],
			],
			fields=fields,
			order_by="creation desc",
			limit=limit,
		)
		for row in rows:
			row["sender_name"] = (
				name_cache.setdefault(row["sender"], _user_name(row["sender"]))
				if row["sender"]
				else ""
			)
			row["creation"] = str(row["creation"])
		links = rows
	else:
		rows = frappe.db.get_all(
			"Chat Message",
			filters=[
				["Chat Message", "thread", "=", thread],
				["Chat Message", "message", "like", "%http%"],
			],
			fields=fields,
			order_by="creation desc",
			limit=limit,
		)
		for row in rows:
			sender_name = (
				name_cache.setdefault(row["sender"], _user_name(row["sender"]))
				if row["sender"]
				else ""
			)
			for url in URL_RE.findall(row["message"] or ""):
				links.append(
					{
						"url": url,
						"message": row["name"],
						"sender_name": sender_name,
						"creation": str(row["creation"]),
					}
				)

	me_row = next((p for p in doc.participants if p.user == me), None)

	return {
		"thread": thread,
		"thread_type": doc.thread_type,
		"muted": me_row.muted if me_row else 0,
		"title": doc.title,
		"display_title": display_title,
		"is_secret": doc.is_secret,
		"participants": participants,
		"attachments": attachments,
		"links": links,
	}


@frappe.whitelist()
def rename_thread(thread, title):
	"""Rename a group chat (admins only). Direct chats are named after the other person."""
	doc = _require_participant(thread)
	if doc.thread_type != "Group":
		frappe.throw(_("Only a group chat can be renamed"))
	_require_admin(doc)
	doc.title = (title or "").strip() or None
	doc.save(ignore_permissions=True)
	_fanout(doc, "chat_message", {"thread": thread, "system": True})
	return {"title": doc.title}


@frappe.whitelist()
def search_employees(txt=None):
	"""Active employees with a login, for the new-chat and add-people pickers."""
	filters = [["Employee", "status", "=", "Active"], ["Employee", "user_id", "is", "set"]]
	or_filters = None
	if txt:
		like = "%" + txt + "%"
		or_filters = [
			["Employee", "employee_name", "like", like],
			["Employee", "user_id", "like", like],
		]
	rows = frappe.get_all(
		"Employee",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "employee_name", "user_id", "department", "image"],
		order_by="employee_name asc",
		limit=50,
	)
	rows = [r for r in rows if r.user_id != frappe.session.user]

	# The secret-chat picker needs to know who can receive an encrypted thread key.
	enrolled = set(frappe.get_all("Chat Encryption Key", pluck="user"))
	for r in rows:
		r["secret_ready"] = 1 if r.user_id in enrolled else 0
	return rows


def _require_admin(thread_doc):
	me = frappe.session.user
	if me == "Administrator":
		return
	row = next((p for p in thread_doc.participants if p.user == me), None)
	if not row or row.role != "Admin":
		frappe.throw(_("Only a group admin can do that"), frappe.PermissionError)


@frappe.whitelist()
def add_participant(thread, user, thread_key=None):
	"""Add someone to a group. In a secret group the caller's browser must also pass
	`thread_key` — the thread key re-wrapped for the newcomer. Without it they would join
	a thread they cannot read."""
	doc = _require_participant(thread)
	if doc.thread_type != "Group":
		frappe.throw(_("Can only add people to a group chat"))
	_require_admin(doc)
	if doc.is_participant(user):
		return {"ok": True}

	if doc.is_secret:
		from erpnext.crm import chat_crypto

		if not chat_crypto.is_enrolled(user):
			frappe.throw(_("{0} has not enabled secret chats yet").format(user))
		if not thread_key:
			frappe.throw(_("A thread key is required to add someone to a secret chat"))
		if isinstance(thread_key, str):
			thread_key = frappe.parse_json(thread_key)
		chat_crypto.grant_thread_key(thread, [dict(thread_key, user=user)])

	emp = frappe.db.get_value("Employee", {"user_id": user}, ["name", "employee_name"], as_dict=True)
	doc.append(
		"participants",
		{
			"user": user,
			"employee": emp.name if emp else None,
			"employee_name": emp.employee_name if emp else None,
			"role": "Member",
		},
	)
	doc.save(ignore_permissions=True)
	_fanout(doc, "chat_message", {"thread": thread, "system": True})
	return {"ok": True}


@frappe.whitelist()
def remove_participant(thread, user):
	doc = _require_participant(thread)
	if doc.thread_type != "Group":
		frappe.throw(_("Can only remove people from a group chat"))
	_require_admin(doc)
	doc.participants = [p for p in doc.participants if p.user != user]
	doc.save(ignore_permissions=True)
	if doc.is_secret:
		from erpnext.crm import chat_crypto

		chat_crypto.drop_thread_keys(thread, user)
	return {"ok": True}
