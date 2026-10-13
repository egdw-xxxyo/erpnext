import frappe
from frappe.permissions import add_permission

from erpnext.correspondence.forwarding_accounts import MANAGER_ROLE

READ_ONLY = ("Email Account", "Communication")


def execute():
	if not frappe.db.exists("Role", MANAGER_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": MANAGER_ROLE, "desk_access": 1}).insert(
			ignore_permissions=True
		)
	for doctype in READ_ONLY:
		if not frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": MANAGER_ROLE, "permlevel": 0}):
			add_permission(doctype, MANAGER_ROLE)
