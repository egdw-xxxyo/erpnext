import frappe
from frappe import _

SETTINGS = "Mail Forward Settings"
WATCHED = "Watched"
SENDER = "Sender"

DEFAULTS = {
	WATCHED: {
		"email_sync_option": "ALL",
		"default_incoming": 0,
		"create_contact": 0,
		"notify_if_unreplied": 0,
		"enable_auto_reply": 0,
		"enable_automatic_linking": 0,
	},
	SENDER: {"track_email_status": 0, "send_unsubscribe_message": 0},
}
HIDDEN = {
	WATCHED: (*DEFAULTS[WATCHED], "initial_sync_count", "append_to"),
	SENDER: tuple(DEFAULTS[SENDER]),
}


def forwarding_role(name: str | None) -> str | None:
	if not name:
		return None
	if frappe.db.exists("Mail Forward Mailbox", {"parenttype": SETTINGS, "email_account": name}):
		return WATCHED
	if frappe.db.get_single_value(SETTINGS, "sender_account") == name:
		return SENDER
	return None


def pending_changes(account, role: str | None) -> dict:
	return {field: value for field, value in DEFAULTS.get(role, {}).items() if account.get(field) != value}


def apply_defaults(name: str, role: str) -> list[str]:
	account = frappe.get_doc("Email Account", name)
	changes = pending_changes(account, role)
	if changes:
		account.update(changes)
		account.save(ignore_permissions=True)
		frappe.msgprint(
			_("Email Account {0} was adjusted for mail forwarding: {1}").format(
				name, ", ".join(_(account.meta.get_label(field)) for field in changes)
			),
			alert=True,
		)
	return list(changes)


def form_profile(name: str | None) -> dict | None:
	role = forwarding_role(name)
	return {"role": role, "hidden": HIDDEN[role]} if role else None
