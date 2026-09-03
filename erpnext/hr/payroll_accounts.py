"""Зарплатні рахунки компанії й проведення виплат.

І аванс, і остаточний розрахунок платяться однаково: з банківського рахунку на картки та з
каси — готівкою. Тримаємо це в одному місці, щоб «Аванс» і «Зарплатна відомість» не розійшлися
в проведеннях.
"""

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.hr.salary_advance import ADVANCE_CARD
from erpnext.hr.salary_split import CASH_COMPONENT

# Рахунок витрат на зарплату — з нього ж списується ЄСВ, який платить роботодавець.
SALARY_EXPENSE_COMPONENT = "Оклад"


def payable_account(company):
	return frappe.get_cached_value("Company", company, "default_payroll_payable_account")


def bank_account(company):
	account = frappe.get_cached_value("Company", company, "default_bank_account")

	if account:
		return account

	# У компанії може не бути рахунку за замовчуванням — беремо єдиний банківський,
	# і мовчимо лише тоді, коли вибір неоднозначний.
	accounts = frappe.get_all(
		"Account",
		filters={"company": company, "account_type": "Bank", "is_group": 0},
		pluck="name",
	)

	return accounts[0] if len(accounts) == 1 else None


def cash_account(company):
	return frappe.get_cached_value("Company", company, "default_cash_account")


def cash_payable_account(company):
	return component_account(company, CASH_COMPONENT)


def advance_account(company):
	return component_account(company, ADVANCE_CARD)


def component_account(company, component):
	return frappe.db.get_value(
		"Salary Component Account", {"parent": component, "company": company}, "account"
	)


def salary_expense_account(company):
	return component_account(company, SALARY_EXPENSE_COMPONENT)


def tax_account(company, component):
	"""Рахунок податку береться з самого компонента — бухгалтер міняє його в довіднику
	«Складова зарплати», а не в коді."""
	return component_account(company, component)


def requires_party(account):
	"""Рахунки типу «дебіторська/кредиторська» проведення без контрагента не приймають."""
	return frappe.get_cached_value("Account", account, "account_type") in ("Payable", "Receivable")


def make_journal_entry(company, paid_from, paid_to, amount, posting_date, remark, parties=None):
	"""Одне проведення виплати: банківське, якщо платимо з банку, інакше касове.

	`parties` — пари (працівник, сума) для розкладки боргу по контрагентах: офіційну частину
	HRMS нараховує на кожного окремо, тож і закривати її треба так само, інакше рахунок не
	зійдеться по працівниках.
	"""
	if not paid_from or not paid_to:
		frappe.throw(_("Set the payroll accounts for company {0} first.").format(company))

	entry = frappe.new_doc("Journal Entry")
	entry.voucher_type = "Bank Entry" if paid_from == bank_account(company) else "Cash Entry"
	entry.company = company
	entry.posting_date = posting_date
	entry.cheque_no = remark
	entry.cheque_date = posting_date
	entry.user_remark = remark

	if parties:
		amount = sum(flt(party_amount, 2) for _employee, party_amount in parties)

		for employee, party_amount in parties:
			entry.append(
				"accounts",
				{
					"account": paid_to,
					"party_type": "Employee",
					"party": employee,
					"debit_in_account_currency": flt(party_amount, 2),
				},
			)
	else:
		entry.append("accounts", {"account": paid_to, "debit_in_account_currency": flt(amount, 2)})

	entry.append("accounts", {"account": paid_from, "credit_in_account_currency": flt(amount, 2)})
	entry.insert()
	entry.submit()

	return entry.name


def make_tax_entry(company, posting_date, remark, pit=0.0, military=0.0, ssc=0.0):
	"""Проведення податків із виплати: утримане з працівника й ЄСВ зверху.

	ПДФО і військовий збір компанія втримала із нарахованого — вони знімаються із зарплатного
	пасиву й лягають на рахунки «до сплати», де й видно борг перед бюджетом. ЄСВ працівника не
	торкається: це витрата роботодавця, тож дебет іде на витрати на оплату праці.

	Повертає назву проведення або None, коли рахунки не налаштовані чи сум немає.
	"""
	from erpnext.hr import payroll_tax

	pit, military, ssc = flt(pit, 2), flt(military, 2), flt(ssc, 2)
	withheld = flt(pit + military, 2)

	if not (withheld or ssc):
		return None

	payable = payable_account(company)
	expense = salary_expense_account(company)
	lines = []

	if withheld:
		accounts = {
			payroll_tax.PIT_COMPONENT: pit,
			payroll_tax.MILITARY_COMPONENT: military,
		}

		if not payable or not all(tax_account(company, component) for component in accounts):
			_warn_missing_tax_accounts(company)
			return None

		lines.append({"account": payable, "debit_in_account_currency": withheld})
		lines += [
			{"account": tax_account(company, component), "credit_in_account_currency": amount}
			for component, amount in accounts.items()
			if amount
		]

	if ssc:
		ssc_account = tax_account(company, payroll_tax.SSC_COMPONENT)

		if not expense or not ssc_account:
			_warn_missing_tax_accounts(company)
		else:
			lines.append({"account": expense, "debit_in_account_currency": ssc})
			lines.append({"account": ssc_account, "credit_in_account_currency": ssc})

	if not lines:
		return None

	entry = frappe.new_doc("Journal Entry")
	entry.voucher_type = "Journal Entry"
	entry.company = company
	entry.posting_date = posting_date
	entry.cheque_no = remark
	entry.cheque_date = posting_date
	entry.user_remark = remark

	for line in lines:
		entry.append("accounts", line)

	entry.insert()
	entry.submit()

	return entry.name


def _warn_missing_tax_accounts(company):
	"""Гроші вже пішли — податки лише не проведені, тож зупиняти виплату не можна."""
	frappe.msgprint(
		_("Set the tax accounts for company {0} — the taxes of this payment are not posted.").format(company),
		indicator="orange",
		alert=True,
	)
