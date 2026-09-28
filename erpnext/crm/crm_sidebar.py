"""Our chat pages in the stock CRM sidebar.

On v16 a desk page gets a left menu only when some Workspace Sidebar links to it. The CRM
sidebar ships from upstream `erpnext/workspace_sidebar/crm.json`, which upstream edits often,
so the links are added here on every migrate instead of in that file.

The rows are written straight to the table without touching the sidebar's `modified`. Sync
re-imports `crm.json` only when the file is newer than the record, so bumping `modified` here
would silently block every later upstream change to the CRM sidebar. When upstream does
re-import it, our rows are dropped with the old ones and this hook puts them back.
"""

import frappe

SIDEBAR = "CRM"
INSERT_AFTER = "Customer"
LINKS = (
	{"label": "Employee Chat", "link_to": "employee-chat", "link_type": "Page", "icon": "messages-square"},
	{
		"label": "WhatsApp Chat",
		"link_to": "whatsapp-chat-center",
		"link_type": "Page",
		"icon": "message-circle",
	},
)


def add_chat_pages():
	if not frappe.db.exists("Workspace Sidebar", SIDEBAR):
		return

	rows = frappe.get_all(
		"Workspace Sidebar Item",
		filters={"parent": SIDEBAR, "parenttype": "Workspace Sidebar", "parentfield": "items"},
		fields=["name", "idx", "link_to", "link_type", "child"],
		order_by="idx asc",
	)
	present = {(r.link_type, r.link_to) for r in rows}
	missing = [link for link in LINKS if (link["link_type"], link["link_to"]) not in present]
	missing = [link for link in missing if frappe.db.exists(link["link_type"], link["link_to"])]
	if not missing:
		return

	anchor = next(
		(r for r in rows if r.link_to == INSERT_AFTER and r.link_type == "DocType" and not r.child), None
	)
	position = rows.index(anchor) + 1 if anchor else len(rows)
	ordered = [r.name for r in rows[:position]] + [None] * len(missing) + [r.name for r in rows[position:]]

	new_names = iter(_insert(link) for link in missing)
	for idx, name in enumerate(ordered, start=1):
		name = name or next(new_names)
		frappe.db.set_value("Workspace Sidebar Item", name, "idx", idx, update_modified=False)


def _insert(link):
	row = frappe.new_doc("Workspace Sidebar Item")
	row.update(
		{
			**link,
			"parent": SIDEBAR,
			"parenttype": "Workspace Sidebar",
			"parentfield": "items",
			"type": "Link",
			"child": 0,
			"indent": 0,
			"collapsible": 1,
			"keep_closed": 0,
			"show_arrow": 0,
		}
	)
	row.db_insert()
	return row.name
