"""Sort the existing chats into the three kinds the chat lists are split by: direct (two
people, one per pair), group (named, with an admin) and document chats.

- a "Direct" thread that does not have exactly two participants is a group;
- every group gets a name (its people) if it has none;
- every group gets an admin if it has none: its creator when still in it, else the first person.
"""

import frappe


def execute():
	from erpnext.crm.page.employee_chat.employee_chat import _default_group_title

	for name in frappe.get_all(
		"Chat Thread", filters={"thread_type": ["in", ["Direct", "Group"]]}, pluck="name"
	):
		doc = frappe.get_doc("Chat Thread", name)
		users = [p.user for p in doc.participants if p.user]
		changed = False
		if doc.thread_type == "Direct" and len(users) != 2:
			doc.thread_type = "Group"
			changed = True
		if doc.thread_type == "Group":
			if not (doc.title or "").strip():
				doc.title = _default_group_title(users) or doc.name
				changed = True
			if doc.participants and not any(p.role == "Admin" for p in doc.participants):
				admin = next((p for p in doc.participants if p.user == doc.owner), doc.participants[0])
				admin.role = "Admin"
				changed = True
		if changed:
			doc.flags.ignore_links = True
			doc.save(ignore_permissions=True)
