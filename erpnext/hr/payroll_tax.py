"""Податки з офіційної частини зарплати.

Офіційна сума в картці працівника — **нарахована**, а не та, що падає на картку. Із неї
утримуються два податки працівника:

* ПДФО — 18%;
* військовий збір — 5%.

Разом 23%, тож на картку йде 77% нарахованої суми. ЄСВ 22% податком працівника не є: його
платить роботодавець **зверху** на нарахування, тож у виплату він не входить і рахується лише
як вартість працівника для компанії.

Для працівника з групою інвалідності (будь-якою — I, II чи III) ЄСВ рахується за пільговою
ставкою 8,41%, і доплата до мінімального страхового внеску не застосовується: внесок береться
з фактичної зарплати. Підставою є довідка МСЕК, тож група й довідка живуть у картці працівника
(`custom_disability_group`, `custom_disability_certificate`).

Самі ставки лежать у «Налаштуваннях зарплатних податків» — їх міняє закон, тож у коді вони лише
запасні значення.

Готівкова частина не оподатковується — вона не проходить нарахуванням, тож усі функції цього
модуля стосуються виключно офіційної суми.
"""

import frappe
from frappe import _
from frappe.utils import flt

PIT_RATE = 0.18
MILITARY_RATE = 0.05
SSC_RATE = 0.22
SSC_DISABILITY_RATE = 0.0841

SETTINGS = "Payroll Tax Settings"

PIT_COMPONENT = "ПДФО"
MILITARY_COMPONENT = "Військовий збір"
SSC_COMPONENT = "ЄСВ (роботодавець)"

PIT_ABBR = "PDFO"
MILITARY_ABBR = "VZ"
SSC_ABBR = "ESV"

DISABILITY_GROUPS = ("I", "I А", "I Б", "II", "III")


def rate(fieldname, fallback) -> float:
	"""Ставка з налаштувань у частках одиниці; поки налаштувань немає — законна за замовчуванням."""
	try:
		value = frappe.db.get_single_value(SETTINGS, fieldname)
	except Exception:
		# Міграція, на якій DocType ще не створений, не має валити нарахування.
		value = None

	return flt(value) / 100 if value else fallback


def ssc_rate(employee=None) -> float:
	"""Ставка ЄСВ: пільгова, якщо в картці працівника стоїть група інвалідності."""
	if employee and has_disability(employee):
		return rate("ssc_disability_rate", SSC_DISABILITY_RATE)

	return rate("ssc_rate", SSC_RATE)


def has_disability(employee) -> bool:
	return bool(frappe.db.get_value("Employee", employee, "custom_disability_group"))


def warn_missing_certificate(doc, method=None):
	"""Employee.validate: пільгова ставка ЄСВ тримається на довідці МСЕК — без неї це просто
	слово в картці, тож нагадуємо, але зберегти не заважаємо."""
	if doc.get("custom_disability_group") and not doc.get("custom_disability_certificate"):
		frappe.msgprint(
			_("Enter the MSEC certificate — the reduced SSC rate is applied on it."),
			indicator="orange",
			alert=True,
		)


def split(gross, employee=None) -> frappe._dict:
	"""Розкладає нараховану офіційну суму: що утримали, що лишилось на картку, скільки ЄСВ.

	Округлення робиться тут і один раз, щоб листок, аванс і відомість показували ті самі
	копійки — інакше «до виплати» в трьох документах розходиться на копійку.
	"""
	gross = flt(gross, 2)
	pit = flt(gross * rate("pit_rate", PIT_RATE), 2)
	military = flt(gross * rate("military_levy_rate", MILITARY_RATE), 2)

	return frappe._dict(
		gross=gross,
		pit=pit,
		military=military,
		withheld=flt(pit + military, 2),
		net=flt(gross - pit - military, 2),
		ssc=flt(gross * ssc_rate(employee), 2),
	)


def net(gross, employee=None) -> float:
	"""Скільки з нарахованої офіційної суми дійде до картки."""
	return split(gross, employee).net


def withheld(gross, employee=None) -> float:
	"""ПДФО + військовий збір з нарахованої офіційної суми."""
	return split(gross, employee).withheld


def employer_ssc(gross, employee=None) -> float:
	"""ЄСВ, який компанія платить зверху на нарахування."""
	return split(gross, employee).ssc


def ensure_components():
	"""Створює податкові компоненти, якщо їх ще немає.

	Утримані податки лишаються на зарплатному рахунку компанії до сплати в бюджет, тож
	рахунок беремо той самий, на якому HRMS тримає нарахування. ЄСВ — статистичний компонент:
	він видно в листку, але жодну суму до виплати не зменшує.
	"""
	accounts = _payable_accounts()

	for component, abbr, statistical in (
		(PIT_COMPONENT, PIT_ABBR, 0),
		(MILITARY_COMPONENT, MILITARY_ABBR, 0),
		(SSC_COMPONENT, SSC_ABBR, 1),
	):
		if frappe.db.exists("Salary Component", component):
			continue

		doc = frappe.get_doc(
			{
				"doctype": "Salary Component",
				"salary_component": component,
				"salary_component_abbr": abbr,
				"type": "Deduction",
				"depends_on_payment_days": 0,
				"amount_based_on_formula": 0,
				"statistical_component": statistical,
				"do_not_include_in_total": statistical,
				"accounts": [] if statistical else accounts,
			}
		)
		doc.insert(ignore_permissions=True)


def _payable_accounts() -> list:
	rows = []

	for company in frappe.get_all("Company", pluck="name"):
		account = frappe.get_cached_value("Company", company, "default_payroll_payable_account")

		if account:
			rows.append({"company": company, "account": account})

	return rows
