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
from urllib.parse import unquote, urlparse

import frappe
from frappe import _
from frappe.utils import now

URL_RE = re.compile(r"https?://[^\s<>\"']+")

# Report-style desk routes: /app/query-report/<name> and /app/report/<name>.
_REPORT_VIEWS = {"query-report", "report"}
# Desk routes that are neither a DocType nor a report — treated as generic pages.
_PAGE_VIEWS = {"dashboard", "dashboard-view", "kanban", "gantt", "calendar", "print"}


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


def _may_manage_archive(thread_doc):
	"""Archiving is not a membership privilege: for a Document thread anyone who may read the
	referenced record may archive/unarchive it (the same gate `open_document_thread` uses to let
	them join). For Direct/Group threads any participant may."""
	me = frappe.session.user
	if me == "Administrator" or thread_doc.is_participant(me):
		return thread_doc
	if (
		thread_doc.thread_type == "Document"
		and thread_doc.reference_doctype
		and thread_doc.reference_name
		and not thread_doc.reference_removed
		and frappe.has_permission(thread_doc.reference_doctype, "read", doc=thread_doc.reference_name)
	):
		return thread_doc
	frappe.throw(_("You are not allowed to archive this chat"), frappe.PermissionError)


def _require_writable(thread_doc):
	"""An archived Document thread is frozen — the record it belongs to is done with. Direct and
	group threads stay writable while archived; they just sit in the archived list."""
	if thread_doc.thread_type == "Document" and thread_doc.is_archived:
		frappe.throw(_("This chat is archived and read-only"), frappe.PermissionError)
	return thread_doc


def _may_purge():
	"""Deleting a chat for everyone is a role-level right (see the `Chat Manager` role), not
	something a participant gets by taking part in the conversation. Checked without a doc on
	purpose — the doc-level hook would add a participation requirement."""
	return bool(frappe.has_permission("Chat Thread", "delete"))


def _is_read_only(thread_type, is_archived):
	return 1 if (thread_type == "Document" and is_archived) else 0


def _participant_users(thread_doc):
	return [p.user for p in thread_doc.participants if p.user]


def _fanout(thread_doc, event, message, users=None):
	"""Emit a realtime event to each user's private room. Defaults to every participant;
	pass `users` to target a subset (e.g. only assignees of a Document thread's record)."""
	for user in users if users is not None else _participant_users(thread_doc):
		frappe.publish_realtime(event=event, message=message, user=user, after_commit=True)


def _assigned_users(reference_doctype, reference_name):
	"""Users assigned to a record (its `_assign` list). Empty when the record has no
	assignees or is gone."""
	if not reference_doctype or not reference_name:
		return set()
	try:
		raw = frappe.db.get_value(reference_doctype, reference_name, "_assign")
	except Exception:
		return set()
	try:
		return set(frappe.parse_json(raw) or [])
	except (ValueError, TypeError):
		return set()


def _notify_users(thread_doc, sender):
	"""Who gets a realtime notification for a new message. Normally every participant; for a
	Document thread only the participants assigned to the linked record — plus the sender, so
	their own other tabs stay in sync. Non-assignees still see the message on open/poll, they
	just aren't pinged."""
	participants = set(_participant_users(thread_doc))
	if thread_doc.thread_type != "Document":
		return participants
	assigned = _assigned_users(thread_doc.reference_doctype, thread_doc.reference_name)
	return (participants & assigned) | {sender}


def _user_name(user):
	return frappe.db.get_value("User", user, "full_name") or user


def _preview_text(content_type, message, attach, is_encrypted=False, link_title=None):
	if is_encrypted:
		# The server cannot read the body — and must not store a hint about it either.
		return "🔒 " + _("Encrypted message")
	if content_type == "image":
		return "📷 " + _("Photo")
	if content_type == "audio":
		return "🎤 " + _("Audio")
	if content_type == "file":
		fname = (attach or "").split("/")[-1]
		return "📎 " + (fname or _("File"))
	if content_type == "link":
		return "🔗 " + (link_title or (message or "").strip() or _("Link"))
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


def _extra_file_urls(raw, limit=5):
	"""Sanitise the `extra_files` argument of send_message: a short list of local file urls."""
	if not raw:
		return []
	urls = frappe.parse_json(raw) if isinstance(raw, str) else raw
	if not isinstance(urls, list | tuple):
		return []
	out = []
	for url in urls:
		if isinstance(url, str) and url.startswith(("/files/", "/private/files/")):
			out.append(url)
	return out[:limit]


