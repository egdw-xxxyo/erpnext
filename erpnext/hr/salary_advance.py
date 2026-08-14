"""Аванс — перший платіж місяця (за домовленістю, по 15 число включно).

Місячний Salary Slip лишається єдиним документом нарахування. Аванс — це виплата всередині
місяця: сума рахується за робочими днями першої половини, а в листку вона повертається
відрахуваннями «Аванс», тож другий платіж = залишок.

Обидві частини зарплати діляться однаково:

	аванс_офіційний = офіційна   × робочі_дні(1..15) / робочі_дні(місяць)
	аванс_готівкою  = готівкова  × робочі_дні(1..15) / робочі_дні(місяць)

Кожна половина — окремий компонент («Аванс на картку» / «Аванс готівкою»), щоб у листку було
видно з назви, звідки платили. Обидва списуються на той самий рахунок, що й «Аванс».

	bench --site frontend execute erpnext.hr.salary_advance.create_advance \
	    --kwargs "{'company': 'КАЛЬХЕОН', 'year': 2026, 'month': 4, 'dry_run': False}"
"""

import frappe
from frappe import _
from frappe.utils import date_diff, flt, get_last_day, getdate

ADVANCE_COMPONENT = "Аванс"
ADVANCE_CARD = "Аванс на картку"
ADVANCE_CASH = "Аванс готівкою"


def create_advance(company, year, month, cutoff_day=15, dry_run=True, require_attendance=True):
	"""Створює відрахування «Аванс» за першу половину місяця.

	`require_attendance` пропускає тих, у кого за першу половину місяця немає жодного дня табеля —
	інакше аванс отримали б і ті, хто в цьому місяці не працював.
	"""
	period_start = getdate(f"{year}-{month:02d}-01")
	period_end = get_last_day(period_start)
	cutoff = min(getdate(f"{year}-{month:02d}-{cutoff_day:02d}"), period_end)

	if not frappe.db.exists("Salary Component", ADVANCE_COMPONENT):
		frappe.throw(_("Salary Component {0} does not exist.").format(ADVANCE_COMPONENT))

	_ensure_components()

	employees = frappe.get_all(
		"Employee",
		filters={"status": "Active", "company": company},
		fields=["name", "employee_name", "holiday_list", "date_of_joining", "relieving_date"],
		order_by="name",
	)

	rows = []

	for employee in employees:
		official, cash = _salary_parts(employee.name, period_end)

		if not (official + cash):
			continue

		if require_attendance and not _has_attendance(employee.name, period_start, cutoff):
			continue

		holidays = _holiday_list(employee, company)
		month_days = _working_days(period_start, period_end, holidays)
		first_half_days = _working_days(
			max(period_start, getdate(employee.date_of_joining or period_start)), cutoff, holidays
		)

		if not month_days or first_half_days <= 0:
			continue

		share = first_half_days / month_days
		rows.append(
			frappe._dict(
				employee=employee.name,
				employee_name=employee.employee_name,
				days=f"{first_half_days}/{month_days}",
				official=flt(official * share, 2),
				cash=flt(cash * share, 2),
			)
		)

	_report(rows, period_start, cutoff, dry_run)

	if dry_run:
		return rows

	for row in rows:
		for amount, component in ((row.official, ADVANCE_CARD), (row.cash, ADVANCE_CASH)):
			if not amount:
				continue

			_make_additional_salary(row.employee, company, period_end, amount, component)

	frappe.db.commit()

	return rows


def _salary_parts(employee, on_date):
	"""Дві частини окладу з картки працівника; якщо їх немає — з чинного призначення структури."""
	official, cash = frappe.db.get_value(
		"Employee", employee, ["custom_official_salary", "custom_cash_salary"]
	) or (0, 0)

	if flt(official) + flt(cash):
		return flt(official), flt(cash)

	assignment = frappe.db.get_value(
		"Salary Structure Assignment",
		{"employee": employee, "docstatus": 1, "from_date": ["<=", on_date]},
		["base", "variable"],
		order_by="from_date desc",
		as_dict=True,
	)

	if not assignment:
		return 0.0, 0.0

	return flt(assignment.variable), flt(assignment.base) - flt(assignment.variable)


