"""Найближчі виплати відпускних: кожна неоплачена відпустка, до якої дати її треба оплатити
і скільки це коштує. Оплата йде через «Відомість відпускних» місяця, де відпустка закінчується."""

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

from erpnext.hr import average_pay, payroll_tax
from erpnext.hr.salary_advance import _holiday_dates, _holiday_list
from erpnext.payroll_ua import vacation_rules
from erpnext.payroll_ua.doctype.vacation_pay_sheet.vacation_pay_sheet import EARLIEST

DEFAULT_HORIZON = 60


@frappe.whitelist()
def get_data(company, horizon=DEFAULT_HORIZON):
	frappe.has_permission("Vacation Pay Sheet", "read", throw=True)

	today = getdate(nowdate())
	until = add_days(today, cint(horizon) or DEFAULT_HORIZON)
	employees = frappe.get_all(
		"Employee",
		filters={"company": company, "status": "Active"},
		fields=[
			"name",
			"employee_name",
			"department",
			"holiday_list",
			"date_of_joining",
			vacation_rules.OPENING_FIELD,
		],
		order_by="employee_name asc",
	)
	names = [employee.name for employee in employees]
	cache = {}
	holiday_lists = {employee.name: _holiday_list(employee, company) for employee in employees}
	absences = average_pay.absence_calendar(
		names,
		EARLIEST,
		until,
		lambda name: _holiday_dates(holiday_lists.get(name), EARLIEST, until, cache),
	)
	paid = _paid_through_sheets(names)
	rows = []

	for employee in employees:
		days = sorted((absences.get(employee.name) or {}).get(average_pay.VACATION) or [])

		if not days:
			continue

		covered = int(flt(employee.get(vacation_rules.OPENING_FIELD))) + paid.get(employee.name, 0)
		remaining = vacation_rules.split_unpaid(days, covered)

		for start, end in _runs(remaining):
			if start > until:
				continue

			pay_days = remaining.index(end) + 1
			run_days = date_diff(end, start) + 1
			average = average_pay.vacation_average_details(
				frappe._dict(name=employee.name, date_of_joining=employee.date_of_joining), remaining[0]
			)
			taxes = payroll_tax.split(flt(average.average * pay_days, 2), employee.name)
			due = getdate(vacation_rules.due_date(start))

			rows.append(
				{
					"employee": employee.name,
					"employee_name": employee.employee_name,
					"department": employee.department,
					"first_day": start,
					"last_day": end,
					"days": run_days,
					"pay_days": pay_days,
					"earlier_days": pay_days - run_days,
					"due_date": due,
					"days_left": date_diff(due, today),
					"average": average.average,
					"average_note": _average_note(average),
					"gross": taxes.gross,
					"net": taxes.net,
				}
			)

	rows.sort(key=lambda row: (row["due_date"], row["employee_name"] or ""))

	return {"rows": rows, "pay_before_days": vacation_rules.pay_before_days(), "today": today}


@frappe.whitelist()
def pay(company, employee, last_day, days, posting_date=None):
	"""Оплачує відпустку через «Відомість відпускних» місяця її останнього дня."""
	frappe.has_permission("Vacation Pay Sheet", "write", throw=True)

	period_start = getdate(last_day).replace(day=1)
	name = frappe.db.get_value("Vacation Pay Sheet", {"company": company, "period_start": period_start})

	if name:
		sheet = frappe.get_doc("Vacation Pay Sheet", name)
		sheet.refresh_data()
	else:
		sheet = frappe.get_doc(
			{"doctype": "Vacation Pay Sheet", "company": company, "period_start": period_start}
		).insert()

	sheet.set_pay_days(employee, cint(days))
	entries = sheet.pay(posting_date or nowdate(), [employee])

	return {"sheet": sheet.name, "entries": entries}


def _paid_through_sheets(employees) -> dict:
	if not employees:
		return {}

	result = {}

	for row in frappe.get_all(
		"Vacation Pay Sheet Item",
		filters={"parenttype": "Vacation Pay Sheet", "employee": ("in", employees), "paid": 1},
		fields=["employee", "pay_days"],
	):
		result[row.employee] = result.get(row.employee, 0) + cint(row.pay_days)

	return result


def _runs(days) -> list:
	"""Неоплачені дні, зібрані у відпустки: дні поспіль — одна відпустка."""
	runs = []

	for day in days:
		if runs and date_diff(day, runs[-1][1]) == 1:
			runs[-1][1] = day
		else:
			runs.append([day, day])

	return [tuple(run) for run in runs]


def _average_note(average) -> str:
	if average.from_salary:
		return _("No earnings yet — official salary × 12 ÷ {0} days.").format(average.days)

	return _("{0} – {1}: earnings {2} ÷ {3} days.").format(
		frappe.format(average.period_start, {"fieldtype": "Date"}),
		frappe.format(average.period_end, {"fieldtype": "Date"}),
		frappe.format(average.earnings, {"fieldtype": "Currency"}),
		average.days,
	)
