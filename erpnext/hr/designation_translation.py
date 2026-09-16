import frappe


def sync_employee_designation_name_en(doc, method=None):
	if not doc.has_value_changed("designation_name_en"):
		return

	frappe.db.set_value(
		"Employee",
		{"designation": doc.name},
		"designation_name_en",
		doc.designation_name_en,
		update_modified=False,
	)
