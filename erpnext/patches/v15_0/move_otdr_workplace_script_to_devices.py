import frappe

# Second wave of the Manufacturing -> Devices module move: OTDR, Workplace Script
# and the Print Queue page. Permissions (roles) are unchanged and keep living in
# each JSON; this patch only reassigns the module so the records match the new
# folder layout even if a JSON sync is skipped.
MOVED_DOCTYPES = [
	"OTDR",
	"OTDR Configuration",
	"OTDR Measurement Log Entry",
	"OTDR QC Item",
	"Workplace Script",
	"Workplace Script State",
	"Workplace Script Subflow Entry",
	"Workplace Script Transition",
	"Workplace Script Version",
]

MOVED_PAGES = ["print-queue"]


def execute():
	if not frappe.db.exists("Module Def", "Devices"):
		frappe.get_doc(
			{
				"doctype": "Module Def",
				"module_name": "Devices",
				"app_name": "erpnext",
			}
		).insert(ignore_permissions=True)

	for dt in MOVED_DOCTYPES:
		if frappe.db.exists("DocType", dt):
			frappe.db.set_value("DocType", dt, "module", "Devices", update_modified=False)

	for page in MOVED_PAGES:
		if frappe.db.exists("Page", page):
			frappe.db.set_value("Page", page, "module", "Devices", update_modified=False)

	frappe.clear_cache()
