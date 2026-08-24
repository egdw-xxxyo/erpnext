"""Зарплата двома частинами: офіційна (на картку) і готівкова.

Джерело істини — картка працівника: `custom_official_salary` + `custom_cash_salary`. Усе інше
робиться автоматично:

* при збереженні Employee створюється поданий Salary Structure Assignment, де
  `base` = сума обох частин, а `variable` = офіційна частина;
* при перерахунку Salary Slip відрахування «До виплати готівкою» забирає все нарахування понад
  офіційну суму — тобто пропорцію відпрацьованих днів і премії з `custom_pay_in_cash`.

Офіційна сума за місяць фіксована: скільки б днів людина не відпрацювала, на картку йде рівно
вона (аванс на картку + решта на картку). Виняток один — якщо нарахування менше за офіційну суму,
готівки просто немає, і на картку йде все нарахування.

У підсумку `net_pay` листка = те, що йде на картку, а залишок рахунку «ЗП готівкою до виплати» =
те, що видається з каси.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, getdate, money_in_words, nowdate, rounded

CASH_COMPONENT = "До виплати готівкою"
CASH_ADVANCE_COMPONENT = "Аванс готівкою"
STRUCTURE_BY_COMPANY = "Структура ЗП офіц+готівка - {company}"


def sync_salary_structure_assignment(doc, method=None):
	"""Employee.on_update: тримає Salary Structure Assignment у згоді з карткою працівника."""
	try:
		_sync_assignment(doc)
	except Exception:
		frappe.log_error(
			title=f"Не вдалося синхронізувати призначення структури ЗП: {doc.name}",
			message=frappe.get_traceback(),
		)


def _sync_assignment(doc):
	if doc.status != "Active":
		return

	official = flt(doc.get("custom_official_salary"))
	cash = flt(doc.get("custom_cash_salary"))
	total = official + cash

	if not total:
		return

	effective = getdate(doc.get("custom_salary_effective_from") or get_first_day(nowdate()))

	if doc.date_of_joining and effective < getdate(doc.date_of_joining):
		effective = getdate(doc.date_of_joining)

	structure = STRUCTURE_BY_COMPANY.format(company=doc.company)

	if frappe.db.get_value("Salary Structure", structure, "is_active") != "Yes":
		frappe.msgprint(
			_("Active Salary Structure {0} not found, the assignment was not created.").format(structure),
			indicator="orange",
			alert=True,
		)
		return

	existing = frappe.db.get_value(
		"Salary Structure Assignment",
		{"employee": doc.name, "from_date": effective, "docstatus": 1},
		["name", "base", "variable"],
		as_dict=True,
	)

	if existing and flt(existing.base) == total and flt(existing.variable) == official:
		return

	if _has_submitted_slip(doc.name, effective):
		frappe.msgprint(
			_(
				"Salary is already processed for the period starting {0}, the assignment was left untouched."
			).format(frappe.format(effective, {"fieldtype": "Date"})),
			indicator="orange",
			alert=True,
		)
		return

	if existing:
		frappe.get_doc("Salary Structure Assignment", existing.name).cancel()

	assignment = frappe.get_doc(
		{
			"doctype": "Salary Structure Assignment",
			"employee": doc.name,
			"salary_structure": structure,
			"from_date": effective,
			"company": doc.company,
			"currency": doc.get("salary_currency")
			or frappe.get_cached_value("Company", doc.company, "default_currency"),
			"base": total,
			"variable": official,
		}
	)
	assignment.insert(ignore_permissions=True)
	assignment.submit()

	# CTC оновлюємо лише разом із призначенням, щоб картка не показувала суму,
	# за якою насправді ніхто не рахує зарплату.
	if flt(doc.ctc) != total:
		doc.db_set("ctc", total, update_modified=False)


def salary_parts_on(employee, on_date) -> tuple:
	"""Дві частини окладу, чинні на дату: (офіційна, готівкова).

	Читаємо чинне призначення структури, а не картку працівника: картка тримає лише останній
	затверджений оклад, і після «Зміни окладу» на майбутній місяць вона вже показує майбутню
	суму. Картка лишається запасним джерелом — для тих, кому призначення ще не створили.
	"""
	assignment = frappe.db.get_value(
		"Salary Structure Assignment",
		{"employee": employee, "docstatus": 1, "from_date": ["<=", getdate(on_date)]},
		["base", "variable"],
		order_by="from_date desc",
		as_dict=True,
	)

	if assignment:
		return flt(assignment.variable), flt(assignment.base) - flt(assignment.variable)

	official, cash = frappe.db.get_value(
		"Employee", employee, ["custom_official_salary", "custom_cash_salary"]
	) or (0, 0)

	return flt(official), flt(cash)


def apply_salary_to_employee(employee, official, cash, effective_from) -> bool:
	"""Кладе оклад у картку працівника; звідти хук `on_update` створює призначення структури.

	Повертає False, якщо в картці вже стоїть рівно те саме — щоб повторне затвердження не
	перестворювало призначення.
	"""
	doc = frappe.get_doc("Employee", employee)
	official, cash = flt(official), flt(cash)
	effective_from = getdate(effective_from)

	if (
		flt(doc.get("custom_official_salary")) == official
		and flt(doc.get("custom_cash_salary")) == cash
		and getdate(doc.get("custom_salary_effective_from") or "1900-01-01") == effective_from
	):
		return False

	doc.custom_official_salary = official
	doc.custom_cash_salary = cash
	doc.custom_salary_effective_from = effective_from
	doc.save()

	return True


def has_submitted_slip(employee, date) -> bool:
	return bool(_has_submitted_slip(employee, date))


def _has_submitted_slip(employee, date):
	return frappe.db.exists(
		"Salary Slip",
		{"employee": employee, "docstatus": 1, "start_date": ["<=", date], "end_date": [">=", date]},
	)


def apply_cash_split(doc, method=None):
	"""Salary Slip.validate: наповнює відрахування «До виплати готівкою».

	Рахується з нуля, тому хук ідемпотентний і не залежить від того, що вже лежить у рядку.
	"""
	if not doc.employee or not doc.start_date:
		return

	if not frappe.db.exists("Salary Component", CASH_COMPONENT):
		return

	# Призначення шукаємо по кінцю періоду, а не по початку: у працівника, прийнятого всередині
	# місяця, воно діє з дати прийняття, і по `start_date` ми б його не знайшли.
	assignment = frappe.db.get_value(
		"Salary Structure Assignment",
		{"employee": doc.employee, "docstatus": 1, "from_date": ["<=", doc.end_date]},
		["base", "variable"],
		order_by="from_date desc",
		as_dict=True,
	)

	if not assignment:
		return

	# Офіційна сума не ділиться на відпрацьовані дні: за домовленістю на картку за місяць має піти
	# рівно вона (аванс на картку + решта на картку). Пропорцію відпрацьованих днів і всі премії
	# поглинає готівкова частина — вона ж лишок нарахування понад офіційну суму.
	official = flt(assignment.variable) + _official_bonuses(doc)

	# Готівкову виплату зменшують лише ті відрахування, які й видані готівкою (аванс з каси,
	# задаток). Відрахування без прапорця пішли з рахунку, тож вони зменшують офіційну частину.
	cash_amount = flt(doc.gross_pay) - official - _cash_deductions(doc)
	_set_cash_row(doc, flt(max(cash_amount, 0), doc.precision("amount", "deductions")))
	_recalculate_totals(doc)


def _official_bonuses(doc):
	"""Премії та надбавки без прапорця «Виплата готівкою» — вони збільшують виплату на картку."""
	total = 0.0

	for row in doc.get("earnings") or []:
		if not row.get("additional_salary"):
			continue

		if not frappe.db.get_value("Additional Salary", row.additional_salary, "custom_pay_in_cash"):
			total += flt(row.amount)

	return total


def _cash_deductions(doc):
	"""Відрахування, видані готівкою: аванс з каси, задаток тощо."""
	total = 0.0

	for row in doc.get("deductions") or []:
		if row.salary_component == CASH_COMPONENT:
			continue

		if row.salary_component == CASH_ADVANCE_COMPONENT:
			total += flt(row.amount)
			continue

		if not row.get("additional_salary"):
			continue

		if frappe.db.get_value("Additional Salary", row.additional_salary, "custom_pay_in_cash"):
			total += flt(row.amount)

	return total


def _set_cash_row(doc, amount):
	existing = [row for row in doc.get("deductions") or [] if row.salary_component == CASH_COMPONENT]

	if not amount:
		for row in existing:
			doc.remove(row)
		return

	if existing:
		existing[0].amount = amount
		existing[0].default_amount = amount
		return

	component = frappe.get_cached_doc("Salary Component", CASH_COMPONENT)
	doc.append(
		"deductions",
		{
			"salary_component": CASH_COMPONENT,
			"abbr": component.salary_component_abbr,
			"amount": amount,
			"default_amount": amount,
			"depends_on_payment_days": 0,
			"amount_based_on_formula": 0,
		},
	)


def _recalculate_totals(doc):
	doc.total_deduction = sum(flt(row.amount) for row in doc.get("deductions") or [])
	doc.net_pay = flt(doc.gross_pay) - flt(doc.total_deduction)
	doc.rounded_total = rounded(doc.net_pay)
	doc.total_in_words = money_in_words(doc.rounded_total, doc.currency)


def backfill_from_assignments(company=None, dry_run=True):
	"""Разово розкладає наявні призначення на дві суми в картці працівника.

	bench --site frontend execute erpnext.hr.salary_split.backfill_from_assignments \
	    --kwargs "{'dry_run': False}"
	"""
	filters = {"status": "Active"}

	if company:
		filters["company"] = company

	employees = frappe.get_all("Employee", filters=filters, pluck="name")
	updated = skipped = 0

	for employee in employees:
		assignment = frappe.db.get_value(
			"Salary Structure Assignment",
			{"employee": employee, "docstatus": 1},
			["base", "variable", "from_date"],
			order_by="from_date desc",
			as_dict=True,
		)

		if not assignment or not flt(assignment.base):
			skipped += 1
			continue

		official = flt(assignment.variable)
		cash = flt(assignment.base) - official
		print(f"  {employee}: офіційна {official}, готівкова {cash}, з {assignment.from_date}")

		if dry_run:
			continue

		frappe.db.set_value(
			"Employee",
			employee,
			{
				"custom_official_salary": official,
				"custom_cash_salary": cash,
				"custom_salary_effective_from": assignment.from_date,
				"ctc": flt(assignment.base),
			},
			update_modified=False,
		)
		updated += 1

	if not dry_run:
		frappe.db.commit()

	print(f"Оброблено: {len(employees)}, оновлено: {updated}, пропущено без призначення: {skipped}")
