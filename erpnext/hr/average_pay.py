"""Відпускні й лікарняні за середньою зарплатою — так, як їх рахує закон.

Раніше день відпустки чи лікарняного платився як звичайний робочий: оклад ÷ робочі дні місяця.
Закон рахує інакше — від середньоденної зарплати за останні 12 місяців і за **календарні** дні:

* відпускні (Порядок № 100): заробіток за розрахунковий період ÷ календарні дні періоду ×
  календарні дні відпустки. Святкові дні з періоду не викидаються (воєнний стан), викидається
  лише час без збереження зарплати;
* лікарняні (Порядок № 1266): середньоденна × відсоток за страховим стажем × календарні дні
  хвороби. Перші `EMPLOYER_SICK_DAYS` днів випадку платить роботодавець, решту — Пенсійний фонд,
  тож у виплату компанії йдуть лише перші, а решта рахується довідково.

Це стосується тільки офіційної частини: закон про готівку нічого не знає, тож готівкова половина
платить ці дні як і раніше (див. `erpnext.hr.salary_advance`).

Заробіток місяця береться з виплаченого «Нарахування зарплати», а за місяці до ERP — з таблиці
«Заробіток до ERP» у картці працівника. Місяць без жодних даних у розрахунок не входить; якщо
даних немає зовсім, середня рахується з чинного офіційного окладу.
"""

import calendar
from itertools import pairwise

import frappe
from frappe.utils import add_days, add_months, flt, getdate

from erpnext.hr import payroll_tax

# Скільки календарних днів кожного випадку хвороби оплачує роботодавець.
EMPLOYER_SICK_DAYS = 5

# Середня кількість календарних днів місяця — нею ділять оклад, коли заробітку в періоді немає.
AVERAGE_MONTH_DAYS = 30.44

# Максимальна база нарахування ЄСВ — стільки мінімальних зарплат; вища зарплата лікарняні не збільшує.
MAX_BASE_MINIMUM_WAGES = 20

# Страховий стаж, менший за який лікарняні обмежуються мінімальною зарплатою.
SHORT_TENURE_MONTHS = 6

# Відсоток лікарняних за повними роками страхового стажу: від найбільшого порога до нуля.
TENURE_PERCENT = ((8, 100), (5, 70), (3, 60), (0, 50))

# Типи відпусток, які насправді є лікарняним, оформленим заявкою.
SICK_LEAVE_TYPES = ("Sick Leave", "Лікарняний (оплачуваний)")

# На скільки днів назад дивитися за початком випадку, що тягнеться з минулого місяця.
LOOKBACK_DAYS = 62

OPENING_TABLE = "custom_opening_earnings"

VACATION = "vacation"
SICK = "sick"


def absence_calendar(employees: list, start, end, holidays_of) -> dict:
	"""Календарні дні відпустки й лікарняного: `{працівник: {VACATION: {...}, SICK: {...}}}`.

	Значення — `{дата: (початок випадку, номер дня у випадку)}`. Табель ставиться лише на робочі
	дні, а закон платить календарні, тож вихідні всередині випадку добираються: за заявкою —
	усі її дати, без заявки — вихідні між двома сусідніми відмітками. `holidays_of(працівник)`
	віддає множину неробочих дат працівника.
	"""
	if not employees:
		return {}

	start, end = getdate(start), getdate(end)
	since = add_days(start, -LOOKBACK_DAYS)
	rows = frappe.get_all(
		"Attendance",
		filters={
			"docstatus": 1,
			"employee": ("in", employees),
			"attendance_date": ("between", [since, end]),
			"status": ("in", ["Sick Leave", "On Leave"]),
		},
		fields=["employee", "attendance_date", "status", "leave_application"],
	)
	applications = _applications({row.leave_application for row in rows if row.leave_application})
	marked = {}

	for row in rows:
		application = applications.get(row.leave_application)

		# Відпустка без збереження не оплачується взагалі — ні за середньою, ні за окладом.
		if application and application.is_lwp:
			continue

		sick = row.status == "Sick Leave" or (application and application.leave_type in SICK_LEAVE_TYPES)
		days = marked.setdefault(row.employee, {VACATION: set(), SICK: set()})[SICK if sick else VACATION]
		days.add(getdate(row.attendance_date))

		if application:
			day = max(getdate(application.from_date), since)

			while day <= min(getdate(application.to_date), end):
				days.add(day)
				day = add_days(day, 1)

	result = {}

	for employee, kinds in marked.items():
		holidays = holidays_of(employee)
		result[employee] = {
			kind: {day: case for day, case in _cases(_bridged(days, holidays)).items() if start <= day <= end}
			for kind, days in kinds.items()
		}

	return result


