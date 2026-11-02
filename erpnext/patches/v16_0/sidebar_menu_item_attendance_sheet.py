import frappe


def execute():
	frappe.reload_doc("setup", "doctype", "sidebar_menu_item")
	if frappe.db.exists("Sidebar Menu Item", {"link_to": "attendance-sheet", "sidebar": ["is", "not set"]}):
		return
	frappe.get_doc(
		{
			"doctype": "Sidebar Menu Item",
			"label": "Attendance Sheet",
			"link_type": "Page",
			"link_to": "attendance-sheet",
			"icon": "sheet",
			"required_doctype": "Attendance",
		}
	).insert(ignore_permissions=True)