def _parse_link_data(raw):
	if not raw:
		return None
	if isinstance(raw, dict):
		return raw
	try:
		return json.loads(raw)
	except (ValueError, TypeError):
		return None


def _doctype_from_slug(slug):
	"""Desk routes a DocType as its scrubbed, hyphenated name ("Sales Order" → "sales-order").
	Resolve back to the real DocType name, or None if it isn't one."""
	if not slug:
		return None
	guess = frappe.unscrub(slug.replace("-", "_"))
	if frappe.db.exists("DocType", guess):
		return guess
	# Fallback for odd casing/naming — scan (only runs on the rare miss).
	for dt in frappe.get_all("DocType", pluck="name"):
		if frappe.scrub(dt).replace("_", "-") == slug:
			return dt
	return None


def _document_card(doctype, name):
	"""Title/subtitle/image for a record the current user may read, else None."""
	if not frappe.has_permission(doctype, "read", doc=name):
		return None
	meta = frappe.get_meta(doctype)
	title_field = meta.get_title_field()
	image_field = meta.image_field
	fields = ["name"]
	if title_field and title_field != "name":
		fields.append(title_field)
	if image_field:
		fields.append(image_field)
	rows = frappe.get_list(doctype, filters={"name": name}, fields=fields, limit=1)
	if not rows:
		return None
	row = rows[0]
	title = str((row.get(title_field) if title_field else None) or name)
	# Always surface the DocType and, when the record has a human title distinct from its
	# id, the id too — so the card reads "Item · R202ADV", not just a bare URL.
	subtitle = _(doctype) if title == str(name) else f"{_(doctype)} · {name}"
	return {
		"kind": "document",
		"doctype": doctype,
		"name": name,
		"title": title,
		"subtitle": subtitle,
		"image": row.get(image_field) if image_field else None,
	}


def _mark_removed(cards):
	"""Set `removed` on each document-kind card whose target record no longer exists.
	Batched: one existence query per distinct doctype. `cards` are mutated in place."""
	by_dt = {}
	for c in cards:
		if isinstance(c, dict) and c.get("kind") == "document" and c.get("doctype") and c.get("name"):
			by_dt.setdefault(c["doctype"], set()).add(c["name"])
	existing = {}
	for dt, names in by_dt.items():
		if not frappe.db.exists("DocType", dt):
			existing[dt] = set()
			continue
		existing[dt] = set(frappe.get_all(dt, filters={"name": ["in", list(names)]}, pluck="name"))
	for c in cards:
		if isinstance(c, dict) and c.get("kind") == "document" and c.get("doctype") and c.get("name"):
			c["removed"] = c["name"] not in existing.get(c["doctype"], set())


def _annotate_removed(payloads):
	"""Flag inline document link cards whose target has been deleted, so the client can
	badge them 'Removed'."""
	_mark_removed([p["link_data"] for p in payloads if isinstance(p.get("link_data"), dict)])
	return payloads


def _reference_card(doc):
	"""Header card for a Document thread's linked record. Live records resolve to a full
	card (with a URL to the form); a deleted record degrades to a ghost card built from the
	stored `reference_label`, flagged `removed`."""
	if not doc.reference_doctype or not doc.reference_name:
		return None
	if not doc.reference_removed:
		card = _document_card(doc.reference_doctype, doc.reference_name)
		if card:
			card["url"] = frappe.utils.get_url_to_form(doc.reference_doctype, doc.reference_name)
			return card
	return {
		"kind": "document",
		"doctype": doc.reference_doctype,
		"name": doc.reference_name,
		"title": doc.reference_label or doc.reference_name,
		"subtitle": f"{_(doc.reference_doctype)} · {doc.reference_name}",
		"removed": True,
	}


