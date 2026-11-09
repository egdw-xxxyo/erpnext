import frappe

BUILTINS = [
	("Search", "Search", "search", 10),
	("Scanner", "Scan barcode", "barcode", 20),
	("Notifications", "Notification", "bell", 30),
	("Tasks", "Tasks", "list", 40),
]


def execute():
	frappe.reload_doc("setup", "doctype", "sidebar_menu_item")
	for key, label, icon, order in BUILTINS:
		if frappe.db.exists("Sidebar Menu Item", {"builtin": key}):
			continue
		frappe.get_doc(
			{
				"doctype": "Sidebar Menu Item",
				"builtin": key,
				"label": label,
				"icon": icon,
				"sort_order": order,
				"link_type": "Page",
			}
		).insert(ignore_permissions=True)

	frappe.db.set_value(
		"Sidebar Menu Item",
		{"link_to": "attendance-sheet", "sidebar": ["is", "not set"], "sort_order": 0},
		"sort_order",
		50,
	)
