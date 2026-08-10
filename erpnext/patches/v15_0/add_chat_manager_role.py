"""Provision the `Chat Manager` role, which may purge an archived chat with all of its
messages and attachments (erpnext.crm.page.employee_chat.employee_chat.purge_thread)."""

import frappe

from erpnext.patches.setup_custom_fields import setup_chat_manager_role


def execute():
	setup_chat_manager_role()
	frappe.db.commit()
