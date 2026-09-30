"""Who may see and answer which WhatsApp chats.

Chats belong to a business number (WhatsApp Account). A user reaches a chat only
through a `WhatsApp Number Access` row for that number: `Responsible` reads and
writes, `Spectator` only reads. System Manager reaches every number with full
rights.

Who works with WhatsApp at all is a role: `WhatsApp User` chats on the numbers they
are given, `WhatsApp Manager` also opens the WhatsApp Overview, edits the numbers'
cards and gives people access. A manager still sees only the chats of their own
numbers. The same rule backs the chat API, desk list queries, form permission
checks and the realtime fan-out, so no path shows a chat its number hides.
"""

import frappe
from frappe import _

ADMIN_ROLE = "System Manager"
CHAT_ROLE = "WhatsApp User"
MANAGER_ROLE = "WhatsApp Manager"
RESPONSIBLE = "Responsible"
SPECTATOR = "Spectator"
CACHE_KEY = "whatsapp_access_map"


def _access_map():
	"""{user: {account: access}} for every access row, cached until a row changes."""
	cached = frappe.cache.get_value(CACHE_KEY)
	if cached is not None:
		return cached
	result = {}
	if frappe.db.table_exists("WhatsApp Number Access"):
		for row in frappe.get_all("WhatsApp Number Access", fields=["user", "whatsapp_account", "access"]):
			result.setdefault(row.user, {})[row.whatsapp_account] = row.access
	frappe.cache.set_value(CACHE_KEY, result)
	return result


def is_admin(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or ADMIN_ROLE in frappe.get_roles(user)


def is_manager(user=None):
	user = user or frappe.session.user
	return is_admin(user) or MANAGER_ROLE in frappe.get_roles(user)


def require_manager():
	if not is_manager():
		frappe.throw(_("Only WhatsApp managers can do this"), frappe.PermissionError)


def all_accounts():
	if not frappe.db.table_exists("WhatsApp Account"):
		return []
	return frappe.get_all("WhatsApp Account", pluck="name", order_by="creation asc")


def access_by_account(user=None):
	"""{account: access} for the user; System Manager gets Responsible on every number."""
	user = user or frappe.session.user
	if is_admin(user):
		return {name: RESPONSIBLE for name in all_accounts()}
	return dict(_access_map().get(user, {}))


def accounts_for(user=None, write=False):
	rights = access_by_account(user)
	return {a for a, access in rights.items() if not write or access == RESPONSIBLE}


def can_access(account, write=False, user=None):
	return bool(account) and account in accounts_for(user, write=write)


def require_account(account, write=False):
	if not can_access(account, write=write):
		if write and can_access(account):
			frappe.throw(_("You can only read chats of this WhatsApp number"), frappe.PermissionError)
		frappe.throw(_("Not permitted to access chats of this WhatsApp number"), frappe.PermissionError)


def require_chat(chat, write=False):
	"""Load a WhatsApp Chat the current user may read (or write, with `write`)."""
	if not chat or not frappe.db.exists("WhatsApp Chat", chat):
		frappe.throw(_("Chat not found"), frappe.DoesNotExistError)
	doc = frappe.get_doc("WhatsApp Chat", chat)
	require_account(doc.whatsapp_account, write=write)
	return doc


def users_for_account(account):
	"""Enabled users who can see chats of `account`: its access rows plus System Managers."""
	users = {user for user, rights in _access_map().items() if account in rights}
	users |= set(
		frappe.get_all("Has Role", filters={"parenttype": "User", "role": ADMIN_ROLE}, pluck="parent")
	)
	users.add("Administrator")
	return set(frappe.get_all("User", filters={"enabled": 1, "name": ["in", list(users)]}, pluck="name"))


def responsible_users(account):
	return frappe.get_all(
		"WhatsApp Number Access",
		filters={"whatsapp_account": account, "access": RESPONSIBLE},
		fields=["user", "full_name"],
		order_by="full_name asc",
	)


def account_labels():
	"""{account: {label, display_phone_number, verified_name}} for every WhatsApp Account."""
	if not frappe.db.table_exists("WhatsApp Account"):
		return {}
	fields = ["name", "account_name"]
	meta = frappe.get_meta("WhatsApp Account")
	for f in ("display_phone_number", "verified_name", "profile_image"):
		if meta.has_field(f):
			fields.append(f)
	out = {}
	for row in frappe.get_all("WhatsApp Account", fields=fields):
		number = row.get("display_phone_number")
		out[row.name] = {
			"label": number or row.account_name or row.name,
			"display_phone_number": number,
			"verified_name": row.get("verified_name"),
			"profile_image": row.get("profile_image"),
			"account_name": row.account_name or row.name,
		}
	return out


def my_accounts():
	"""The current user's numbers with labels and access, for the desk (boot + pages)."""
	labels = account_labels()
	return [
		dict(labels.get(name, {"label": name}), name=name, access=access, read_only=access != RESPONSIBLE)
		for name, access in access_by_account().items()
	]


def boot_session(bootinfo):
	if frappe.session.user == "Guest":
		return
	try:
		bootinfo.whatsapp_accounts = my_accounts()
		bootinfo.whatsapp_manager = 1 if is_manager() else 0
	except Exception:
		bootinfo.whatsapp_accounts = []
		bootinfo.whatsapp_manager = 0


# ---------------------------------------------------------------------------
# Desk permission hooks (hooks.py)
# ---------------------------------------------------------------------------


def _account_condition(doctype, user):
	user = user or frappe.session.user
	if is_admin(user):
		return ""
	accounts = accounts_for(user)
	if not accounts:
		return "1=0"
	values = ", ".join(frappe.db.escape(a) for a in accounts)
	return f"`tab{doctype}`.`whatsapp_account` in ({values})"


def chat_query_conditions(user=None, doctype=None):
	return _account_condition("WhatsApp Chat", user)


def message_query_conditions(user=None, doctype=None):
	return _account_condition("WhatsApp Message", user)


def has_permission(doc, ptype=None, user=None, debug=False):
	user = user or frappe.session.user
	if is_admin(user):
		return True
	write = ptype not in (None, "read", "select", "print", "email", "export", "report", "share")
	account = doc.get("whatsapp_account")
	if not account:
		# A message being created before the fork fills in its account.
		return bool(accounts_for(user, write=write))
	return can_access(account, write=write, user=user)
