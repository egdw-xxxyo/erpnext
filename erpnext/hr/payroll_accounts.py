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
