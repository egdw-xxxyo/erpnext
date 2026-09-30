"""WhatsApp Access page folded into the WhatsApp Overview; managers become a role.

Numbers are now assigned on each number's card in the overview, and the new Employees
tab decides who works with WhatsApp: `WhatsApp User` chats, `WhatsApp Manager` also
configures. Sales Managers used to configure WhatsApp; those who already chat keep that
right through the new role.
"""

import frappe

from erpnext.crm import whatsapp_access as wa_access


def execute():
	ensure_manager_role()

	if frappe.db.exists("Page", "whatsapp-access"):
		frappe.delete_doc("Page", "whatsapp-access", force=True, ignore_missing=True)
	frappe.db.delete("Workspace Sidebar Item", {"link_type": "Page", "link_to": "whatsapp-access"})

	chat_users = set(
		frappe.get_all(
			"Has Role", filters={"parenttype": "User", "role": wa_access.CHAT_ROLE}, pluck="parent"
		)
	)
	sales_managers = set(
		frappe.get_all("Has Role", filters={"parenttype": "User", "role": "Sales Manager"}, pluck="parent")
	)
	for user in chat_users & sales_managers:
		if user in ("Administrator", "Guest"):
			continue
		doc = frappe.get_doc("User", user)
		doc.flags.ignore_permissions = True
		doc.add_roles(wa_access.MANAGER_ROLE)


def ensure_manager_role():
	if not frappe.db.exists("Role", wa_access.MANAGER_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": wa_access.MANAGER_ROLE, "desk_access": 1}).insert(
			ignore_permissions=True
		)
