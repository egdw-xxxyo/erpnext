import frappe

DOCTYPES = (
	"Attendance Sheet Approval",
	"Attendance Sheet Approval Employee",
	"Attendance Sheet Extra Employee",
)
MODULE = "Payroll UA"


def execute():
	"""Point the attendance sheet doctypes at Payroll UA.

	The files moved from hrms to erpnext, but importing the JSON is not enough: frappe
	skips a file whose `modified` is not newer than the DB row. The tables are left alone
	— their names come from the doctype, not from the module.
	"""
	for doctype in DOCTYPES:
		if frappe.db.get_value("DocType", doctype, "module") not in (None, MODULE):
			frappe.db.set_value("DocType", doctype, "module", MODULE)
