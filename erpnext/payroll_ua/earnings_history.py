"""Заробіток працівника по місяцях — усе, що йому нараховано й виплачено, в одному місці.

Нічого нового не зберігається: місяць складається з уже записаних документів — виплачених
рядків «Зарплатної відомості» (офіційна частина) і «Управлінської відомості» (готівка),
«Відомості відпускних», «Випадків лікарняного» (частина фонду) — а місяці до ERP беруться з
таблиці «Заробіток до ERP» картки. Колонка «для середньої» — рівно те, з чого рахуються
відпускні й лікарняні (`average_pay.monthly_earnings`).
"""

import frappe
from frappe.utils import add_days, add_months, flt, getdate, nowdate

from erpnext.hr import average_pay


def _month(value):
	return getdate(value).replace(day=1)


@frappe.whitelist()
def get_earnings(employee: str) -> list[dict]:
	frappe.has_permission("Employee", doc=employee, throw=True)
	frappe.has_permission("Payroll Sheet", "read", throw=True)

	doc = frappe.get_doc("Employee", employee)
	first = _month(doc.date_of_joining or nowdate())
	last = _month(min(getdate(doc.relieving_date or nowdate()), getdate(nowdate())))
	months = []
	month = first

	while month <= last:
		months.append(month)
		month = getdate(add_months(month, 1))

	rows = {
		month: frappe._dict(
			month=month,
			source="",
			official=0.0,
			official_paid=0.0,
			cash=0.0,
			cash_paid=0.0,
			vacation_days=0,
			vacation_pay=0.0,
			sick_days=0,
			sick_employer=0.0,
			sick_fund=0.0,
			unpaid_days=0.0,
		)
		for month in months
	}

	_opening(employee, rows)
	_payroll_sheets(employee, rows)
	_vacation(employee, rows)
	_sick_fund(employee, rows)

	averages = average_pay.monthly_earnings(frappe._dict(name=employee), months)

	for month, row in rows.items():
		entry = averages.get(month)
		row.for_average = flt(entry.earnings, 2) if entry else 0.0

	return [rows[month] for month in reversed(months)]


def _opening(employee, rows):
	for row in frappe.get_all(
		"Employee Opening Earning",
		filters={"parent": employee, "parenttype": "Employee"},
		fields=["month", "earnings", "sick_pay", "sick_days", "unpaid_days"],
	):
		entry = rows.get(_month(row.month))

		if entry:
			entry.source = "Before ERP"
			entry.official = flt(row.earnings)
			entry.official_paid = flt(row.earnings)
			entry.sick_employer = flt(row.sick_pay)
			entry.sick_days = flt(row.sick_days)
			entry.unpaid_days = flt(row.unpaid_days)


def _payroll_sheets(employee, rows):
	sheets = {}

	for doctype in ("Payroll Sheet", "Management Payroll Sheet"):
		for row in frappe.get_all(doctype, filters={"docstatus": ("<", 2)}, fields=["name", "period_start"]):
			sheets[(doctype, row.name)] = _month(row.period_start)

	items = frappe.get_all(
		"Payroll Sheet Item",
		filters={
			"employee": employee,
			"parenttype": ("in", ["Payroll Sheet", "Management Payroll Sheet"]),
		},
		fields=[
			"parent",
			"parenttype",
			"paid",
			"earned_official",
			"salary_card",
			"advance_card",
			"earned_cash",
			"salary_cash",
			"advance_cash",
			"sick_calendar_days",
			"sick_pay",
			"unpaid_leave_days",
		],
	)

	for item in items:
		entry = rows.get(sheets.get((item.parenttype, item.parent)))

		if not entry:
			continue

		entry.source = "ERP"

		if item.parenttype == "Payroll Sheet":
			entry.official = flt(item.earned_official)
			entry.official_paid = flt(
				flt(item.advance_card) + flt(item.salary_card) if item.paid else item.advance_card
			)
			entry.sick_days = flt(item.sick_calendar_days)
			entry.sick_employer = flt(item.sick_pay)
			entry.unpaid_days = flt(item.unpaid_leave_days)
		else:
			entry.cash = flt(item.earned_cash)
			entry.cash_paid = flt(
				flt(item.advance_cash) + flt(item.salary_cash) if item.paid else item.advance_cash
			)


def _vacation(employee, rows):
	sheets = {
		row.name: _month(row.period_start)
		for row in frappe.get_all("Vacation Pay Sheet", fields=["name", "period_start"])
	}

	for item in frappe.get_all(
		"Vacation Pay Sheet Item",
		filters={"employee": employee, "parenttype": "Vacation Pay Sheet", "paid": 1},
		fields=["parent", "pay_days", "gross"],
	):
		entry = rows.get(sheets.get(item.parent))

		if entry:
			entry.vacation_days += int(item.pay_days or 0)
			entry.vacation_pay = flt(entry.vacation_pay + flt(item.gross), 2)


def _sick_fund(employee, rows):
	for case in frappe.get_all(
		"Sick Leave Case",
		filters={"employee": employee, "fund_paid_date": ("is", "set")},
		fields=["start_date", "employer_days", "fund_days", "fund_gross"],
	):
		days = int(case.fund_days or 0)

		if not days:
			continue

		per_day = flt(case.fund_gross) / days
		day = add_days(getdate(case.start_date), int(case.employer_days or 0))

		for _i in range(days):
			entry = rows.get(_month(day))

			if entry:
				entry.sick_fund = flt(entry.sick_fund + per_day, 2)

			day = add_days(day, 1)