def _applications(names: set) -> dict:
	if not names:
		return {}

	rows = frappe.get_all(
		"Leave Application",
		filters={"name": ("in", list(names))},
		fields=["name", "leave_type", "from_date", "to_date"],
	)
	lwp = {
		leave_type: frappe.get_cached_value("Leave Type", leave_type, "is_lwp")
		for leave_type in {row.leave_type for row in rows}
	}

	for row in rows:
		row.is_lwp = lwp.get(row.leave_type)

	return {row.name: row for row in rows}


def _bridged(days: set, holidays: set) -> list:
	"""Додає вихідні, що лежать між двома сусідніми днями випадку."""
	ordered = sorted(days)
	result = set(ordered)

	for previous, following in pairwise(ordered):
		gap = [add_days(previous, offset) for offset in range(1, (following - previous).days)]

		if gap and all(day in holidays for day in gap):
			result.update(gap)

	return sorted(result)


def _cases(ordered: list) -> dict:
	"""Розбиває дати на випадки — безперервні відрізки — і нумерує дні в кожному."""
	result = {}
	first = None
	previous = None

	for day in ordered:
		if previous is None or (day - previous).days > 1:
			first = day

		result[day] = (first, (day - first).days + 1)
		previous = day

	return result


def leave_pay(employee, first, last, holidays: set, absences: dict | None) -> frappe._dict:
	"""Відпускні й лікарняні працівника за відрізок `first..last`.

	`working_days` — скільки робочих днів відрізка зайняли відпустка й лікарняний: за них оклад
	не платиться, їх уже оплачено за середньою.
	"""
	result = frappe._dict(
		vacation_days=0,
		vacation_pay=0.0,
		vacation_average=0.0,
		sick_calendar_days=0,
		sick_pay=0.0,
		sick_pay_fund=0.0,
		sick_average=0.0,
		sick_percent=0.0,
		working_days=0,
	)

	if not absences:
		return result

	first, last = getdate(first), getdate(last)
	averages = {}

	def average(kind, case_start):
		key = (kind, case_start.replace(day=1))

		if key not in averages:
			averages[key] = (vacation_average if kind == VACATION else sick_average)(employee, case_start)

		return averages[key]

	for day, (case_start, _number) in sorted((absences.get(VACATION) or {}).items()):
		if not first <= day <= last:
			continue

		# Середня фіксується місяцем початку відпустки, навіть якщо вона перейшла в наступний.
		result.vacation_average = average(VACATION, case_start)
		result.vacation_days += 1
		result.vacation_pay += result.vacation_average
		result.working_days += day not in holidays

	for day, (case_start, number) in sorted((absences.get(SICK) or {}).items()):
		if not first <= day <= last:
			continue

		result.sick_average = average(SICK, case_start)
		result.sick_percent = sick_percent(employee, case_start)
		amount = result.sick_average * result.sick_percent / 100
		result.sick_calendar_days += 1
		result["sick_pay" if number <= EMPLOYER_SICK_DAYS else "sick_pay_fund"] += amount
		result.working_days += day not in holidays

	for field in ("vacation_pay", "vacation_average", "sick_pay", "sick_pay_fund", "sick_average"):
		result[field] = flt(result[field], 2)

	return result


def calculation_months(employee, on_date) -> list:
	"""Розрахунковий період: 12 календарних місяців перед місяцем події, але не раніше першого
	повного місяця роботи."""
	month = getdate(on_date).replace(day=1)
	joining = getdate(employee.get("date_of_joining") or "1900-01-01")
	first_full = joining if joining.day == 1 else getdate(add_months(joining.replace(day=1), 1))

	return [
		candidate
		for candidate in (getdate(add_months(month, -offset)) for offset in range(12, 0, -1))
		if candidate >= first_full
	]


def monthly_earnings(employee, months: list) -> dict:
	"""Офіційний заробіток по місяцях: `{місяць: {earnings, sick_pay, sick_days, unpaid_days}}`.

	Виплачене «Нарахування зарплати» важить більше за ручний рядок із картки: ручні дані —
	лише для місяців, яких в ERP немає.
	"""
	if not months:
		return {}

	result = {}
	opening = frappe.get_all(
		"Employee Opening Earning",
		filters={
			"parent": employee.name,
			"parenttype": "Employee",
			"month": ("between", [months[0], months[-1]]),
		},
		fields=["month", "earnings", "sick_pay", "sick_days", "unpaid_days"],
	)

	for row in opening:
		result[getdate(row.month).replace(day=1)] = frappe._dict(
			earnings=flt(row.earnings),
			sick_pay=flt(row.sick_pay),
			sick_days=flt(row.sick_days),
			unpaid_days=flt(row.unpaid_days),
		)

	sheets = {
		row.name: getdate(row.period_start)
		for row in frappe.get_all(
			"Payroll Sheet",
			filters={"period_start": ("between", [months[0], months[-1]]), "docstatus": ("<", 2)},
			fields=["name", "period_start"],
		)
	}

	if sheets:
		paid = frappe.get_all(
			"Payroll Sheet Item",
			filters={
				"parent": ("in", list(sheets)),
				"parenttype": "Payroll Sheet",
				"employee": employee.name,
				"paid": 1,
			},
			fields=["parent", "earned_official", "sick_pay", "sick_calendar_days", "unpaid_leave_days"],
		)

		for row in paid:
			result[sheets[row.parent]] = frappe._dict(
				earnings=flt(row.earned_official),
				sick_pay=flt(row.sick_pay),
				sick_days=flt(row.sick_calendar_days),
				unpaid_days=flt(row.unpaid_leave_days),
			)

	return result


