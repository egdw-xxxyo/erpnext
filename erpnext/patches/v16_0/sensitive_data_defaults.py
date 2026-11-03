import frappe

SETTINGS = "Sensitive Data Settings"

DOCTYPES = (
	"Payroll Sheet",
	"Management Payroll Sheet",
	"Salary Advance",
	"Salary Change",
	"Salary Approval",
	"Payroll Tax Settings",
	"Salary Structure",
	"Salary Structure Assignment",
)

REPORTS = ("Payroll by Department", "Salary History")

PAGES = ("access-console",)

EMPLOYEE_FIELDS = (
	"ctc",
	"custom_total_salary",
	"custom_official_salary",
	"custom_cash_salary",
	"custom_official_salary_net",
	"custom_official_bonus",
	"custom_official_bonus_month",
	"custom_reservation_salary",
	"custom_salary_effective_from",
)


def execute():
	frappe.reload_doc("access_control", "doctype", "sensitive_data_object")
	frappe.reload_doc("access_control", "doctype", "sensitive_data_field")
	frappe.reload_doc("access_control", "doctype", "sensitive_data_api_user")
	frappe.reload_doc("access_control", "doctype", "sensitive_data_settings")
	settings = frappe.get_single(SETTINGS)
	if settings.objects or settings.fields:
		return
	meta = frappe.get_meta("Employee")
	settings.update(
		{
			"enabled": 0,
			"unlock_minutes": 30,
			"idle_minutes": 10,
			"max_attempts": 5,
			"objects": [
				*(
					{"object_type": "DocType", "object_name": name}
					for name in DOCTYPES
					if frappe.db.exists("DocType", name)
				),
				*(
					{"object_type": "Report", "object_name": name}
					for name in REPORTS
					if frappe.db.exists("Report", name)
				),
				*(
					{"object_type": "Page", "object_name": name}
					for name in PAGES
					if frappe.db.exists("Page", name)
				),
			],
			"fields": [
				{"document_type": "Employee", "fieldname": fieldname}
				for fieldname in EMPLOYEE_FIELDS
				if meta.get_field(fieldname)
			],
		}
	)
	settings.flags.ignore_permissions = True
	settings.save()
