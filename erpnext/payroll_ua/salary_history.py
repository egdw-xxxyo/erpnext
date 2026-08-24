"""Історія окладів: який оклад у якому місяці був і буде.

Джерело — подані призначення структури ЗП (`base` = повний оклад, `variable` = офіційна
частина): саме їх читає HRMS, коли рахує листок, тож історія показує рівно те, за чим платили.
Створює їх хук `erpnext.hr.salary_split` із картки працівника, а міняє — документ
«Зміна окладу».
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, get_first_day, getdate, nowdate

PAST, CURRENT, FUTURE = "Past", "Current", "Future"


@frappe.whitelist()
def get_salary_history(employee: str) -> list[dict]:
	"""Оклади одного працівника від найранішого до майбутніх."""
	frappe.has_permission("Employee", doc=employee, throw=True)

	return build_history(
		frappe.get_all(
			"Salary Structure Assignment",
			filters={"employee": employee, "docstatus": 1},
			fields=["name", "employee", "from_date", "base", "variable"],
			order_by="from_date asc",
		)
	)


def build_history(assignments: list) -> list[dict]:
	"""Ряд призначень одного працівника → періоди з датою «по» і зміною до попереднього."""
	month = get_first_day(nowdate())
	rows = []

	for index, assignment in enumerate(assignments):
		start = getdate(assignment.from_date)
		following = assignments[index + 1] if index + 1 < len(assignments) else None
		end = add_days(getdate(following.from_date), -1) if following else None

		official = flt(assignment.variable)
		total = flt(assignment.base)
		previous = flt(assignments[index - 1].base) if index else 0

		rows.append(
			{
				"assignment": assignment.name,
				"employee": assignment.employee,
				"from_date": start,
				"to_date": end,
				"official": official,
				"cash": total - official,
				"total": total,
				"change": flt(total - previous, 2) if index else 0,
				"period": period_of(start, end, getdate(month)),
			}
		)

	return rows


def period_of(start, end, month) -> str:
	if start > month:
		return FUTURE

	if end and end < month:
		return PAST

	return CURRENT


def period_label(period: str) -> str:
	return {PAST: _("Past"), CURRENT: _("Current"), FUTURE: _("Future")}.get(period, period)
