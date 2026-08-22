"""Історія окладів — який оклад у якому місяці був і буде, по всіх працівниках.

Керівник бачить лише тих, хто на нього звітує (`Employee.reports_to`), як і у звіті
«Зарплата підрозділу». Повний список — ролям HR Manager / System Manager.
"""

import frappe
from frappe import _
from frappe.utils import getdate

from erpnext.payroll_ua.report.payroll_by_department.payroll_by_department import visible_employees
from erpnext.payroll_ua.salary_history import build_history, period_label


def execute(filters=None):
	filters = frappe._dict(filters or {})

	if not filters.company:
		frappe.throw(_("Select the company."))

	return columns(), rows(filters)


def rows(filters):
	employees = employee_scope(filters)

	if employees is not None and not employees:
		return []

	conditions = {"company": filters.company, "docstatus": 1}

	if employees is not None:
		conditions["employee"] = ["in", employees]

	assignments = frappe.get_all(
		"Salary Structure Assignment",
		filters=conditions,
		fields=["name", "employee", "employee_name", "department", "from_date", "base", "variable"],
		order_by="employee asc, from_date asc",
	)

	by_employee = {}

	for assignment in assignments:
		by_employee.setdefault(assignment.employee, []).append(assignment)

	result = []

	# Історію рахуємо по кожному працівнику окремо: «діє по» одного періоду — це день перед
	# початком наступного, і сусідні рядки чужої людини тут ні до чого.
	for employee, own in by_employee.items():
		names = {row.name: row for row in own}

		for row in build_history(own):
			assignment = names[row["assignment"]]
			result.append(
				{
					**row,
					"employee": employee,
					"employee_name": assignment.employee_name,
					"department": assignment.department,
					"period": period_label(row["period"]),
				}
			)

	result = filter_period(result, filters)

	return sorted(result, key=lambda row: (row["employee_name"] or "", row["from_date"]))


def employee_scope(filters):
	"""None — видно всіх; інакше список працівників, дозволених фільтром і роллю."""
	visible = visible_employees(filters.company)

	if not filters.employee:
		return visible

	if visible is not None and filters.employee not in visible:
		return []

	return [filters.employee]


def filter_period(rows, filters):
	if not filters.from_date and not filters.to_date:
		return rows

	start = getdate(filters.from_date) if filters.from_date else None
	end = getdate(filters.to_date) if filters.to_date else None

	return [
		row
		for row in rows
		if (not end or getdate(row["from_date"]) <= end)
		and (not start or not row["to_date"] or getdate(row["to_date"]) >= start)
	]


def columns():
	return [
		{
			"fieldname": "employee",
			"label": _("Employee"),
			"fieldtype": "Link",
			"options": "Employee",
			"width": 110,
		},
		{"fieldname": "employee_name", "label": _("Employee Name"), "fieldtype": "Data", "width": 200},
		{
			"fieldname": "department",
			"label": _("Department"),
			"fieldtype": "Link",
			"options": "Department",
			"width": 160,
		},
		{"fieldname": "from_date", "label": _("From Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "to_date", "label": _("To Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "official", "label": _("Official Salary"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "cash", "label": _("Cash Salary"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "total", "label": _("Total Salary"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "change", "label": _("Change"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "period", "label": _("Period"), "fieldtype": "Data", "width": 90},
		{
			"fieldname": "assignment",
			"label": _("Salary Structure Assignment"),
			"fieldtype": "Link",
			"options": "Salary Structure Assignment",
			"width": 200,
		},
	]
