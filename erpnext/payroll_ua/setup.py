import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

ATTENDANCE_STATUSES = "\nPresent\nAbsent\nSick Leave\nOn Leave\nHalf Day\nWork From Home"


def setup_attendance_sheet():
	"""Adds what the attendance sheet needs to the HR doctypes it reads.

	These fields sit on doctypes hrms owns, and hrms is installed after erpnext, so this
	runs after every migration rather than on install: at install time there is nothing
	yet to hang them on. Both calls below skip what is already there.
	"""
	create_custom_fields(get_custom_fields(), ignore_validate=True)

	for doctype, fieldname, prop, value, prop_type in get_property_setters():
		if frappe.db.exists("DocType", doctype):
			make_property_setter(
				doctype, fieldname, prop, value, prop_type, validate_fields_for_doctype=False
			)


def get_custom_fields() -> dict:
	return {
		"Attendance": [
			{
				"fieldname": "overtime_hours",
				"fieldtype": "Float",
				"label": _("Overtime Hours"),
				"non_negative": 1,
				"precision": "2",
				"insert_after": "working_hours",
			},
			{
				"fieldname": "shortfall_hours",
				"fieldtype": "Float",
				"label": _("Shortfall Hours"),
				"non_negative": 1,
				"precision": "2",
				"insert_after": "overtime_hours",
			},
		],
		"Employee": [
			{
				"fieldname": "attendance_sheet_section",
				"fieldtype": "Section Break",
				"label": _("Attendance Sheet"),
				"insert_after": "default_shift",
			},
			{
				"description": _(
					"Employees this one fills the attendance sheet for on top of their direct reports. "
					"They are listed first in the sheet."
				),
				"fieldname": "attendance_sheet_extra_employees",
				"fieldtype": "Table MultiSelect",
				"ignore_user_permissions": 1,
				"label": _("Additional Employees in Attendance Sheet"),
				"options": "Attendance Sheet Extra Employee",
				"insert_after": "attendance_sheet_section",
			},
		],
		"Leave Type": [
			{
				"description": _(
					"Shown in the attendance sheet on the days of this leave. "
					"Days of a leave without an abbreviation are marked as leave in general."
				),
				"fieldname": "attendance_sheet_abbr",
				"fieldtype": "Data",
				"label": _("Attendance Sheet Abbreviation"),
				"length": 5,
				"insert_after": "leave_type_name",
			},
		],
	}


def get_property_setters() -> list[tuple]:
	"""A sick day is a status of its own, and half days are no longer filed.

	The half day fields are hidden rather than removed: applications filed before we
	stopped using them still carry the values, and dropping the fields would take those
	days out of sight while they are still what the application says.
	"""
	return [
		("Attendance", "status", "options", ATTENDANCE_STATUSES, "Text"),
		("Leave Application", "half_day", "hidden", 1, "Check"),
		("Leave Application", "half_day", "read_only", 1, "Check"),
		("Leave Application", "half_day_date", "hidden", 1, "Check"),
		("Leave Application", "half_day_date", "read_only", 1, "Check"),
		("Leave Application", "half_day_date", "depends_on", "", "Code"),
	]
