import frappe


def sync_employee_designation_name_en(doc, method=None):
	_sync_employee_field(doc, "designation", "designation_name_en")


def sync_employee_department_name_en(doc, method=None):
	_sync_employee_field(doc, "department", "department_name_en")


def _sync_employee_field(doc, link_field, fieldname):
	if not doc.has_value_changed(fieldname):
		return

	frappe.db.set_value(
		"Employee",
		{link_field: doc.name},
		fieldname,
		doc.get(fieldname),
		update_modified=False,
	)