@frappe.whitelist()
def resolve_link(url):
	"""Turn a desk URL into a link-card payload the chat renders.

	Understands `/app/<doctype>/<name>` (a record), `/app/<doctype>` (a list),
	`/app/query-report|report/<name>` and other `/app/<page>` routes. Anything whose path
	is not a desk (`/app/...`) route comes back as `kind:"external"` so the client just
	sends the raw text. Document cards are permission-checked — a link to a record you
	cannot read resolves to a bare URL, never a title leak.

	Note: we key off the URL path, not the host. The host is unreliable server-side
	(docker/reverse-proxy rewrites `request.host` and the site URL), so any `/app/...` link
	is treated as ours; the stored URL keeps its original host so it still opens correctly."""
	url = (url or "").strip()
	if not url:
		frappe.throw(_("No link given"))

	parsed = urlparse(url)
	path = parsed.path or ""
	segments = [unquote(s) for s in path.split("/") if s]
	# Expect ["app", <view>, <name?>]
	if len(segments) < 2 or segments[0] != "app":
		return {"kind": "external", "url": url}

	view = segments[1].lower()
	rest = segments[2] if len(segments) > 2 else None

	if view in _REPORT_VIEWS and rest:
		return {"kind": "report", "url": url, "name": rest, "title": rest, "subtitle": _("Report")}

	if view in _PAGE_VIEWS or (not _doctype_from_slug(segments[1]) and not rest):
		title = frappe.unscrub((rest or segments[1]).replace("-", "_"))
		return {"kind": "page", "url": url, "title": title, "subtitle": _("Page")}

	doctype = _doctype_from_slug(segments[1])
	if not doctype:
		return {"kind": "page", "url": url, "title": segments[1], "subtitle": _("Page")}

	if not rest:
		return {
			"kind": "list",
			"url": url,
			"doctype": doctype,
			"title": _(doctype),
			"subtitle": _("List"),
		}

	card = _document_card(doctype, rest)
	if not card:
		# No read access (or gone) — degrade to a plain URL card.
		return {"kind": "page", "url": url, "title": rest, "subtitle": _(doctype)}
	card["url"] = url
	return card


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
			["sender", "content_type", "message", "attach", "link_data", "is_encrypted", "enc_iv"],
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
				rt_title = (_parse_link_data(rt.link_data) or {}).get("title")
				reply_preview["text"] = _preview_text(
					rt.content_type, rt.message, rt.attach, link_title=rt_title
				)[:120]

	return {
		"name": row.get("name"),
		"thread": row.get("thread"),
		"sender": row.get("sender"),
		"sender_name": resolve_name(row.get("sender")),
		"content_type": row.get("content_type") or "text",
		"message": row.get("message") or "",
		"attach": row.get("attach"),
		"link_data": _parse_link_data(row.get("link_data")),
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
			"reference_doctype",
			"reference_name",
			"reference_label",
			"is_archived",
			"reference_removed",
		],
		order_by="last_message_on desc",
	)

	# One role check for the whole list — the per-thread gate still runs inside purge_thread.
	can_purge = 1 if _may_purge() else 0

	for t in threads:
		parts = frappe.get_all(
			"Chat Participant",
			filters={"parenttype": "Chat Thread", "parent": t["name"]},
			fields=["user", "employee_name", "role", "last_read_on", "muted"],
		)
		t["participants"] = parts
		mine = next((p for p in parts if p.user == me), None)
		t["muted"] = mine.muted if mine else 0
		# The client needs its own read cursor to place the "New messages" divider and
		# scroll to the first unread message on open.
		t["my_last_read"] = str(last_read[t["name"]]) if last_read[t["name"]] else None
		others = [p for p in parts if p.user != me]
		if t["thread_type"] == "Direct" and others:
			o = others[0]
			t["display_title"] = o.employee_name or _user_name(o.user)
			t["other_user"] = o.user
		elif t["thread_type"] == "Document":
			t["display_title"] = t["reference_label"] or (
				f"{t['reference_doctype']}: {t['reference_name']}"
				if t["reference_doctype"]
				else _("Document chat")
			)
			t["other_user"] = None
		else:
			t["display_title"] = t["title"] or ", ".join(p.employee_name or p.user for p in others)
			t["other_user"] = None

		unread_filters = [
			["Chat Message", "thread", "=", t["name"]],
			["Chat Message", "sender", "!=", me],
		]
		if last_read[t["name"]]:
			unread_filters.append(["Chat Message", "creation", ">", last_read[t["name"]]])
		t["unread"] = frappe.db.count("Chat Message", unread_filters)
		t["read_only"] = _is_read_only(t["thread_type"], t["is_archived"])
		t["can_purge"] = can_purge

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
			frappe.throw(_("These people have not enabled secret chats yet: {0}").format(", ".join(missing)))

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
		emp = frappe.db.get_value("Employee", {"user_id": u}, ["name", "employee_name"], as_dict=True)
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


