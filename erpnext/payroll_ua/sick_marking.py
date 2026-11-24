"""Лікарняний із табеля: кожен день «Лікарняного» належить «Випадку лікарняного».

Табель відмічають першим — номер ЕЛН з'являється пізніше, на порталі ПФУ. Тож відмітка
«Лікарняний» одразу створює випадок (або продовжує чернетку, яка закінчилась напередодні),
а номер ЕЛН додають у випадку потім. Дні, що вже належать випадку, табель не змінює: їх
змінює сам випадок, інакше табель і розрахунок лікарняного розійдуться.
"""

import frappe
from frappe import _
from frappe.utils import add_days, formatdate, getdate

from erpnext.payroll_ua import sick_rules
from erpnext.payroll_ua.doctype.sick_leave_case.sick_leave_case import _continues

CASE = "Sick Leave Case"


def case_days(employees: list, from_date, to_date) -> dict:
	"""Які дні періоду належать випадкам: `{працівник: {дата: {name, submitted, eln}}}`."""
	if not employees:
		return {}

	from_date, to_date = getdate(from_date), getdate(to_date)
	cases = {
		case.name: case
		for case in frappe.get_all(
			CASE,
			filters={
				"employee": ("in", employees),
				"docstatus": ("<", 2),
				"start_date": ("<=", to_date),
				"end_date": (">=", from_date),
			},
			fields=["name", "employee", "docstatus", "start_date", "end_date", "eln_number"],
		)
	}

	result = {}

	for case in cases.values():
		day = max(getdate(case.start_date), from_date)
		last = min(getdate(case.end_date), to_date)

		while day <= last:
			result.setdefault(case.employee, {})[day] = {
				"name": case.name,
				"submitted": case.docstatus == 1,
				"eln": (case.eln_number or "").strip(),
			}
			day = add_days(day, 1)

	return result


def case_on(employee: str, day) -> dict | None:
	return case_days([employee], day, day).get(employee, {}).get(getdate(day))


def assert_not_in_case(employee: str, day) -> None:
	"""День випадку змінюється лише у випадку: табель і розрахунок мусять сходитись."""
	case = case_on(employee, day)

	if case:
		frappe.throw(
			_("{0} belongs to sick leave case {1} — change it in the case.").format(
				formatdate(day), case["name"]
			)
		)


def resolve(employee: str, from_date, to_date) -> dict:
	"""Що робити з лікарняним за ці дні: продовжити чернетку чи відкрити новий випадок.

	Чернетка продовжується, коли закінчилась напередодні або перед самими вихідними: ЕЛН
	іде календарними днями, тож продовження заповнює й ці вихідні. Відрізок, що заходить
	на дні тієї ж чернетки, продовжує її з наступного після неї дня.
	"""
	from_date, to_date = getdate(from_date), getdate(to_date)
	taken = case_days([employee], from_date, to_date).get(employee) or {}
	company = frappe.db.get_value("Employee", employee, "company")
	target = None

	if taken:
		names = {entry["name"] for entry in taken.values()}
		case = frappe.db.get_value(CASE, names.pop(), ["name", "docstatus", "end_date"], as_dict=True)

		if names or case.docstatus != 0 or getdate(case.end_date) >= to_date:
			return {"error": _overlap_message(taken)}

		target = case
	else:
		previous = frappe.get_all(
			CASE,
			filters={"employee": employee, "docstatus": 0, "end_date": ("<", from_date)},
			fields=["name", "docstatus", "end_date"],
			order_by="end_date desc",
			limit=1,
		)

		if previous and _continues(getdate(previous[0].end_date), from_date, employee, company, {}):
			target = previous[0]

	if not target:
		return {"extend": None, "company": company}

	details = frappe.db.get_value(CASE, target.name, ["start_date", "end_date", "case_type"], as_dict=True)

	return {
		"extend": {
			"name": target.name,
			"start_date": str(details.start_date),
			"end_date": str(details.end_date),
			"case_type": details.case_type,
			"from_date": str(add_days(details.end_date, 1)),
		},
		"company": company,
	}


def options(employee: str, from_date, to_date) -> dict:
	result = resolve(employee, from_date, to_date)
	result["case_types"] = list(sick_rules.CASE_TYPES)
	result["default_case_type"] = sick_rules.DEFAULT_CASE_TYPE

	return result


def mark(
	employee: str, from_date, to_date, action: str = "auto", case_type=None, eln_number=None, mark_day=None
) -> dict:
	"""Відмічає лікарняний і кладе його у випадок. `action`: auto, extend або new.

	`mark_day` — відмітка одного дня табеля (із перевірками самого табеля); без неї днями
	займається лише випадок."""
	from_date, to_date = getdate(from_date), getdate(to_date)
	plan = resolve(employee, from_date, to_date)

	if plan.get("error"):
		frappe.throw(plan["error"])

	extend = plan.get("extend") if action in ("auto", "extend") else None

	if action == "extend" and not extend:
		frappe.throw(_("There is no draft sick leave case that these days continue."))

	eln_number = (eln_number or "").strip() or None
	first_day = getdate(extend["from_date"]) if extend else from_date
	created, skipped = [], []

	if mark_day:
		day = max(from_date, first_day)

		while day <= to_date:
			outcome = mark_day(employee, day, {"status": "Sick Leave"})

			if outcome.get("name"):
				created.append(outcome["name"])
			else:
				skipped.append(outcome["skipped"])

			day = add_days(day, 1)

	if extend:
		doc = frappe.get_doc(CASE, extend["name"])

		# Поки в ЕЛН немає номера, це той самий листок, що просто триває; з номером —
		# продовження окремим ЕЛН у тому ж випадку непрацездатності.
		if not (doc.eln_number or "").strip():
			doc.end_date = to_date
			doc.eln_number = eln_number
		else:
			doc = _new_case(employee, plan["company"], doc.case_type, first_day, to_date, eln_number)
			doc.incapacity_case = frappe.db.get_value(CASE, extend["name"], "incapacity_case")
	else:
		doc = _new_case(
			employee,
			plan["company"],
			case_type or sick_rules.DEFAULT_CASE_TYPE,
			from_date,
			to_date,
			eln_number,
		)

	doc.flags.ignore_permissions = True
	doc.save()

	return {"case": doc.name, "extended": bool(extend), "created": created, "skipped": skipped}


def _new_case(employee, company, case_type, from_date, to_date, eln_number):
	doc = frappe.new_doc(CASE)
	doc.employee = employee
	doc.company = company
	doc.case_type = case_type
	doc.start_date = from_date
	doc.end_date = to_date
	doc.eln_number = eln_number

	return doc


def _overlap_message(taken: dict) -> str:
	names = sorted({entry["name"] for entry in taken.values()})
	days = sorted(taken)

	return _("{0} — {1} already belong to sick leave case {2}.").format(
		formatdate(days[0]), formatdate(days[-1]), ", ".join(names)
	)
