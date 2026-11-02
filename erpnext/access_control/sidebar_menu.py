"""Role-gated, UI-configured sidebar items (doctype `Sidebar Menu Item`).

Applied to the boot payload after Frappe has built the sidebars:
- row without `sidebar` -> global item under "Tasks" (rendered by `global_todo_sidebar.js`);
- row with `sidebar` whose target already exists there -> restricts that item to the row's roles
  (or hides it when disabled);
- row with `sidebar` and a new target -> inserted into that sidebar.
"""

import frappe
from frappe import _

FIELDS = [
	"name",
	"label",
	"sidebar",
	"link_type",
	"link_to",
	"icon",
	"required_doctype",
	"sort_order",
	"disabled",
]


def allowed(row, roles: set, user: str) -> bool:
	if row.disabled:
		return False
	if user == "Administrator":
		return True
	row_roles = {
		r.role
		for r in frappe.get_all("Has Role", {"parent": row.name, "parenttype": "Sidebar Menu Item"}, ["role"])
	}
	if row_roles and not row_roles & roles:
		return False
	return not row.required_doctype or frappe.has_permission(row.required_doctype, "read")


def boot_session(bootinfo):
	if frappe.session.user == "Guest" or not frappe.db.table_exists("Sidebar Menu Item"):
		return

	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	rows = frappe.get_all("Sidebar Menu Item", fields=FIELDS, order_by="sort_order asc, creation asc")

	bootinfo.global_sidebar_items = [
		{"label": _(r.label), "link_type": r.link_type, "link_to": r.link_to, "icon": r.icon or "list"}
		for r in rows
		if not r.sidebar and allowed(r, roles, user)
	]

	sidebars = bootinfo.get("workspace_sidebar_item") or {}
	for row in rows:
		if not row.sidebar:
			continue
		sidebar = sidebars.get(row.sidebar.lower())
		if sidebar is None:
			continue
		items = sidebar["items"]
		existing = [
			i for i in items if i.get("link_to") == row.link_to and i.get("link_type") == row.link_type
		]
		visible = allowed(row, roles, user)
		if existing:
			if not visible:
				sidebar["items"] = [i for i in items if i not in existing]
			continue
		if not visible:
			continue
		item = {
			"label": _(row.label),
			"link_to": row.link_to,
			"link_type": row.link_type,
			"type": "Link",
			"icon": row.icon,
			"child": 0,
			"collapsible": 1,
			"indent": 0,
			"keep_closed": 0,
			"url": row.link_to if row.link_type == "URL" else None,
			"show_arrow": 0,
		}
		pos = row.sort_order - 1 if row.sort_order > 0 else len(items)
		items.insert(min(pos, len(items)), item)
