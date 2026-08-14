"""Зарплата двома частинами: офіційна (на картку) і готівкова.

Джерело істини — картка працівника: `custom_official_salary` + `custom_cash_salary`. Усе інше
робиться автоматично:

* при збереженні Employee створюється поданий Salary Structure Assignment, де
  `base` = сума обох частин, а `variable` = офіційна частина;
* при перерахунку Salary Slip відрахування «До виплати готівкою» отримує готівкову частину окладу
  плюс ті премії (`Additional Salary`), у яких стоїть `custom_pay_in_cash`.

У підсумку `net_pay` листка = те, що йде на картку, а залишок рахунку «ЗП готівкою до виплати» =
те, що видається з каси.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, getdate, money_in_words, nowdate, rounded

CASH_COMPONENT = "До виплати готівкою"
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

	if flt(doc.ctc) != total:
		doc.db_set("ctc", total, update_modified=False)

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

	assignment = frappe.db.get_value(
		"Salary Structure Assignment",
		{"employee": doc.employee, "docstatus": 1, "from_date": ["<=", doc.start_date]},
		["base", "variable"],
		order_by="from_date desc",
		as_dict=True,
	)

	if not assignment:
		return

	# Аванс і задаток уже видані готівкою, тому вони зменшують саме готівкову виплату,
	# а не офіційну частину — інакше «на картку» лишається менше за домовлену суму.
	cash_amount = _cash_part_of_base(doc, assignment) + _cash_bonuses(doc) - _other_deductions(doc)
	_set_cash_row(doc, flt(max(cash_amount, 0), doc.precision("amount", "deductions")))
	_recalculate_totals(doc)


def _cash_part_of_base(doc, assignment):
	base_cash = flt(assignment.base) - flt(assignment.variable)

	if base_cash <= 0:
		return 0.0

	working_days = flt(doc.total_working_days)

	if not working_days:
		return 0.0

	return base_cash * flt(doc.payment_days) / working_days


def _cash_bonuses(doc):
	"""Сума премій і надбавок, позначених «Виплата готівкою»."""
	total = 0.0

	for row in doc.get("earnings") or []:
		if not row.get("additional_salary"):
			continue

		if frappe.db.get_value("Additional Salary", row.additional_salary, "custom_pay_in_cash"):
			total += flt(row.amount)

	return total


def _other_deductions(doc):
	"""Решта відрахувань листка — аванс, задаток тощо."""
	return sum(
		flt(row.amount) for row in doc.get("deductions") or [] if row.salary_component != CASH_COMPONENT
	)


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
