import frappe


def execute():
	"""Sick Leave Case became submittable: a case already marked final is submitted, so payroll keeps it."""
	names = frappe.get_all("Sick Leave Case", filters={"closed": 1, "docstatus": 0}, pluck="name")
	if not names:
		return
	frappe.db.set_value("Sick Leave Case", {"name": ("in", names)}, "docstatus", 1, update_modified=False)
	frappe.db.set_value(
		"Sick Leave Certificate",
		{"parent": ("in", names), "parenttype": "Sick Leave Case"},
		"docstatus",
		1,
		update_modified=False,
	)
