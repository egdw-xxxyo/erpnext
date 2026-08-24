"""Аванс — перший платіж місяця, по день відсікання включно (за домовленістю — 15-те).

Місячний Salary Slip лишається єдиним документом нарахування. Аванс — це виплата всередині
місяця: сума рахується за **фактично відпрацьованими** днями першої половини, а в листку вона
повертається відрахуваннями «Аванс», тож другий платіж = залишок.

Обидві частини зарплати діляться однаково:

	денна_ставка   = частина_окладу / робочі_дні(місяць)
	аванс_частини  = денна_ставка × зараховані_дні(1..відсікання)

Зараховані дні беруться з табеля, а не з календаря: прогул чи неоплачувана відпустка першої
половини зменшують аванс. Кожна половина — окремий компонент («Аванс на картку» /
«Аванс готівкою»), щоб у листку було видно з назви, звідки платили.

	bench --site frontend execute erpnext.hr.salary_advance.create_advance \
	    --kwargs "{'company': 'КАЛЬХЕОН', 'year': 2026, 'month': 4, 'dry_run': False}"
"""

import frappe
from frappe import _
from frappe.utils import date_diff, flt, get_last_day, getdate

from erpnext.hr.salary_split import salary_parts_on

ADVANCE_COMPONENT = "Аванс"
ADVANCE_CARD = "Аванс на картку"
ADVANCE_CASH = "Аванс готівкою"

DEFAULT_CUTOFF_DAY = 15

# Скільки дня зараховується авансу — так само, як його оплачує листок.
DAY_WEIGHT = {
	"Present": 1.0,
	"Work From Home": 1.0,
	"On Leave": 1.0,
	"Half Day": 0.5,
	"Absent": 0.0,
}

# Скільки годин має повний робочий день, коли зміна не задана.
DEFAULT_DAY_HOURS = 8.0

EMPTY_STATS = {
	"credited_days": 0.0,
	"present_days": 0.0,
	"leave_days": 0.0,
	"unpaid_leave_days": 0.0,
	"sick_days": 0.0,
	"absent_days": 0.0,
	"half_days": 0.0,
	"overtime_hours": 0.0,
	"shortfall_hours": 0.0,
}


def plan_advance(company, year, month, cutoff_day=DEFAULT_CUTOFF_DAY) -> list:
	"""Рахує аванс по кожному працівнику компанії, нічого не записуючи."""
	period_start, period_end, cutoff = period(year, month, cutoff_day)

	employees = frappe.get_all(
		"Employee",
		filters={"status": "Active", "company": company},
		fields=[
			"name",
			"employee_name",
			"department",
			"reports_to",
			"holiday_list",
			"date_of_joining",
			"relieving_date",
		],
		order_by="department asc, employee_name asc",
	)

	stats = attendance_stats([employee.name for employee in employees], period_start, cutoff)
	day_hours = standard_day_hours()
	rows = []

	for employee in employees:
		official, cash = salary_parts_on(employee.name, period_end)

		if not (official + cash):
			continue

		holidays = _holiday_list(employee, company)

		if not holidays:
			frappe.throw(
				_("Set the holiday list for {0} — without it every day counts as a working day.").format(
					employee.employee_name or employee.name
				),
				title=_("No Holiday List"),
			)

		first, last = _employee_period(employee, period_start, cutoff)
		month_days = _working_days(period_start, period_end, holidays)
		planned_days = _working_days(first, last, holidays)
		attendance = stats.get(employee.name) or frappe._dict(EMPTY_STATS)
		credited_days = flt(attendance.credited_days, 2)

		if not month_days or credited_days <= 0:
			continue

		rate_official = flt(official) / month_days
		rate_cash = flt(cash) / month_days

		rows.append(
			frappe._dict(
				employee=employee.name,
				employee_name=employee.employee_name,
				department=employee.department,
				manager=employee.reports_to,
				official_salary=flt(official),
				cash_salary=flt(cash),
				month_working_days=month_days,
				planned_days=planned_days,
				planned_hours=flt(planned_days * day_hours, 2),
				credited_days=credited_days,
				present_days=flt(attendance.present_days, 2),
				leave_days=flt(attendance.leave_days, 2),
				unpaid_leave_days=flt(attendance.unpaid_leave_days, 2),
				sick_days=flt(attendance.sick_days, 2),
				absent_days=flt(attendance.absent_days, 2),
				half_days=flt(attendance.half_days, 2),
				overtime_hours=flt(attendance.overtime_hours, 2),
				shortfall_hours=flt(attendance.shortfall_hours, 2),
				working_hours=flt(
					credited_days * day_hours
					+ flt(attendance.overtime_hours)
					- flt(attendance.shortfall_hours),
					2,
				),
				daily_rate=flt(rate_official + rate_cash, 2),
				official=flt(rate_official * credited_days, 2),
				cash=flt(rate_cash * credited_days, 2),
			)
		)

	for row in rows:
		# сумісність зі старим друком і викликами з відомості
		row.days = f"{row.credited_days:g}/{row.month_working_days:g}"
		row.advance_total = flt(row.official + row.cash, 2)

	return rows


