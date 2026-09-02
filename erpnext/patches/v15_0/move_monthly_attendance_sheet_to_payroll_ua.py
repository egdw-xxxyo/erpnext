import frappe

REPORT = "Monthly Attendance Sheet"
MODULE = "Payroll UA"


def execute():
	"""Point the Monthly Attendance Sheet report at Payroll UA.

	The report file moved from hrms to erpnext, but importing the JSON is not enough:
	frappe skips a file whose `modified` is not newer than the DB row, and that row gets
	its timestamp bumped during the very migration that should carry the move.
	"""
	if not frappe.db.exists("Report", REPORT):
		return

	if frappe.db.get_value("Report", REPORT, "module") != MODULE:
		frappe.db.set_value("Report", REPORT, "module", MODULE)