@frappe.whitelist()
def open_document_thread(reference_doctype, reference_name):
	"""Open (or create) the single canonical chat about a specific record. There is one
	thread per record — everyone who opens it from the form joins the same conversation.

	Returns the thread name; the caller routes the Employee Chat page to it."""
	if not frappe.has_permission(reference_doctype, "read", doc=reference_name):
		frappe.throw(_("You do not have access to this document"))

	from erpnext.crm.doctype.chat_thread.chat_thread import document_dedup_key

	me = frappe.session.user
	emp = frappe.db.get_value("Employee", {"user_id": me}, ["name", "employee_name"], as_dict=True)
	key = document_dedup_key(reference_doctype, reference_name)

	existing = frappe.db.exists("Chat Thread", {"dedup_key": key})
	if existing:
		doc = frappe.get_doc("Chat Thread", existing)
		if not doc.is_participant(me):
			# Shared thread — anyone opening the record joins the conversation.
			doc.append(
				"participants",
				{
					"user": me,
					"employee": emp.name if emp else None,
					"employee_name": emp.employee_name if emp else None,
					"role": "Member",
				},
			)
			doc.save(ignore_permissions=True)
		return {"name": doc.name, "existing": True}

	card = _document_card(reference_doctype, reference_name)
	doc = frappe.new_doc("Chat Thread")
	doc.thread_type = "Document"
	doc.is_secret = 0
	doc.reference_doctype = reference_doctype
	doc.reference_name = reference_name
	doc.reference_label = (card or {}).get("title") or reference_name
	doc.append(
		"participants",
		{
			"user": me,
			"employee": emp.name if emp else None,
			"employee_name": emp.employee_name if emp else None,
			"role": "Admin",
		},
	)
	doc.insert(ignore_permissions=True)
	return {"name": doc.name, "existing": False}


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
			"link_data",
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
	return _annotate_removed([_message_payload(r, name_cache) for r in rows])


@frappe.whitelist()
def send_message(
	thread,
	message=None,
	content_type="text",
	attach=None,
	link_data=None,
	reply_to=None,
	is_encrypted=0,
	enc_iv=None,
	extra_files=None,
):
	"""Insert a message, update the thread's last-message metadata, and push it to every
	participant's private room.

	In a secret thread `message` must already be ciphertext produced in the sender's
	browser. Plaintext is rejected outright rather than stored — a client-side bug must
	not be able to leak a body into the database. A `link` card in a secret thread carries
	its payload inside the encrypted `message`, so `link_data` stays empty there."""
	doc = _require_writable(_require_participant(thread))
	is_encrypted = int(is_encrypted or 0)

	link = _parse_link_data(link_data)
	link_title = link.get("title") if link else None

	if doc.is_secret:
		if not is_encrypted or not enc_iv:
			frappe.throw(_("This chat only accepts encrypted messages"))
		if not (message or "").strip():
			frappe.throw(_("Nothing to send"))
		# Never persist a cleartext card in a secret thread — it belongs in the ciphertext.
		link = None
	else:
		if is_encrypted:
			frappe.throw(_("This chat is not a secret chat"))
		if content_type == "text" and not (message or "").strip():
			frappe.throw(_("Nothing to send"))
		if content_type in ("image", "audio", "file") and not attach:
			frappe.throw(_("Nothing to send"))
		if content_type == "link":
			if not link or not link.get("url"):
				frappe.throw(_("Nothing to send"))
			# Keep the URL in `message` too, so URL scanning / the Links tab still work.
			message = link["url"]

	me = frappe.session.user
	msg = frappe.get_doc(
		{
			"doctype": "Chat Message",
			"thread": thread,
			"sender": me,
			"content_type": content_type,
			"message": message or "",
			"attach": attach,
			"link_data": json.dumps(link) if link else None,
			"reply_to": reply_to,
			"is_encrypted": is_encrypted,
			"enc_iv": enc_iv,
			"enc_version": 1 if is_encrypted else 0,
		}
	)
	msg.insert(ignore_permissions=True)
	if attach:
		link_attachment_to_thread(attach, thread)
	# Files the message references but does not carry in `attach` — in a secret thread the
	# encrypted preview's url lives inside the ciphertext, so the server would never find it
	# again (and could not delete it on purge) unless the sender names it here.
	for url in _extra_file_urls(extra_files):
		link_attachment_to_thread(url, thread)

	preview = _preview_text(content_type, message, attach, is_encrypted=is_encrypted, link_title=link_title)
	frappe.db.set_value(
		"Chat Thread",
		thread,
		{"last_message_on": msg.creation, "last_message_preview": preview[:140], "last_sender": me},
		update_modified=False,
	)

	payload = _message_payload(msg.as_dict())
	_fanout(doc, "chat_message", payload, users=_notify_users(doc, me))
	return payload