def apply_advance(company, year, month, rows) -> list:
	"""Створює відрахування «Аванс» на кінець місяця по вже порахованих рядках."""
	_ensure_components()
	payroll_date = get_last_day(getdate(f"{int(year)}-{int(month):02d}-01"))
	created = []

	for row in rows:
		for amount, component in (
			(flt(row.get("official")), ADVANCE_CARD),
			(flt(row.get("cash")), ADVANCE_CASH),
		):
			if not flt(amount, 2):
				continue

			created.append(_make_additional_salary(row["employee"], company, payroll_date, amount, component))

	return created


def create_advance(
	company, year, month, cutoff_day=DEFAULT_CUTOFF_DAY, dry_run=True, require_attendance=True
):
	"""Рахує і (якщо не пробний прогін) створює аванс за першу половину місяця."""
	if not frappe.db.exists("Salary Component", ADVANCE_COMPONENT):
		frappe.throw(_("Salary Component {0} does not exist.").format(ADVANCE_COMPONENT))

	period_start, _period_end, cutoff = period(year, month, cutoff_day)
	rows = plan_advance(company, year, month, cutoff_day)
	_report(rows, period_start, cutoff, dry_run)

	if dry_run:
		return rows

	apply_advance(company, year, month, rows)
	frappe.db.commit()

	return rows


def period_norm(company, year, month, cutoff_day=DEFAULT_CUTOFF_DAY) -> tuple:
	"""Норма першої половини місяця за календарем компанії: робочі дні й години.

	Довідкове число для шапки документа — на відміну від рядків, воно нічиє і рахується
	за списком вихідних компанії, а не працівника.
	"""
	period_start, _period_end, cutoff = period(year, month, cutoff_day)
	holidays = frappe.get_cached_value("Company", company, "default_holiday_list")
	days = _working_days(period_start, cutoff, holidays)

	return days, flt(days * standard_day_hours(), 2)


def period(year, month, cutoff_day=DEFAULT_CUTOFF_DAY) -> tuple:
	period_start = getdate(f"{int(year)}-{int(month):02d}-01")
	period_end = get_last_day(period_start)
	cutoff = min(getdate(f"{int(year)}-{int(month):02d}-{int(cutoff_day):02d}"), period_end)

	return period_start, period_end, cutoff


def _employee_period(employee, period_start, cutoff) -> tuple:
	"""Межі першої половини для конкретного працівника — з урахуванням прийому і звільнення."""
	first = max(period_start, getdate(employee.date_of_joining or period_start))
	last = cutoff

	if employee.relieving_date:
		last = min(cutoff, getdate(employee.relieving_date))

	return first, last


def standard_day_hours() -> float:
	"""Годин у повному робочому дні — з налаштувань HR, інакше вісім."""
	return flt(frappe.db.get_single_value("HR Settings", "standard_working_hours")) or DEFAULT_DAY_HOURS