def _has_attendance(employee, start, end):
	return frappe.db.count(
		"Attendance",
		{
			"employee": employee,
			"docstatus": 1,
			"attendance_date": ["between", [start, end]],
			"status": ["!=", "Absent"],
		},
	)


def _holiday_list(employee, company):
	return employee.holiday_list or frappe.get_cached_value("Company", company, "default_holiday_list")


def _working_days(start, end, holiday_list):
	"""Робочі дні періоду — календарні мінус вихідні та свята зі списку працівника.

	Той самий підрахунок, що й у листку при `include_holidays_in_total_working_days = 0`.
	"""
	start, end = getdate(start), getdate(end)

	if end < start:
		return 0

	days = date_diff(end, start) + 1

	if not holiday_list:
		return days

	holidays = frappe.db.count("Holiday", {"parent": holiday_list, "holiday_date": ["between", [start, end]]})

	return days - holidays


def _ensure_components():
	"""Створює компоненти авансу, копіюючи рахунки з наявного «Аванс»."""
	source = frappe.get_doc("Salary Component", ADVANCE_COMPONENT)

	for component, in_cash in ((ADVANCE_CARD, 0), (ADVANCE_CASH, 1)):
		if frappe.db.exists("Salary Component", component):
			continue

		doc = frappe.get_doc(
			{
				"doctype": "Salary Component",
				"salary_component": component,
				"salary_component_abbr": "AVCARD" if not in_cash else "AVCASH",
				"type": "Deduction",
				"depends_on_payment_days": 0,
				"amount_based_on_formula": 0,
				"accounts": [{"company": row.company, "account": row.account} for row in source.accounts],
			}
		)
		doc.insert(ignore_permissions=True)


def _make_additional_salary(employee, company, payroll_date, amount, component):
	existing = frappe.db.exists(
		"Additional Salary",
		{
			"employee": employee,
			"salary_component": component,
			"payroll_date": payroll_date,
			"docstatus": ["<", 2],
		},
	)

	if existing:
		return existing

	doc = frappe.get_doc(
		{
			"doctype": "Additional Salary",
			"employee": employee,
			"company": company,
			"salary_component": component,
			"amount": amount,
			"payroll_date": payroll_date,
			"overwrite_salary_structure_amount": 0,
			"custom_pay_in_cash": 1 if component == ADVANCE_CASH else 0,
		}
	)
	doc.insert(ignore_permissions=True)
	doc.submit()

	return doc.name


def _report(rows, period_start, cutoff, dry_run):
	print(
		f"Аванс {period_start:%d.%m.%Y}–{cutoff:%d.%m.%Y}"
		f"{' (пробний прогін)' if dry_run else ''}: {len(rows)} працівників"
	)

	for row in rows:
		print(
			f"  {row.employee:<14} {row.employee_name:<28} дні {row.days:>7}"
			f"  офіційно {row.official:>10,.2f}  готівкою {row.cash:>10,.2f}"
		)

	print(
		f"  Разом: офіційно {sum(r.official for r in rows):,.2f},"
		f" готівкою {sum(r.cash for r in rows):,.2f}"
	)


def unlink_advance(company, year, month, dry_run=True):
	"""Скасовує аванс місяця — потрібно, якщо суми довелось перерахувати."""
	payroll_date = get_last_day(getdate(f"{year}-{month:02d}-01"))
	names = frappe.get_all(
		"Additional Salary",
		filters={
			"company": company,
			"salary_component": ["in", [ADVANCE_CARD, ADVANCE_CASH]],
			"payroll_date": payroll_date,
			"docstatus": 1,
		},
		pluck="name",
	)
	print(f"Скасувати {len(names)} відрахувань авансу за {payroll_date}")

	if dry_run:
		return names

	for name in names:
		frappe.get_doc("Additional Salary", name).cancel()

	frappe.db.commit()

	return names
