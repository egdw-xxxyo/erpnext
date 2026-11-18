import frappe

from erpnext.setup.doctype.helper_settings.helper_settings import DEFAULT_GUIDE_NAMING_SERIES


def execute():
	if not frappe.db.get_single_value("Helper Settings", "guide_naming_series"):
		settings = frappe.get_single("Helper Settings")
		settings.guide_naming_series = DEFAULT_GUIDE_NAMING_SERIES
		settings.save(ignore_permissions=True)
