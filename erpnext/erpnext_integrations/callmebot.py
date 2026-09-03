"""Mirror desk notifications to WhatsApp through CallMeBot.

CallMeBot (https://www.callmebot.com/blog/free-api-whatsapp-messages/) is a free relay: a user
messages the bot once from their own phone, receives a personal `apikey`, and any

	GET https://api.callmebot.com/whatsapp.php?phone=<digits>&text=<text>&apikey=<key>

is delivered to that phone as a WhatsApp message. Opt-in is therefore per user and needs no
central configuration — the phone and the key live on the user's own Notification Settings
document, next to the existing system and email toggles (Custom Fields created by
`erpnext.patches.setup_custom_fields.create_callmebot_fields`).

`on_notification_log` is wired as `doc_events["Notification Log"]["after_insert"]`, which is the
single funnel every in-app notification passes through (mentions, assignments, shares, Notification
rules, energy points). The HTTP call itself runs in a background job, so a slow or unreachable
CallMeBot can never delay or fail the document that produced the notification.
"""

import re

import frappe
import requests
from frappe import _
from frappe.utils import get_url, strip_html_tags
from frappe.utils.password import get_decrypted_password

API_URL = "https://api.callmebot.com/whatsapp.php"
REQUEST_TIMEOUT = 15
# CallMeBot rejects very long texts; keep a safety margin below its limit.
MAX_TEXT_LENGTH = 900


def get_user_config(user: str) -> dict | None:
	"""Phone + apikey of `user`, or None when CallMeBot is not usable for them."""
	if not user:
		return None

	# Notification Settings is named after the user; missing row means the user never opted in.
	config = frappe.db.get_value(
		"Notification Settings",
		user,
		["callmebot_enabled", "callmebot_phone"],
		as_dict=True,
	)
	if not config or not config.callmebot_enabled:
		return None

	# Users paste numbers as "+380 63 640 07 06"; the API wants bare digits.
	phone = re.sub(r"\D", "", config.callmebot_phone or "")
	# `callmebot_api_key` is a Password field: its own column holds only a `*****` dummy, the
	# real key lives encrypted in `__Auth`.
	apikey = (
		get_decrypted_password("Notification Settings", user, "callmebot_api_key", raise_exception=False)
		or ""
	).strip()
	if not phone or not apikey:
		return None

	return {"phone": phone, "apikey": apikey}


def _plain(html: str | None) -> str:
	"""Notification text as a single-spaced plain string."""
	if not html:
		return ""

	return re.sub(r"\s+", " ", strip_html_tags(html)).strip()


def get_callmebot_settings():
	"""Fetch CallMeBot Settings Single DocType if exists."""
	try:
		if frappe.db.exists("DocType", "CallMeBot Settings"):
			return frappe.get_cached_doc("CallMeBot Settings")
	except Exception:
		pass
	return None


def match_template(settings, notif_type: str | None, doc_type: str | None):
	"""Find the most specific matching template row from CallMeBot Settings."""
	if not settings or not getattr(settings, "templates", None):
		return None

	notif_type = (notif_type or "").strip()
	doc_type = (doc_type or "").strip()

	# Priority 1: Match both notification_type and document_type
	if notif_type and doc_type:
		for row in settings.templates:
			r_notif = (row.notification_type or "").strip()
			r_dt = (row.document_type or "").strip()
			if r_notif == notif_type and r_dt == doc_type:
				return row

	# Priority 2: Match notification_type with any document_type
	if notif_type:
		for row in settings.templates:
			r_notif = (row.notification_type or "").strip()
			r_dt = (row.document_type or "").strip()
			if r_notif == notif_type and not r_dt:
				return row

	# Priority 3: Match document_type with generic/any notification_type
	if doc_type:
		for row in settings.templates:
			r_notif = (row.notification_type or "").strip()
			r_dt = (row.document_type or "").strip()
			if (not r_notif or r_notif == "All") and r_dt == doc_type:
				return row

	# Priority 4: Match generic "All" template
	for row in settings.templates:
		r_notif = (row.notification_type or "").strip()
		r_dt = (row.document_type or "").strip()
		if (not r_notif or r_notif == "All") and not r_dt:
			return row

	return None


