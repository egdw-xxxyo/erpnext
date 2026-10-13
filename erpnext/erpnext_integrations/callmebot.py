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

CallMeBot has no status endpoint: the only way to learn whether a number can receive messages is
the answer to a send. It answers every request with a 2xx code — 200 when the message is queued,
208 when the account is paused (by the user's "stop" or by CallMeBot itself; the bot then waits
for the word "resume"), 203 when the apikey is wrong — so the code alone is not an error for
`requests`. `classify_response` reads that answer, the outcome is kept on the user's Notification
Settings (`callmebot_status`), and a user whose channel went dead is told so in the desk.
"""

import re

import frappe
import requests
from frappe import _
from frappe.utils import add_to_date, escape_html, get_datetime, get_url, now_datetime, strip_html_tags
from frappe.utils.password import get_decrypted_password

API_URL = "https://api.callmebot.com/whatsapp.php"
REQUEST_TIMEOUT = 15
# CallMeBot rejects very long texts; keep a safety margin below its limit.
MAX_TEXT_LENGTH = 900

STATUS_ACTIVE = "Active"
STATUS_PAUSED = "Paused"
STATUS_INVALID_KEY = "Invalid API Key"
# Outcomes only the user can fix, from their own phone. Anything else (timeout, 5xx, rate limit)
# is transient and never changes the stored status.
USER_ACTION_STATUSES = (STATUS_PAUSED, STATUS_INVALID_KEY)
# While the channel stays dead, remind the user at most this often.
ALERT_INTERVAL_HOURS = 24
RESUME_LINK_PATTERN = re.compile(r"https://wa\.me/\d+\?text=Resume", re.IGNORECASE)


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
			text = (default_msg or "").strip() or _("You have a new notification in ERPnext")
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
		# The "your WhatsApp channel is dead" alert must not be sent down the dead channel.
		if doc.flags.skip_callmebot:
			return

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
			user=doc.for_user,
		)
	except Exception:
		# A notification must never fail because of an optional side channel.
		frappe.log_error(title="CallMeBot: failed to queue notification", message=frappe.get_traceback())


def classify_response(status_code: int, body: str | None) -> str | None:
	"""Delivery status told by a CallMeBot answer, or None for a failure that is not the user's."""
	body = body or ""
	if re.search(r"account is\s*(<b>)?\s*paused", body, re.IGNORECASE):
		return STATUS_PAUSED
	if re.search(r"apikey is invalid", body, re.IGNORECASE):
		return STATUS_INVALID_KEY
	if status_code == 200:
		return STATUS_ACTIVE
	return None


def deliver(phone: str, apikey: str, text: str) -> dict:
	"""One CallMeBot request. Returns `status` (None when the failure is not the user's to fix),
	the `resume_url` CallMeBot offers for a paused account, and `error` for a failed request."""
	try:
		response = requests.get(
			API_URL,
			params={"phone": phone, "text": text, "apikey": apikey},
			timeout=REQUEST_TIMEOUT,
		)
		response.raise_for_status()
	except Exception as e:
		frappe.log_error(
			title="CallMeBot: failed to send message",
			message=f"phone={phone}\n\n{frappe.get_traceback()}",
		)
		return {"status": None, "resume_url": None, "error": str(e)}

	status = classify_response(response.status_code, response.text)
	if status == STATUS_ACTIVE:
		return {"status": status, "resume_url": None, "error": None}

	frappe.log_error(
		title="CallMeBot: message was not accepted",
		message=f"phone={phone}\nstatus={response.status_code}\n\n{response.text[:2000]}",
	)
	resume_link = RESUME_LINK_PATTERN.search(response.text)
	return {
		"status": status,
		"resume_url": resume_link.group(0) if resume_link else None,
		"error": None,
	}


def send_message(phone: str, apikey: str, text: str, user: str | None = None) -> bool:
	"""Send one WhatsApp message. Returns True on success; logs and returns False otherwise.

	With `user`, the outcome is recorded on their Notification Settings and they are alerted in
	the desk when the channel needs their action."""
	result = deliver(phone, apikey, text)
	if user and result["status"]:
		record_status(user, result["status"], resume_url=result["resume_url"])
	return result["status"] == STATUS_ACTIVE


def get_help_url() -> str | None:
	"""Link to the page explaining how to restore WhatsApp notifications, if one is configured."""
	settings = get_callmebot_settings()
	url = (getattr(settings, "help_url", None) or "").strip() if settings else ""
	return get_url(url) if url.startswith("/") else url or None