ATTENDANCE_FIELDS = (
	"present_days",
	"leave_days",
	"unpaid_leave_days",
	"sick_days",
	"absent_days",
	"half_days",
	"overtime_hours",
	"shortfall_hours",
)


def attendance_summary(employees: list, start, end) -> dict:
	"""Готові значення полів табеля по кожному працівнику — те, що показують усі три
	зарплатні документи однаково: розклад днів, зараховані дні й години."""
	stats = attendance_stats(employees, start, end)
	day_hours = standard_day_hours()
	summary = {}

	for employee in employees:
		entry = stats.get(employee) or frappe._dict(EMPTY_STATS)
		values = {field: flt(entry.get(field), 2) for field in ATTENDANCE_FIELDS}
		values["credited_days"] = flt(entry.get("credited_days"), 2)
		values["working_hours"] = flt(
			values["credited_days"] * day_hours + values["overtime_hours"] - values["shortfall_hours"], 2
		)
		summary[employee] = values

	return summary


def attendance_stats(employees: list, start, end) -> dict:
	"""Розклад табеля по кожному працівнику за період: дні по статусах і години.

	`credited_days` — те, за що платиться аванс. Неоплачувана відпустка не зараховується:
	у табелі це «On Leave» із заявкою на тип з ознакою `is_lwp`. Решта чисел нічого не
	рахує, вони лише пояснюють суму керівникові.
	"""
	if not employees:
		return {}

	rows = frappe.get_all(
		"Attendance",
		filters={
			"docstatus": 1,
			"employee": ("in", employees),
			"attendance_date": ("between", [start, end]),
		},
		fields=[
			"employee",
			"status",
			"half_day_status",
			"leave_application",
			"overtime_hours",
			"shortfall_hours",
		],
	)

	unpaid = _unpaid_leaves({row.leave_application for row in rows if row.leave_application})
	stats = {}

	for row in rows:
		entry = stats.setdefault(row.employee, frappe._dict(EMPTY_STATS.copy()))
		lwp = row.leave_application in unpaid

		if row.status in ("Present", "Work From Home"):
			entry.present_days += 1
		elif row.status == "Half Day":
			entry.half_days += 1
			entry.present_days += 0.5
			entry.absent_days += 0 if row.half_day_status == "Present" else 0.5
		elif row.status == "Sick Leave":
			entry.sick_days += 1
		elif row.status == "Absent":
			entry.absent_days += 1
		elif row.status == "On Leave":
			entry["unpaid_leave_days" if lwp else "leave_days"] += 1

		entry.overtime_hours += flt(row.overtime_hours)
		entry.shortfall_hours += flt(row.shortfall_hours)

		if not lwp:
			entry.credited_days += DAY_WEIGHT.get(row.status, 0.0)

	return stats


def _unpaid_leaves(applications: set) -> set:
	if not applications:
		return set()

	rows = frappe.get_all(
		"Leave Application",
		filters={"name": ("in", list(applications))},
		fields=["name", "leave_type"],
	)
	lwp = {
		leave_type
		for leave_type in {row.leave_type for row in rows}
		if frappe.db.get_value("Leave Type", leave_type, "is_lwp")
	}

	return {row.name for row in rows if row.leave_type in lwp}


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
			f"  {row.employee:<14} {row.employee_name:<28} дні {row.days:>9}"
			f"  офіційно {row.official:>10,.2f}  готівкою {row.cash:>10,.2f}"
		)

	print(
		f"  Разом: офіційно {sum(r.official for r in rows):,.2f},"
		f" готівкою {sum(r.cash for r in rows):,.2f}"
	)


def unlink_advance(company, year, month, dry_run=True):
	"""Скасовує аванс місяця — потрібно, якщо суми довелось перерахувати."""
	payroll_date = get_last_day(getdate(f"{int(year)}-{int(month):02d}-01"))
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
