"""Assign people to business WhatsApp numbers: Responsible answers, Spectator reads."""

import json

import frappe
from frappe import _

from erpnext.crm import whatsapp_access as wa_access

EDIT_ROLES = ("System Manager", "Sales Manager")
CHAT_ROLE = "WhatsApp User"


@frappe.whitelist()
def get_matrix():
	frappe.only_for(EDIT_ROLES)
	if not frappe.db.table_exists("WhatsApp Account"):
		return {"installed": False}

	labels = wa_access.account_labels()
	accounts = [dict(labels.get(name, {"label": name}), name=name) for name in wa_access.all_accounts()]
	rows = frappe.get_all("WhatsApp Number Access", fields=["whatsapp_account", "user", "access"])
	chat_users = set(
		frappe.get_all("Has Role", filters={"parenttype": "User", "role": CHAT_ROLE}, pluck="parent")
	)
	admins = set(
		frappe.get_all(
			"Has Role", filters={"parenttype": "User", "role": wa_access.ADMIN_ROLE}, pluck="parent"
		)
	)
	names = chat_users | {r.user for r in rows}
	users = frappe.get_all(
		"User",
		filters={"name": ["in", list(names) or [""]], "enabled": 1, "user_type": "System User"},
		fields=["name", "full_name", "user_image"],
		order_by="full_name asc",
	)
	for u in users:
		u["is_admin"] = 1 if u.name in admins else 0
		u["has_chat_role"] = 1 if u.name in chat_users else 0
	return {
		"installed": True,
		"accounts": accounts,
		"users": users,
		"access": {f"{r.user}::{r.whatsapp_account}": r.access for r in rows},
	}


@frappe.whitelist()
def save_access(changes):
	"""Apply [{user, whatsapp_account, access}] — access "" removes the assignment. Users
	who get a number also get the WhatsApp User role, without which the chat page and
	bubble stay hidden."""
	frappe.only_for(EDIT_ROLES)
	if isinstance(changes, str):
		changes = json.loads(changes)

	valid = {wa_access.RESPONSIBLE, wa_access.SPECTATOR}
	for change in changes or []:
		user = change.get("user")
		account = change.get("whatsapp_account")
		access = change.get("access") or ""
		if not user or not account or not frappe.db.exists("WhatsApp Account", account):
			continue
		if access and access not in valid:
			frappe.throw(_("Unknown access level: {0}").format(access))

		name = frappe.db.get_value("WhatsApp Number Access", {"user": user, "whatsapp_account": account})
		if not access:
			if name:
				frappe.delete_doc("WhatsApp Number Access", name, ignore_permissions=True)
			continue
		if name:
			frappe.db.set_value("WhatsApp Number Access", name, "access", access)
		else:
			frappe.get_doc(
				{
					"doctype": "WhatsApp Number Access",
					"whatsapp_account": account,
					"user": user,
					"access": access,
				}
			).insert(ignore_permissions=True)
		_ensure_chat_role(user)

	frappe.cache.delete_value(wa_access.CACHE_KEY)
	return get_matrix()


@frappe.whitelist()
def add_user(user):
	"""Put a user on the matrix by giving them the WhatsApp User role."""
	frappe.only_for(EDIT_ROLES)
	_ensure_chat_role(user)
	return get_matrix()


def _ensure_chat_role(user):
	if CHAT_ROLE not in frappe.get_roles(user) and frappe.db.exists("Role", CHAT_ROLE):
		doc = frappe.get_doc("User", user)
		doc.flags.ignore_permissions = True
		doc.add_roles(CHAT_ROLE)
