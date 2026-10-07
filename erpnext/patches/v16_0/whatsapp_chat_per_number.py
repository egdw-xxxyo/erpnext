"""Chats become one per (business number, customer) and managers move from chats to numbers.

- messages without an account go to the default account;
- every chat gets the account of its latest message (a customer who wrote to two numbers
  gets a second chat);
- whoever was a manager of any chat becomes Responsible for that chat's number;
- the per-chat `WhatsApp Chat Manager` table is dropped.
"""

import frappe


def execute():
	if not frappe.db.table_exists("WhatsApp Account") or not frappe.db.table_exists("WhatsApp Chat"):
		return

	accounts = frappe.get_all("WhatsApp Account", pluck="name", order_by="creation asc")
	if not accounts:
		return
	default = (
		frappe.db.get_value("WhatsApp Account", {"is_default_incoming": 1}, "name")
		or frappe.db.get_value("WhatsApp Account", {"is_default_outgoing": 1}, "name")
		or accounts[0]
	)

	frappe.db.sql(
		"update `tabWhatsApp Message` set whatsapp_account = %s where ifnull(whatsapp_account, '') = ''",
		default,
	)

	chats = frappe.db.sql("select name, phone, whatsapp_account from `tabWhatsApp Chat`", as_dict=True)
	for chat in chats:
		if chat.whatsapp_account:
			continue
		used = frappe.db.sql(
			"""
			select whatsapp_account, max(creation) as last
			from `tabWhatsApp Message`
			where `from` = %(phone)s or `to` = %(phone)s
			group by whatsapp_account
			order by last desc
			""",
			{"phone": chat.phone},
			as_dict=True,
		)
		own = used[0].whatsapp_account if used else default
		frappe.db.set_value("WhatsApp Chat", chat.name, "whatsapp_account", own, update_modified=False)
		for other in used[1:]:
			_split_chat(chat.name, other.whatsapp_account)

	_seed_access(default)

	if frappe.db.exists("DocType", "WhatsApp Chat Manager"):
		frappe.delete_doc("DocType", "WhatsApp Chat Manager", ignore_missing=True, force=True)
	frappe.cache.delete_value("whatsapp_access_map")
	frappe.cache.delete_value("whatsapp_chats_backfilled")


def _split_chat(source, account):
	"""A second chat for the same customer on another number, with the same identity links."""
	src = frappe.get_doc("WhatsApp Chat", source)
	copy = frappe.get_doc(
		{
			"doctype": "WhatsApp Chat",
			"whatsapp_account": account,
			"phone": src.phone,
			"contact": src.contact,
			"title": src.title,
			"chat_type": src.chat_type,
			"links": [{"link_doctype": r.link_doctype, "link_name": r.link_name} for r in src.links],
		}
	)
	copy.flags.ignore_links = True
	copy.insert(ignore_permissions=True)
	last = frappe.db.sql(
		"""
		select creation, message, content_type from `tabWhatsApp Message`
		where whatsapp_account = %(account)s and (`from` = %(phone)s or `to` = %(phone)s)
		order by creation desc limit 1
		""",
		{"account": account, "phone": src.phone},
		as_dict=True,
	)
	if last:
		frappe.db.set_value(
			"WhatsApp Chat",
			copy.name,
			{
				"last_message_on": last[0].creation,
				"last_preview": (last[0].message or "")[:200],
				"last_content_type": last[0].content_type,
			},
			update_modified=False,
		)


def _seed_access(default):
	if not frappe.db.table_exists("WhatsApp Chat Manager") or not frappe.db.table_exists(
		"WhatsApp Number Access"
	):
		return
	account_of = {
		c.name: c.whatsapp_account or default
		for c in frappe.db.sql("select name, whatsapp_account from `tabWhatsApp Chat`", as_dict=True)
	}
	pairs = set()
	for row in frappe.db.sql(
		"select parent, user from `tabWhatsApp Chat Manager` where parenttype = 'WhatsApp Chat'", as_dict=True
	):
		if row.user and row.parent in account_of and frappe.db.exists("User", row.user):
			pairs.add((account_of[row.parent], row.user))
	for account, user in sorted(pairs):
		if frappe.db.exists("WhatsApp Number Access", {"whatsapp_account": account, "user": user}):
			continue
		frappe.get_doc(
			{
				"doctype": "WhatsApp Number Access",
				"whatsapp_account": account,
				"user": user,
				"access": "Responsible",
			}
		).insert(ignore_permissions=True)
