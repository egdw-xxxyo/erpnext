"""Утримання за виконавчими документами (аліменти, борги за рішенням суду).

* База — лише офіційні гроші «на руки»: нараховане мінус ПДФО і військовий збір. Готівкова
  частина не утримується.
* Відсоткові документи утримуються з кожної офіційної виплати: аванс, зарплата за місяць,
  відпускні, лікарняні (окрім допомоги у зв'язку з вагітністю та пологами — ст. 73 Закону
  «Про виконавче провадження»).
* Документ із фіксованою сумою — раз на місяць, із зарплати за місяць; що не вистачило —
  переходить на наступний місяць.
* Разом не більше 50% виплати, 70% — коли серед документів є аліменти на дітей (ст. 70
  Закону, ст. 128 КЗпП). Першими йдуть аліменти на дітей.
* Утримане не платиться одразу: воно лягає на рахунок компонента «Утримання за виконавчими
  документами» і перераховується отримувачу з документа окремою дією.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

ENFORCEMENT_COMPONENT = "Утримання за виконавчими документами"
ENFORCEMENT_ABBR = "VYK"

CHILD_ALIMONY = "Child Alimony"
GENERAL_LIMIT = 50.0
CHILD_ALIMONY_LIMIT = 70.0
PRIORITY = {CHILD_ALIMONY: 0, "Other Alimony": 1, "Other Debt": 2}


def active_orders(employee, company, on_date) -> list:
	on_date = getdate(on_date)
	orders = frappe.get_all(
		"Enforcement Order",
		filters={"employee": employee, "company": company, "status": "Active", "start_date": ("<=", on_date)},
		fields=[
			"name",
			"kind",
			"method",
			"percent",
			"fixed_amount",
			"fixed_carry",
			"debt_total",
			"withheld_total",
			"end_date",
		],
	)

	return sorted(
		[order for order in orders if not order.end_date or getdate(order.end_date) >= on_date],
		key=lambda order: PRIORITY.get(order.kind, 9),
	)


def calculate(employee, company, base, on_date, monthly=False) -> list:
	"""Скільки утримати з виплати `base` (чистої): `[(документ, сума), …]`."""
	base = flt(base, 2)

	if base <= 0:
		return []

	orders = active_orders(employee, company, on_date)

	if not orders:
		return []

	limit = CHILD_ALIMONY_LIMIT if any(order.kind == CHILD_ALIMONY for order in orders) else GENERAL_LIMIT
	room = flt(base * limit / 100, 2)
	result = []

	for order in orders:
		if room <= 0:
			break

		if order.method == "Fixed":
			if not monthly:
				continue

			wanted = flt(order.fixed_amount) + flt(order.fixed_carry)
		else:
			wanted = flt(base * flt(order.percent) / 100, 2)

		if flt(order.debt_total):
			wanted = min(wanted, max(flt(order.debt_total) - flt(order.withheld_total), 0))

		amount = flt(min(wanted, room), 2)

		if amount > 0:
			result.append((order.name, amount))
			room = flt(room - amount, 2)

	return result


def total(items) -> float:
	return flt(sum(amount for _name, amount in items or []), 2)


def encode(items) -> str:
	"""Рядком для поля документа: «EO-…: сума» по рядку на виконавчий документ."""
	return "\n".join(f"{name}: {flt(amount, 2)}" for name, amount in items or [])


def decode(text) -> list:
	items = []

	for line in (text or "").splitlines():
		name, _sep, amount = line.partition(":")

		if name.strip() and flt(amount):
			items.append((name.strip(), flt(amount, 2)))

	return items


def account(company):
	from erpnext.hr import payroll_accounts

	return payroll_accounts.component_account(company, ENFORCEMENT_COMPONENT)


def check_account(company, items):
	if items and not account(company):
		frappe.throw(
			_(
				"Set the account for salary component «{0}» for company {1}: the payment has withholdings under enforcement orders."
			).format(ENFORCEMENT_COMPONENT, company),
			title=_("No Account for Enforcement Withholdings"),
		)


def post(
	company, employee, items, posting_date, debit_account, source_doctype, source_name, base, monthly=False
):
	"""Проводить утримання: працівнику менше, отримувачу — на рахунок утримань до перерахування."""
	items = [(name, amount) for name, amount in items or [] if flt(amount) > 0]

	if not items:
		return None

	check_account(company, items)
	amount = total(items)
	party = {}

	if frappe.get_cached_value("Account", debit_account, "account_type") in ("Payable", "Receivable"):
		party = {"party_type": "Employee", "party": employee}

	entry = frappe.new_doc("Journal Entry")
	entry.voucher_type = "Journal Entry"
	entry.company = company
	entry.posting_date = getdate(posting_date)
	entry.cheque_no = source_name
	entry.cheque_date = getdate(posting_date)
	entry.user_remark = _("Withheld under enforcement orders: {0}").format(
		", ".join(name for name, _a in items)
	)
	entry.append("accounts", {"account": debit_account, "debit_in_account_currency": amount, **party})
	entry.append("accounts", {"account": account(company), "credit_in_account_currency": amount})
	entry.insert()
	entry.submit()

	for name, withheld in items:
		order = frappe.get_doc("Enforcement Order", name)
		order.append(
			"withholdings",
			{
				"posting_date": getdate(posting_date),
				"source_doctype": source_doctype,
				"source_name": source_name,
				"base": flt(base, 2),
				"amount": withheld,
				"journal_entry": entry.name,
			},
		)

		if monthly and order.method == "Fixed":
			order.fixed_carry = max(flt(flt(order.fixed_amount) + flt(order.fixed_carry) - withheld, 2), 0)

		order.flags.ignore_permissions = True
		order.save()

	return entry.name


def ensure_component():
	if frappe.db.exists("Salary Component", ENFORCEMENT_COMPONENT):
		return

	frappe.get_doc(
		{
			"doctype": "Salary Component",
			"salary_component": ENFORCEMENT_COMPONENT,
			"salary_component_abbr": ENFORCEMENT_ABBR,
			"type": "Deduction",
			"depends_on_payment_days": 0,
			"amount_based_on_formula": 0,
		}
	).insert(ignore_permissions=True)
