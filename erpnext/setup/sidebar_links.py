"""Add our links to a stock Workspace Sidebar without editing its upstream JSON.

On v16 a desk page or list gets a left menu only when some Workspace Sidebar links to it. The
stock sidebars ship from upstream `erpnext/workspace_sidebar/*.json`, which upstream edits
often, so our links are added here on every migrate instead of in those files.

The rows are written straight to the table without touching the sidebar's `modified`. Sync
re-imports a sidebar file only when it is newer than the record, so bumping `modified` here
would silently block every later upstream change to that sidebar. When upstream does
re-import it, our rows are dropped with the old ones and the next migrate puts them back.
"""

import frappe


def add_links(sidebar, insert_after, links):
	"""Insert the missing `links` after the top-level DocType link `insert_after`, in order."""
	if not frappe.db.exists("Workspace Sidebar", sidebar):
		return

	rows = frappe.get_all(
		"Workspace Sidebar Item",
		filters={"parent": sidebar, "parenttype": "Workspace Sidebar", "parentfield": "items"},
		fields=["name", "idx", "link_to", "link_type", "child"],
		order_by="idx asc",
	)
	present = {(r.link_type, r.link_to) for r in rows}
	missing = [link for link in links if (link["link_type"], link["link_to"]) not in present]
	missing = [link for link in missing if frappe.db.exists(link["link_type"], link["link_to"])]
	if not missing:
		return

	anchor = next(
		(r for r in rows if r.link_to == insert_after and r.link_type == "DocType" and not r.child), None
	)
	position = rows.index(anchor) + 1 if anchor else len(rows)
	ordered = [r.name for r in rows[:position]] + [None] * len(missing) + [r.name for r in rows[position:]]

	new_names = iter(_insert(sidebar, link) for link in missing)
	for idx, name in enumerate(ordered, start=1):
		name = name or next(new_names)
		frappe.db.set_value("Workspace Sidebar Item", name, "idx", idx, update_modified=False)


def _insert(sidebar, link):
	row = frappe.new_doc("Workspace Sidebar Item")
	row.update(
		{
			**link,
			"parent": sidebar,
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
