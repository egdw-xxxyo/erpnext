"""Which channels reach a user when they are away from the desk.

Two of them exist: the WhatsApp mirror through CallMeBot (`erpnext.erpnext_integrations.callmebot`)
and the mobile app's push (`FCM Device Token`). A user with neither only learns about a message
when they next open ERPNext, so a manager wants to see who that is: `Employee.notification_channels`
keeps the answer on the employee (list column and filter), and the chat marks such a person among
those who have not read a message yet.

The field is a stored copy, refreshed where a channel changes — the user's Notification Settings,
a CallMeBot delivery outcome, a device registering or dropping out — and hourly by `sync_all`,
which covers the writes that bypass document events.
"""

import frappe

from erpnext.erpnext_integrations.callmebot import USER_ACTION_STATUSES

WHATSAPP = "WhatsApp"
MOBILE_APP = "Mobile App"
LABEL_BOTH = "WhatsApp + Mobile App"
LABEL_NONE = "No Channel"
LABELS = (LABEL_BOTH, WHATSAPP, MOBILE_APP, LABEL_NONE)


def channels_of(users) -> dict[str, list[str]]:
	"""Active channels of each of `users`. Remembered for the request: the chat list asks for
	the same people once per thread."""
	cache = getattr(frappe.local, "notification_channels", None)
	if cache is None:
		cache = frappe.local.notification_channels = {}
	missing = [u for u in dict.fromkeys(users) if u and u not in cache]
	if missing:
		whatsapp = set()
		if frappe.db.has_column("Notification Settings", "callmebot_status"):
			for row in frappe.get_all(
				"Notification Settings",
				filters={"name": ["in", missing], "callmebot_enabled": 1},
				fields=["name", "callmebot_phone", "callmebot_api_key", "callmebot_status"],
			):
				if (
					row.callmebot_phone
					and row.callmebot_api_key
					and row.callmebot_status not in USER_ACTION_STATUSES
				):
					whatsapp.add(row.name)
		mobile = set(
			frappe.get_all("FCM Device Token", filters={"user": ["in", missing]}, pluck="user", distinct=True)
		)
		for user in missing:
			cache[user] = [
				channel
				for channel, active in ((WHATSAPP, user in whatsapp), (MOBILE_APP, user in mobile))
				if active
			]
	return {u: cache.get(u, []) for u in users}


def without_channels(users) -> set[str]:
	return {user for user, channels in channels_of(users).items() if not channels}


def label_of(channels: list[str]) -> str:
	if len(channels) > 1:
		return LABEL_BOTH
	return channels[0] if channels else LABEL_NONE


def sync_users(users) -> None:
	"""Refresh `Employee.notification_channels` of the employees behind `users`."""
	users = [u for u in dict.fromkeys(users) if u]
	if not users or not frappe.db.has_column("Employee", "notification_channels"):
		return

	frappe.local.notification_channels = {}
	channels = channels_of(users)
	for employee in frappe.get_all(
		"Employee", filters={"user_id": ["in", users]}, fields=["name", "user_id", "notification_channels"]
	):
		label = label_of(channels[employee.user_id])
		if employee.notification_channels != label:
			frappe.db.set_value(
				"Employee", employee.name, "notification_channels", label, update_modified=False
			)


def sync_all() -> None:
	"""Hourly: devices are registered and dropped with direct writes, without document events."""
	sync_users(frappe.get_all("Employee", filters={"user_id": ["is", "set"]}, pluck="user_id"))


def on_notification_settings_update(doc, method=None):
	sync_users([doc.name])


def set_on_employee(doc, method=None):
	"""Employee validate: the linked user may have just been set, changed or removed."""
	if not doc.meta.has_field("notification_channels"):
		return
	doc.notification_channels = label_of(channels_of([doc.user_id])[doc.user_id]) if doc.user_id else None
