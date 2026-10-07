import frappe

from erpnext.payroll_ua.employee_names import full_name_column


def execute():
	Employee = frappe.qb.DocType("Employee")
	frappe.qb.update(Employee).set(Employee.employee_name, full_name_column(Employee)).run()