def failure_text(status: str | None, lang: str | None = None) -> str:
	"""One-line explanation of why WhatsApp notifications are not delivered."""
	if status == STATUS_PAUSED:
		return _(
			'WhatsApp notifications are paused by CallMeBot. Send the word "resume" to the bot from your phone to turn them back on.',
			lang,
		)
	if status == STATUS_INVALID_KEY:
		return _(
			"WhatsApp notifications are not delivered: the CallMeBot API key is no longer valid. Get a new key from the bot and save it in your Notification Settings.",
			lang,
		)
	return _("CallMeBot did not accept the message. Try again later.", lang)


def failure_html(
	status: str | None, resume_url: str | None = None, user: str | None = None, lang: str | None = None
) -> str:
	"""`failure_text` followed by the links that fix it: resume, own settings, help page."""
	links = []
	if status == STATUS_PAUSED and resume_url:
		links.append((resume_url, _('Send "resume" in WhatsApp', lang)))
	if user:
		links.append((get_url(f"/app/notification-settings/{user}"), _("Open Notification Settings", lang)))
	help_url = get_help_url()
	if help_url:
		links.append((help_url, _("How to restore WhatsApp notifications", lang)))

	html = escape_html(failure_text(status, lang))
	for url, label in links:
		html += f'<br><a href="{escape_html(url)}" target="_blank" rel="noopener">{escape_html(label)}</a>'
	return html


def record_status(user: str, status: str, resume_url: str | None = None, alert: bool = True):
	"""Keep the last delivery outcome on the user's Notification Settings; alert on a dead channel.

	The alert goes out when the channel turns dead and then once per `ALERT_INTERVAL_HOURS` for
	as long as notifications keep failing — never once per lost message."""
	try:
		current = frappe.db.get_value(
			"Notification Settings", user, ["callmebot_status", "callmebot_alerted_on"], as_dict=True
		)
		if not current:
			return

		values = {}
		if current.callmebot_status != status:
			values["callmebot_status"] = status

		if status in USER_ACTION_STATUSES and alert:
			remind_after = (
				add_to_date(get_datetime(current.callmebot_alerted_on), hours=ALERT_INTERVAL_HOURS)
				if current.callmebot_alerted_on
				else None
			)
			if current.callmebot_status != status or not remind_after or now_datetime() >= remind_after:
				alert_user(user, status, resume_url)
				values["callmebot_alerted_on"] = now_datetime()
		elif status == STATUS_ACTIVE and current.callmebot_alerted_on:
			values["callmebot_alerted_on"] = None

		if values:
			frappe.db.set_value("Notification Settings", user, values, update_modified=False)
			frappe.clear_document_cache("Notification Settings", user)
			if "callmebot_status" in values:
				from erpnext.crm.notification_channels import sync_users

				sync_users([user])
	except Exception:
		frappe.log_error(title="CallMeBot: failed to record status", message=frappe.get_traceback())


def alert_user(user: str, status: str, resume_url: str | None = None):
	"""Desk notification telling `user` their WhatsApp notifications stopped and how to fix it."""
	lang = frappe.db.get_value("User", user, "language")
	alert = frappe.new_doc("Notification Log")
	alert.for_user = user
	alert.type = "Alert"
	alert.subject = failure_text(status, lang)
	alert.email_content = failure_html(status, resume_url=resume_url, user=user, lang=lang)
	alert.link = get_help_url() or f"/app/notification-settings/{user}"
	alert.flags.skip_callmebot = True
	alert.insert(ignore_permissions=True)


@frappe.whitelist()
def get_status_help(user: str | None = None) -> dict:
	"""What the Notification Settings form shows when the user's WhatsApp channel is dead."""
	user = user or frappe.session.user
	if user != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	status = frappe.db.get_value("Notification Settings", user, "callmebot_status")
	if status not in USER_ACTION_STATUSES:
		return {}
	return {"status": status, "message": failure_text(status), "help_url": get_help_url()}


@frappe.whitelist()
def send_test_message(user: str | None = None) -> dict:
	"""Send a test message so the user can verify their phone and key from their settings.

	A refusal is returned, not thrown: the status it reveals must survive the request."""
	user = user or frappe.session.user
	if user != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw(_("You can only send a test message to yourself."))

	config = get_user_config(user)
	if not config:
		frappe.throw(_("CallMeBot is not configured for this user"))

	result = deliver(config["phone"], config["apikey"], _("Test message from ERPNext"))
	if result["error"]:
		frappe.throw(_("CallMeBot could not deliver the message: {0}").format(result["error"]))

	if result["status"]:
		record_status(user, result["status"], alert=False)
	if result["status"] == STATUS_ACTIVE:
		return {"ok": True, "message": _("Test message sent")}
	return {"ok": False, "message": failure_html(result["status"], resume_url=result["resume_url"])}
