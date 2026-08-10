# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Chat attachments are private to their thread.

A file someone drops into a chat must not turn into a system-wide asset: it must not show up
in the file-library picker of an unrelated form, and it must not be re-attached to another
document. Sharing a chat file elsewhere is allowed only as a *copy* — upload it again — so the
chat message stays the single place where the original lives.

Two guards, both registered in hooks.py:
  * `get_permission_query_conditions` keeps chat files out of every `File` list query (the
	library browser and search are plain `frappe.get_list("File")` calls).
  * `block_reuse` refuses an insert that points a new File row at a chat file's url, which is
	what the "attach from library" path does (frappe.handler.attach_file).

Neither touches downloading or previewing: those go through `File.has_permission`, which
delegates to Chat Thread's participant check.
"""

import frappe
from frappe import _

CHAT_ATTACHMENT_DOCTYPE = "Chat Thread"


def get_permission_query_conditions(user=None):
	if (user or frappe.session.user) == "Administrator":
		return ""
	return f"ifnull(`tabFile`.`attached_to_doctype`, '') != '{CHAT_ATTACHMENT_DOCTYPE}'"


def block_reuse(doc, method=None):
	"""Refuse a File row that reuses a chat attachment's url for anything but the chat."""
	if not doc.file_url or doc.attached_to_doctype == CHAT_ATTACHMENT_DOCTYPE:
		return
	if frappe.db.exists("File", {"file_url": doc.file_url, "attached_to_doctype": CHAT_ATTACHMENT_DOCTYPE}):
		frappe.throw(
			_("Chat attachments cannot be attached elsewhere. Download the file and upload a copy."),
			frappe.PermissionError,
		)