@frappe.whitelist()
def mark_read(thread, upto=None):
	"""Advance the current user's read cursor for a thread; notify others (seen ticks).

	`upto` (a message creation timestamp) marks read only up to a specific message — used
	by progressive read-on-scroll so messages still below the fold stay unread. The cursor
	only ever moves forward, so an out-of-order call (e.g. scrolling back up) can't un-read
	newer messages. With no `upto` the whole thread is marked read as of now."""
	doc = _require_participant(thread)
	me = frappe.session.user
	name = frappe.db.get_value(
		"Chat Participant", {"parenttype": "Chat Thread", "parent": thread, "user": me}, "name"
	)
	if not name:
		return
	ts = upto or now()
	current = frappe.db.get_value("Chat Participant", name, "last_read_on")
	if current and str(current) >= str(ts):
		# Never move the cursor backwards.
		return {"last_read_on": str(current)}
	frappe.db.set_value("Chat Participant", name, "last_read_on", ts, update_modified=False)
	_fanout(doc, "chat_seen", {"thread": thread, "user": me, "last_read_on": ts})
	return {"last_read_on": str(ts)}


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
def set_archived(thread, archived):
	"""Archive/unarchive a chat for everyone. Archived chats move to their own collapsed
	section; a Document thread additionally becomes read-only (see `_require_writable`).

	`reference_removed` is left alone: a thread archived because its record was deleted keeps
	its "Removed" badge even after someone unarchives it."""
	doc = _may_manage_archive(_get_thread(thread))
	archived = 1 if int(archived or 0) else 0
	# `is_archived` is read_only in the schema — write it the same way on_reference_deleted does.
	frappe.db.set_value("Chat Thread", thread, "is_archived", archived, update_modified=False)
	payload = {
		"thread": thread,
		"is_archived": archived,
		"read_only": _is_read_only(doc.thread_type, archived),
	}
	_fanout(doc, "chat_thread_archived", payload)
	return payload


@frappe.whitelist()
def purge_thread(thread):
	"""Delete an archived chat for good: every message, every attachment (including generated
	thumbnails and encrypted blobs), the wrapped thread keys and the thread itself.

	Two gates, deliberately different: `_may_manage_archive` says you have business with this
	chat, `_may_purge` says you are trusted to destroy it (the `Chat Manager` role)."""
	doc = _may_manage_archive(_get_thread(thread))
	if not doc.is_archived:
		frappe.throw(_("Only an archived chat can be removed"))
	if not _may_purge():
		frappe.throw(_("You are not allowed to remove chats"), frappe.PermissionError)

	# The participant rows die with the parent, so capture the audience before deleting.
	users = _participant_users(doc)

	for name in _thread_file_names(thread):
		try:
			frappe.delete_doc("File", name, ignore_permissions=True, force=True, delete_permanently=True)
		except Exception:
			# One unreachable blob must not strand the rest of the purge.
			frappe.log_error(title="Chat purge: could not delete file", message=frappe.get_traceback())

	# Sweep anything that appeared (or was linked) while we were deleting.
	from frappe.utils.file_manager import remove_all

	remove_all("Chat Thread", thread, from_delete=True, delete_permanently=True)

	frappe.db.delete("Chat Message", {"thread": thread})
	frappe.db.delete("Chat Thread Key", {"thread": thread})
	frappe.delete_doc("Chat Thread", thread, ignore_permissions=True, force=True, delete_permanently=True)

	for user in users:
		frappe.publish_realtime(
			event="chat_thread_purged", message={"thread": thread}, user=user, after_commit=True
		)
	return {"ok": True, "thread": thread}


def _thread_file_names(thread):
	"""Every File belonging to a thread: the ones linked to it, the ones only referenced by a
	message (older rows predate `link_attachment_to_thread`), and their thumbnails."""
	names = list(
		frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Chat Thread", "attached_to_name": thread},
			pluck="name",
		)
	)
	urls = [u for u in frappe.get_all("Chat Message", filters={"thread": thread}, pluck="attach") if u]
	for url in set(urls):
		names += frappe.get_all("File", filters={"file_url": url}, pluck="name")

	seen = list(dict.fromkeys(names))
	# Thumbnails are separate File rows cached on the source (see chat_media.ensure_thumbnail);
	# for small images the thumbnail url is the original, which is already in the list.
	for name in list(seen):
		thumb_url = frappe.db.get_value("File", name, "thumbnail_url")
		if thumb_url:
			seen += frappe.get_all("File", filters={"file_url": thumb_url}, pluck="name")
	return list(dict.fromkeys(seen))


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
	doc = _require_writable(_require_participant(thread))
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

	frappe.db.set_value("Chat Message", message, "reactions", json.dumps(reactions), update_modified=False)
	_fanout(doc, "chat_reaction", {"thread": thread, "message": message, "reactions": reactions})
	return reactions


