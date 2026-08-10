"""Seed `Chat Thread.archived_on` for chats archived before the field existed.

There is no record of when those threads were archived. `modified` is the closest proxy, but
`set_archived` writes with `update_modified=False`, so for a thread archived long after its last
save `modified` is too old. Taking the later of `modified` and `last_message_on` keeps the estimate
conservative — the age-based deep archive job then waits at least as long as it should, never less.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Chat Thread"):
		return
	frappe.db.sql(
		"""
		update `tabChat Thread`
		set archived_on = greatest(ifnull(modified, last_message_on), ifnull(last_message_on, modified))
		where ifnull(is_archived, 0) = 1 and archived_on is null
		"""
	)
