import frappe
from frappe.utils import date_diff


def execute():
	"""Sick Leave Case is one ЕЛН now and hangs under an Incapacity Case: every existing case
	gets its own Incapacity Case and the numbers of its old certificate rows."""
	has_rows = frappe.db.table_exists("Sick Leave Certificate")

	for case in frappe.get_all(
		"Sick Leave Case",
		filters={"incapacity_case": ("is", "not set")},
		fields=["name", "employee", "company", "case_type", "start_date", "end_date"],
	):
		numbers = []

		if has_rows:
			numbers = frappe.get_all(
				"Sick Leave Certificate",
				filters={"parent": case.name, "parenttype": "Sick Leave Case"},
				order_by="from_date asc",
				pluck="eln_number",
			)

		parent = frappe.new_doc("Incapacity Case")
		parent.employee = case.employee
		parent.company = case.company
		parent.case_type = case.case_type
		parent.start_date = case.start_date
		parent.end_date = case.end_date
		parent.calendar_days = date_diff(case.end_date, case.start_date) + 1
		parent.flags.ignore_permissions = True
		parent.insert()
		frappe.db.set_value(
			"Sick Leave Case",
			case.name,
			{"incapacity_case": parent.name, "eln_number": ", ".join(n for n in numbers if n)},
			update_modified=False,
		)
		parent.refresh_summary()

	frappe.delete_doc("DocType", "Sick Leave Certificate", ignore_missing=True, force=True)