@frappe.whitelist()
def typing(thread):
	"""Ephemeral typing indicator — notify the other participants, no DB write."""
	doc = _require_writable(_require_participant(thread))
	me = frappe.session.user
	for user in _participant_users(doc):
		if user != me:
			frappe.publish_realtime(event="chat_typing", message={"thread": thread, "user": me}, user=user)


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
	elif doc.thread_type == "Document":
		display_title = doc.reference_label or (
			f"{doc.reference_doctype}: {doc.reference_name}" if doc.reference_doctype else _("Document chat")
		)
	else:
		display_title = doc.title or ", ".join(p["name"] for p in others)

	fields = [
		"name",
		"thread",
		"sender",
		"content_type",
		"message",
		"attach",
		"link_data",
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
				name_cache.setdefault(row["sender"], _user_name(row["sender"])) if row["sender"] else ""
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
				name_cache.setdefault(row["sender"], _user_name(row["sender"])) if row["sender"] else ""
			)
			if row.get("content_type") == "link":
				# A shared card — surface its title/kind, not a bare URL.
				card = _parse_link_data(row.get("link_data")) or {}
				links.append(
					{
						"url": card.get("url") or (row.get("message") or ""),
						"title": card.get("title"),
						"kind": card.get("kind"),
						"doctype": card.get("doctype"),
						"name": card.get("name"),
						"message": row["name"],
						"sender_name": sender_name,
						"creation": str(row["creation"]),
					}
				)
				continue
			for url in URL_RE.findall(row["message"] or ""):
				links.append(
					{
						"url": url,
						"message": row["name"],
						"sender_name": sender_name,
						"creation": str(row["creation"]),
					}
				)

	_mark_removed(links)

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
		"reference_doctype": doc.reference_doctype,
		"reference_name": doc.reference_name,
		"reference_label": doc.reference_label,
		"is_archived": doc.is_archived,
		"read_only": _is_read_only(doc.thread_type, doc.is_archived),
		"can_purge": 1 if _may_purge() else 0,
		"reference_removed": doc.reference_removed,
		"reference_card": _reference_card(doc),
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
	"""People to start a chat with, for the new-chat and add-people pickers.

	The chat is keyed on `User`, not `Employee`, so the list is every enabled internal
	(System User) login — not only staff who happen to have an Employee record with
	`user_id` filled. Website/portal accounts and the built-ins are excluded so the
	picker never offers a customer. Employee name/department decorate a row when the
	user has an Employee, otherwise the user's own full name is used.

	The return shape is unchanged (`user_id`, `employee_name`, `department`, `image`,
	`secret_ready`) so the client pickers need no change."""
	filters = [
		["User", "enabled", "=", 1],
		["User", "user_type", "=", "System User"],
		["User", "name", "not in", ["Administrator", "Guest", frappe.session.user]],
	]
	or_filters = None
	if txt:
		like = "%" + txt + "%"
		or_filters = [
			["User", "full_name", "like", like],
			["User", "name", "like", like],
		]
	users = frappe.get_all(
		"User",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "full_name", "user_image"],
		order_by="full_name asc",
		limit=50,
	)
	if not users:
		return []

	emails = [u.name for u in users]
	# One lookup for the Employee decoration instead of one per row.
	emp_by_user = {
		e.user_id: e
		for e in frappe.get_all(
			"Employee",
			filters={"user_id": ["in", emails]},
			fields=["user_id", "employee_name", "department", "image"],
		)
	}
	# The secret-chat picker needs to know who can receive an encrypted thread key.
	enrolled = set(frappe.get_all("Chat Encryption Key", pluck="user"))

	rows = []
	for u in users:
		emp = emp_by_user.get(u.name)
		rows.append(
			{
				"user_id": u.name,
				"employee_name": (emp.employee_name if emp else None) or u.full_name or u.name,
				"department": emp.department if emp else None,
				"image": (emp.image if emp else None) or u.user_image,
				"secret_ready": 1 if u.name in enrolled else 0,
			}
		)
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
