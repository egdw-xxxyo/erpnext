"""Понаднормова робота — лише готівкою, разом із зарплатою за місяць.

Годинна ставка = повний оклад (офіційна + готівкова частини) ÷ робочі дні місяця ÷ годин
у робочому дні. Понаднормові години звичайного робочого дня — за одинарною ставкою. Робота у
день зі списку вихідних і свят працівника — увесь день (стандартні години + понаднормові) за
подвійною.
"""

import frappe
from frappe.utils import flt, getdate

HOLIDAY_MULTIPLIER = 2

# Статуси, що означають «працював»: лише вони на вихідний дають подвійну оплату дня.
WORKED_STATUSES = ("Present", "Work From Home", "Business Trip")


def hours(employees: list, start, end, holidays_of, day_hours) -> dict:
	"""`{працівник: _dict(regular_hours, holiday_hours, holiday_days)}` за період."""
	if not employees:
		return {}

	result = {}

	for row in frappe.get_all(
		"Attendance",
		filters={
			"docstatus": 1,
			"employee": ("in", employees),
			"attendance_date": ("between", [getdate(start), getdate(end)]),
		},
		fields=["employee", "attendance_date", "status", "overtime_hours"],
	):
		entry = result.setdefault(
			row.employee, frappe._dict(regular_hours=0.0, holiday_hours=0.0, holiday_days=0)
		)

		if row.status in WORKED_STATUSES and getdate(row.attendance_date) in holidays_of(row.employee):
			entry.holiday_days += 1
			entry.holiday_hours += flt(day_hours) + flt(row.overtime_hours)
		else:
			entry.regular_hours += flt(row.overtime_hours)

	return result


def hour_rate(official, cash, month_days, day_hours) -> float:
	if not month_days or not day_hours:
		return 0.0

	return flt((flt(official) + flt(cash)) / month_days / day_hours, 2)


def pay(rate, entry) -> float:
	if not entry:
		return 0.0

	return flt(rate * (flt(entry.regular_hours) + HOLIDAY_MULTIPLIER * flt(entry.holiday_hours)), 2)
