"""Помісячний страховий стаж: один рядок — один місяць, станом на дату стаж — сума місяців до неї."""

import frappe
from frappe.utils import cint, getdate

from erpnext.hr import average_pay


def validate_insurance_months(doc, method=None):
	"""Employee.validate: місяць один раз, дата — перше число, днів не більше, ніж у місяці."""
	seen = set()

	for row in doc.get("custom_insurance_months_table") or []:
		if not row.period_start:
			continue

		row.period_start = getdate(row.period_start).replace(day=1)

		if row.period_start in seen:
			frappe.throw(
				frappe._("Insurance Tenure by Month: the month {0} is entered twice.").format(
					row.period_start.strftime("%m.%Y")
				)
			)

		seen.add(row.period_start)
		longest = frappe.utils.get_last_day(row.period_start).day

		if not 0 <= cint(row.days) <= longest:
			frappe.throw(
				frappe._("Insurance Tenure by Month: {0} has {1} days at most.").format(
					row.period_start.strftime("%m.%Y"), longest
				)
			)


@frappe.whitelist()
def tenure_on(employee, on_date=None):
	"""Стаж працівника станом на дату: до нас (за місяцями) і разом із відпрацьованим тут."""
	frappe.has_permission("Employee", "read", doc=employee, throw=True)
	on_date = getdate(on_date)
	card = frappe.db.get_value(
		"Employee",
		employee,
		["name", "date_of_joining", "custom_insurance_years", "custom_insurance_months"],
		as_dict=True,
	)
	total = average_pay.tenure_months(card, on_date)
	before = average_pay.before_join_months(card, on_date)

	return {
		"on_date": str(on_date),
		"before_months": before,
		"total_months": total,
		"years": total // 12,
		"months": total % 12,
	}
