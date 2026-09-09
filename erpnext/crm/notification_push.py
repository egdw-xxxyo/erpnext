"""Mirror desk notifications to the mobile app as FCM pushes.

The chat sends its own pushes from `employee_chat._push_new_message`; everything else a user
gets on desk — assignments, mentions, shares, Notification rules, energy points — funnels
through a `Notification Log` insert, and until now stopped at the app's Notifications tab,
which only updates while the app is open. This hook gives those the same push treatment,
reusing the chat's Firebase sender so there is one place that talks to FCM.

Silently does nothing on a site without `firebase-admin` / `fcm_service_account_json`
configured (see `_send_fcm_push`) or for a user with no registered device.
"""

import re

import frappe
from frappe.utils import strip_html_tags

MAX_TITLE = 120
MAX_BODY = 400


def _plain(html: str | None) -> str:
	"""Notification text as a single-spaced plain string — subject/description are rich HTML."""
	if not html:
		return ""
	return re.sub(r"\s+", " ", strip_html_tags(html)).strip()


def _notifications_muted(user: str) -> bool:
	"""Respect the user's own desk notification switch; a missing row means default-on."""
	enabled = frappe.db.get_value("Notification Settings", user, "enabled")
	return enabled is not None and not enabled


def on_notification_log(doc, method=None):
	"""doc_events hook: push this notification to the user's mobile devices."""
	try:
		user = doc.for_user
		# A notification the user caused themselves (assigning a task to yourself, say) is
		# already on their screen — pushing it back is noise.
		if not user or user == doc.from_user:
			return
		if _notifications_muted(user):
			return

		tokens = frappe.get_all("FCM Device Token", filters={"user": user}, pluck="token")
		if not tokens:
			return

		title = _plain(doc.subject)[:MAX_TITLE] or "ERPNext"
		body = _plain(doc.email_content)[:MAX_BODY]
		if not body and doc.document_type:
			body = f"{doc.document_type} {doc.document_name or ''}".strip()

		frappe.enqueue(
			"erpnext.crm.page.employee_chat.employee_chat._send_fcm_push",
			queue="short",
			enqueue_after_commit=True,
			tokens=tokens,
			title=title,
			body=body,
			data={
				"type": "erp_notification",
				"open_tab": "notifications",
				"notification": doc.name,
				"doctype": doc.document_type or "",
				"docname": doc.document_name or "",
			},
		)
	except Exception:
		# An optional side channel must never break the document that produced the notification.
		frappe.log_error(title="FCM: failed to queue desk notification", message=frappe.get_traceback())