def _month_days(month) -> int:
	return calendar.monthrange(month.year, month.month)[1]


def _official_salary(employee, on_date) -> float:
	"""Чинний офіційний оклад, але не нижче мінімальної зарплати — як вимагає закон для
	розрахунку «з окладу»."""
	from erpnext.hr.salary_split import salary_parts_on

	official, _cash = salary_parts_on(employee.name, on_date)

	return max(flt(official), payroll_tax.minimum_wage()) if flt(official) else 0.0


def vacation_average(employee, on_date) -> float:
	"""Середньоденна для відпускних: заробіток періоду ÷ календарні дні періоду без днів
	без збереження зарплати. Лікарняні й попередні відпускні в заробіток входять."""
	earnings = monthly_earnings(employee, calculation_months(employee, on_date))
	total = sum(row.earnings for row in earnings.values())
	days = sum(_month_days(month) - row.unpaid_days for month, row in earnings.items())

	if total > 0 and days > 0:
		return flt(total / days, 2)

	# Заробітку в періоді немає: оклад × 12 ÷ календарні дні року.
	return flt(_official_salary(employee, on_date) * 12 / 365, 2)


def sick_average(employee, on_date) -> float:
	"""Середньоденна для лікарняних: без попередніх лікарняних і їхніх днів, з обмеженням
	максимальною базою ЄСВ, а за короткого стажу — мінімальною зарплатою."""
	earnings = monthly_earnings(employee, calculation_months(employee, on_date))
	total = sum(row.earnings - row.sick_pay for row in earnings.values())
	days = sum(_month_days(month) - row.unpaid_days - row.sick_days for month, row in earnings.items())

	if total > 0 and days > 0:
		average = total / days
	else:
		average = _official_salary(employee, on_date) / AVERAGE_MONTH_DAYS

	limit = payroll_tax.minimum_wage() * MAX_BASE_MINIMUM_WAGES / AVERAGE_MONTH_DAYS

	if tenure_months(employee, on_date) < SHORT_TENURE_MONTHS:
		limit = payroll_tax.minimum_wage() / AVERAGE_MONTH_DAYS

	return flt(min(average, limit), 2)


def tenure_months(employee, on_date) -> int:
	"""Страховий стаж у повних місяцях: набутий до нас (з картки) плюс відпрацьований тут."""
	before = int(
		flt(employee.get("custom_insurance_years")) * 12 + flt(employee.get("custom_insurance_months"))
	)
	joining = employee.get("date_of_joining")

	if not joining:
		return before

	joining, on_date = getdate(joining), getdate(on_date)
	here = (on_date.year - joining.year) * 12 + on_date.month - joining.month - (on_date.day < joining.day)

	return before + max(here, 0)


def sick_percent(employee, on_date) -> float:
	"""Відсоток лікарняних за страховим стажем; пільговим категоріям — завжди 100."""
	if employee.get("custom_sick_pay_in_full"):
		return 100.0

	years = tenure_months(employee, on_date) / 12

	return float(next(percent for threshold, percent in TENURE_PERCENT if years >= threshold))


def validate_opening_earnings(doc, method=None):
	"""Employee.validate: рядок «Заробітку до ERP» — один на місяць, дата — перше число."""
	seen = set()

	for row in doc.get(OPENING_TABLE) or []:
		if not row.month:
			continue

		row.month = getdate(row.month).replace(day=1)

		if row.month in seen:
			frappe.throw(
				frappe._("Earnings Before ERP: the month {0} is entered twice.").format(
					frappe.format(row.month, {"fieldtype": "Date"})
				)
			)

		seen.add(row.month)

		if flt(row.sick_pay) > flt(row.earnings):
			frappe.throw(
				frappe._("Earnings Before ERP: the sick pay cannot exceed the earnings of the month.")
			)