def build_text(doc) -> str:
	"""WhatsApp body for a Notification Log: heading, description, absolute link.

	If Privacy Mode is active (default), overrides raw notification content with configured
	templates or a safe fallback default ("У вас нове сповіщення у ERPnext") to avoid
	sending internal customer or task details to third-party relays.
	"""
	settings = get_callmebot_settings()

	# Privacy Mode: use override templates or fallback default
	if not settings or getattr(settings, "privacy_mode", 1):
		notif_type = getattr(doc, "type", None)
		doc_type = getattr(doc, "document_type", None)

		matched = match_template(settings, notif_type, doc_type)

		if matched and matched.template:
			raw_template = matched.template.strip()
			try:
				text = frappe.render_template(raw_template, {"doc": doc, "frappe": frappe})
			except Exception:
				text = raw_template
			include_link = matched.include_link if matched.include_link is not None else 1
		else:
			default_msg = getattr(settings, "default_message", None) if settings else None
			text = (default_msg or "").strip() or _("У вас нове сповіщення у ERPnext")
			include_link = getattr(settings, "include_link", 1) if settings else 1

		if include_link and doc.link:
			link = get_url(doc.link)
			text = f"{text}\n{link}" if text else link

		return text

	# Fallback / Raw Mode: unmasked notification text
	parts = []
	heading = _plain(doc.subject or doc.title)
	if heading:
		parts.append(heading)

	body = _plain(doc.description or doc.email_content)
	# The description usually repeats the subject verbatim — do not send it twice.
	if body and body != heading:
		parts.append(body)

	text = "\n".join(parts)
	if doc.link:
		link = get_url(doc.link)
		text = f"{text}\n{link}" if text else link

	if len(text) > MAX_TEXT_LENGTH:
		text = text[: MAX_TEXT_LENGTH - 1].rstrip() + "…"

	return text


def on_notification_log(doc, method=None):
	"""doc_events hook: queue a WhatsApp copy of this notification, if the user opted in."""
	try:
		config = get_user_config(doc.for_user)
		if not config:
			return

		text = build_text(doc)
		if not text:
			return

		frappe.enqueue(
			send_message,
			queue="short",
			enqueue_after_commit=True,
			phone=config["phone"],
			apikey=config["apikey"],
			text=text,
		)
	except Exception:
		# A notification must never fail because of an optional side channel.
		frappe.log_error(title="CallMeBot: failed to queue notification", message=frappe.get_traceback())


def send_message(phone: str, apikey: str, text: str, raise_on_error: bool = False) -> bool:
	"""Send one WhatsApp message. Returns True on success; logs and returns False otherwise."""
	try:
		response = requests.get(
			API_URL,
			params={"phone": phone, "text": text, "apikey": apikey},
			timeout=REQUEST_TIMEOUT,
		)
		response.raise_for_status()
		return True
	except Exception as e:
		frappe.log_error(
			title="CallMeBot: failed to send message",
			message=f"phone={phone}\n\n{frappe.get_traceback()}",
		)
		if raise_on_error:
			frappe.throw(_("CallMeBot could not deliver the message: {0}").format(str(e)))
		return False


@frappe.whitelist()
def send_test_message(user: str | None = None) -> str:
	"""Send a test message so the user can verify their phone and key from their settings."""
	user = user or frappe.session.user
	if user != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw(_("You can only send a test message to yourself."))

	config = get_user_config(user)
	if not config:
		frappe.throw(_("CallMeBot is not configured for this user"))

	send_message(
		config["phone"],
		config["apikey"],
		_("Test message from ERPNext"),
		raise_on_error=True,
	)
	return _("Test message sent")
