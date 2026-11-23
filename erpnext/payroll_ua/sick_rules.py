"""Правила оплати лікарняних (Закон №1105-XIV, Порядок №1266).

Лікарняний оплачується випадком, а не місяцем: середня й відсоток фіксуються на день початку
хвороби, перші дні випадку платить роботодавець (разом із зарплатою місяця, коли закрито
ЕЛН), решту — фонд, і гроші від фонду приходять на рахунок компанії коли завгодно.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from erpnext.hr import average_pay, payroll_tax

# Тип випадку → (днів за рахунок роботодавця, відсоток незалежно від стажу).
# TODO(бухгалтер): перевірити вагітність і пологи, догляд за дитиною та виробничу травму.
CASE_TYPES = {
	"Illness or Injury": (average_pay.EMPLOYER_SICK_DAYS, None),
	"Work Injury or Occupational Disease": (average_pay.EMPLOYER_SICK_DAYS, 100.0),
	"Maternity": (0, 100.0),
	"Child Care": (0, None),
	"Family Member Care": (0, None),
}
DEFAULT_CASE_TYPE = "Illness or Injury"

# Скільки календарних днів зазвичай триває випадок, після чого потрібне окреме рішення.
# Це попередження в картці випадку, а не обмеження розрахунку: строк ЕЛН визначає лікар
# (або ЕКОПФО), і бухгалтерія платить за тим ЕЛН, який є. Перевіряйте з чинним Порядком.
ILLNESS_CASE_TYPES = ("Illness or Injury", "Work Injury or Occupational Disease")
ILLNESS_DAYS = 120  # поспіль — далі ЕЛН продовжує ЕКОПФО (до 10 міс., туберкульоз — 12)
ILLNESS_YEAR_DAYS = 150  # за календарний рік із повторними випадками — теж ЕКОПФО
CHILD_CARE_DAYS = 14  # догляд за хворою дитиною до 14 років
FAMILY_CARE_DAYS = 3  # догляд за хворим членом сім'ї
FAMILY_CARE_MAX_DAYS = 7  # у виняткових випадках
MATERNITY_DAYS = 126  # 70 + 56
MATERNITY_MAX_DAYS = 140  # ускладнені пологи або двоє й більше дітей (180 — чорнобильські категорії)

# Скільки відсотків готівкової ставки платимо за день лікарняного — поки налаштування немає.
DEFAULT_CASH_PERCENT = 50.0

EMPLOYEE_FIELDS = (
	"name",
	"employee_name",
	"department",
	"company",
	"date_of_joining",
	"custom_insurance_years",
	"custom_insurance_months",
	"custom_sick_pay_in_full",
)


def case_rule(case_type) -> tuple:
	return CASE_TYPES.get(case_type or DEFAULT_CASE_TYPE) or CASE_TYPES[DEFAULT_CASE_TYPE]


def insurance_record(employee, on_date) -> frappe._dict:
	"""Страховий стаж на дату: набутий до нас (з картки) і відпрацьований тут."""
	total = average_pay.tenure_months(employee, on_date)
	before = int(
		flt(employee.get("custom_insurance_years")) * 12 + flt(employee.get("custom_insurance_months"))
	)

	return frappe._dict(
		total_months=total,
		years=total // 12,
		months=total % 12,
		before_join_months=before,
		here_months=max(total - before, 0),
	)


def percent(employee, case_type, on_date) -> tuple:
	"""Відсоток оплати і чому саме він: тип випадку, пільга з картки або стаж."""
	override = case_rule(case_type)[1]

	if override:
		return override, _("{0}: always {1}%").format(_(case_type), int(override))

	if employee.get("custom_sick_pay_in_full"):
		return 100.0, _("Employee card: sick pay in full")

	years = average_pay.tenure_months(employee, on_date) // 12
	value = average_pay.sick_percent(employee, on_date)
	threshold = next(limit for limit, rate in average_pay.TENURE_PERCENT if rate == value)

	if threshold:
		return value, _("Insurance record {0} full years (from {1} years — {2}%)").format(
			years, threshold, int(value)
		)

	return value, _("Insurance record {0} full years (under 3 years — {1}%)").format(years, int(value))


def split(days_total, employer_days) -> tuple:
	"""Дні роботодавця й фонду в одному випадку: роботодавець — перші, фонд — решта."""
	days_total = max(int(days_total or 0), 0)
	employer = min(days_total, max(int(employer_days or 0), 0))

	return employer, days_total - employer


def cash_percent() -> float:
	value = payroll_tax._setting("sick_cash_percent")

	return DEFAULT_CASH_PERCENT if value is None or value == "" else flt(value)


def cash_unpaid_weight() -> float:
	"""Яку частку дня лікарняного готівкова половина не платить: 1 − відсоток/100."""
	return flt(1 - min(max(cash_percent(), 0), 100) / 100, 4)


# Допомога по вагітності та пологах не оподатковується ПДФО (ПКУ п. 165.1.1) і військовим
# збором (п. 16-1 підрозд. 10 розд. XX ПКУ); ЄСВ на неї нараховується.
UNTAXED_CASE_TYPES = {"Maternity"}


def taxes(gross, employee, case_type) -> frappe._dict:
	"""Податки з виплати за випадком: як із зарплати, крім неоподатковуваних видів допомоги."""
	result = payroll_tax.split(gross, employee)

	if case_type in UNTAXED_CASE_TYPES:
		result.update(pit=0.0, military=0.0, withheld=0.0, net=result.gross)

	return result


def calculate(
	employee,
	case_type,
	start_date,
	calendar_days,
	illness_start=None,
	prior_days=0,
	average_period=None,
	average_override=None,
) -> frappe._dict:
	"""Розрахунок одного ЕЛН: стаж, відсоток і середня — на перший день усієї хвороби
	(`illness_start`), дні роботодавця — що лишились після `prior_days` попередніх ЕЛН."""
	start_date = getdate(illness_start or start_date)
	record = insurance_record(employee, start_date)
	rate, reason = percent(employee, case_type, start_date)
	months = average_pay.month_range(*average_period) if average_period and all(average_period) else None
	details = average_pay.sick_average_details(employee, start_date, months)
	details.calculated = details.average

	if flt(average_override) > 0:
		details.average = flt(average_override, 2)
		details.overridden = True

	employer_days, fund_days = split(calendar_days, max(case_rule(case_type)[0] - int(prior_days or 0), 0))
	daily = flt(details.average * rate / 100, 2)
	employer = taxes(flt(daily * employer_days, 2), employee.name, case_type)
	fund = taxes(flt(daily * fund_days, 2), employee.name, case_type)

	return frappe._dict(
		record=record,
		percent=rate,
		percent_reason=reason,
		average=details,
		daily_pay=daily,
		employer_days=employer_days,
		fund_days=fund_days,
		employer=employer,
		fund=fund,
	)


def employer_pay(employees, company, period_start, period_end) -> dict:
	"""Частина роботодавця, яку платить зарплата місяця: `{працівник: _dict}`.

	Береться кожен проведений випадок, що закінчився не пізніше кінця місяця й ще не оплачений,
	а також уже оплачений саме за цей місяць — щоб виплачений рядок відомості не втрачав суму
	при перерахунку.
	"""
	if not employees:
		return {}

	period_start, period_end = getdate(period_start), getdate(period_end)
	cases = frappe.get_all(
		"Sick Leave Case",
		filters={
			"employee": ("in", employees),
			"company": company,
			"docstatus": 1,
			"end_date": ("<=", period_end),
			"employer_days": (">", 0),
		},
		fields=[
			"name",
			"employee",
			"employer_days",
			"fund_days",
			"employer_gross",
			"fund_gross",
			"average_daily",
			"percent",
			"employer_period",
			"start_date",
		],
		order_by="start_date asc",
	)
	result = {}

	for case in cases:
		if case.employer_period and getdate(case.employer_period) != period_start:
			continue

		entry = result.setdefault(
			case.employee,
			frappe._dict(
				sick_calendar_days=0,
				sick_pay=0.0,
				sick_pay_fund=0.0,
				sick_average=0.0,
				sick_percent=0.0,
				sick_cases=[],
			),
		)
		entry.sick_calendar_days += int(case.employer_days)
		entry.sick_pay = flt(entry.sick_pay + flt(case.employer_gross), 2)
		entry.sick_pay_fund = flt(entry.sick_pay_fund + flt(case.fund_gross), 2)
		entry.sick_average = flt(case.average_daily, 2)
		entry.sick_percent = flt(case.percent)
		entry.sick_cases.append(case.name)

	return result


def mark_employer_paid(case_names, payroll_sheet, period_start, paid_date):
	"""Зарплатна відомість виплатила частину роботодавця — фіксуємо це у випадках."""
	for name in case_names or []:
		case = frappe.get_doc("Sick Leave Case", name)

		if case.employer_paid_date:
			continue

		case.payroll_sheet = payroll_sheet
		case.employer_period = getdate(period_start)
		case.employer_paid_date = getdate(paid_date)
		case.flags.ignore_permissions = True
		case.save()


def duration_warnings(case_type, calendar_days, year_days=0) -> list:
	"""Чому тривалість випадку варто перевірити: перевищено звичний строк ЕЛН.

	`year_days` — днів хвороби цього працівника за календарний рік разом із цим випадком."""
	days = int(calendar_days or 0)
	warnings = []

	if case_type in ILLNESS_CASE_TYPES:
		if days > ILLNESS_DAYS:
			warnings.append(
				_(
					"{0} days in a row: over {1} days the certificate is extended only by a decision of the ЕКОПФО commission."
				).format(days, ILLNESS_DAYS)
			)
		if int(year_days or 0) > ILLNESS_YEAR_DAYS:
			warnings.append(
				_(
					"{0} sick days this calendar year: over {1} days a repeated illness goes to the ЕКОПФО commission."
				).format(int(year_days), ILLNESS_YEAR_DAYS)
			)
	elif case_type == "Child Care" and days > CHILD_CARE_DAYS:
		warnings.append(
			_(
				"{0} days of child care: the fund usually pays up to {1} days (longer only for a hospital stay with the child)."
			).format(days, CHILD_CARE_DAYS)
		)
	elif case_type == "Family Member Care" and days > FAMILY_CARE_DAYS:
		warnings.append(
			_(
				"{0} days of care for a family member: the certificate is issued for up to {1} days, up to {2} only in exceptional cases."
			).format(days, FAMILY_CARE_DAYS, FAMILY_CARE_MAX_DAYS)
		)
	elif case_type == "Maternity" and days > MATERNITY_DAYS:
		warnings.append(
			_(
				"{0} days of maternity leave: the usual leave is {1} days, {2} for a complicated birth or twins, 180 for the Chornobyl categories."
			).format(days, MATERNITY_DAYS, MATERNITY_MAX_DAYS)
		)

	return warnings
