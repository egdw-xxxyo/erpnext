"""Зарплата підрозділу — те саме, що бачить бухгалтерія у відомості, але лише свої люди.

Керівник бачить тих, хто на нього звітує (`Employee.reports_to`), і нікого більше. Повний список
доступний ролям HR Manager / System Manager.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_last_day, getdate

from erpnext.hr.salary_advance import ADVANCE_CARD, ADVANCE_CASH
from erpnext.hr.salary_split import CASH_COMPONENT

FULL_ACCESS_ROLES = {"HR Manager", "System Manager", "Administrator"}


def execute(filters=None):
	filters = frappe._dict(filters or {})

	if not filters.company or not filters.year or not filters.month:
		frappe.throw(_("Select the company, the year and the month."))

	start = getdate(f"{filters.year}-{int(filters.month):02d}-01")
	end = get_last_day(start)
	employees = visible_employees(filters.company)

	if employees is not None and not employees:
		return columns(), []

	return columns(), rows(filters.company, start, end, employees)


def visible_employees(company):
	"""None — видно всіх; інакше список підлеглих поточного користувача."""
	if FULL_ACCESS_ROLES & set(frappe.get_roles()):
		return None

	employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"}, "name")

	if not employee:
		return []

	return frappe.get_all(
		"Employee",
		filters={"company": company, "reports_to": employee},
		pluck="name",
	)


def rows(company, start, end, employees):
	conditions = {"company": company, "docstatus": 1, "start_date": [">=", start], "end_date": ["<=", end]}

	if employees is not None:
		conditions["employee"] = ["in", employees]

	slips = frappe.get_all(
		"Salary Slip",
		filters=conditions,
		fields=["name", "employee", "employee_name", "department", "payment_days", "gross_pay", "net_pay"],
		order_by="department asc, employee_name asc",
	)

	if not slips:
		return []

	cash = dict(
		frappe.get_all(
			"Salary Detail",
			filters={
				"parent": ["in", [slip.name for slip in slips]],
				"parenttype": "Salary Slip",
				"salary_component": CASH_COMPONENT,
			},
			fields=["parent", "amount"],
			as_list=True,
		)
	)
	advances = advance_by_employee(company, start, end, [slip.employee for slip in slips])
	result = []

	for slip in slips:
		advance = advances.get(slip.employee, {})
		result.append(
			{
				"employee": slip.employee,
				"employee_name": slip.employee_name,
				"department": slip.department,
				"credited_days": flt(slip.payment_days),
				"gross_pay": flt(slip.gross_pay),
				"advance_card": flt(advance.get(ADVANCE_CARD)),
				"advance_cash": flt(advance.get(ADVANCE_CASH)),
				"salary_card": flt(slip.net_pay),
				"salary_cash": flt(cash.get(slip.name)),
				"salary_slip": slip.name,
			}
		)

	return result


def advance_by_employee(company, start, end, employees):
	rows = frappe.get_all(
		"Additional Salary",
		filters={
			"company": company,
			"docstatus": 1,
			"employee": ["in", employees],
			"payroll_date": ["between", [start, end]],
			"salary_component": ["in", [ADVANCE_CARD, ADVANCE_CASH]],
		},
		fields=["employee", "salary_component", "amount"],
	)
	by_employee = {}

	for row in rows:
		by_employee.setdefault(row.employee, {})
		by_employee[row.employee][row.salary_component] = flt(
			by_employee[row.employee].get(row.salary_component)
		) + flt(row.amount)

	return by_employee


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
		{"fieldname": "credited_days", "label": _("Credited Days"), "fieldtype": "Float", "width": 110},
		{"fieldname": "gross_pay", "label": _("Accrued"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "advance_card", "label": _("Advance to Card"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "advance_cash", "label": _("Advance in Cash"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "salary_card", "label": _("Salary to Card"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "salary_cash", "label": _("Salary in Cash"), "fieldtype": "Currency", "width": 130},
		{
			"fieldname": "salary_slip",
			"label": _("Salary Slip"),
			"fieldtype": "Link",
			"options": "Salary Slip",
			"width": 150,
		},
	]
