"""Виконавчий документ працівника: скільки утримувати і кому перераховувати.

Розрахунок і утримання — `erpnext.payroll_ua.enforcement`; тут лише сам документ, журнал
утримань і перерахування отримувачу.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate

from erpnext.hr import payroll_accounts
from erpnext.payroll_ua import enforcement


class EnforcementOrder(Document):
	def validate(self):
		if self.method == "Percent" and not 0 < flt(self.percent) <= 100:
			frappe.throw(_("The percent must be above 0 and not more than 100."))

		if self.method == "Fixed" and flt(self.fixed_amount) <= 0:
			frappe.throw(_("Enter the fixed amount per month."))

		if self.end_date and getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("The last day of withholding is before the first one."))

		self.set_totals()

	def on_trash(self):
		if self.withholdings:
			frappe.throw(_("Money was already withheld under this document — close it instead of deleting."))

	def set_totals(self):
		rows = self.withholdings or []
		self.withheld_total = flt(sum(flt(row.amount) for row in rows), 2)
		self.transferred_total = flt(sum(flt(row.amount) for row in rows if row.transferred), 2)
		self.to_transfer = flt(self.withheld_total - self.transferred_total, 2)

		if flt(self.debt_total) and self.withheld_total >= flt(self.debt_total) and self.status == "Active":
			self.status = "Closed"

	@frappe.whitelist()
	def transfer(self, posting_date=None):
		"""Перераховує отримувачу все утримане, що ще лежить на рахунку утримань."""
		frappe.has_permission("Enforcement Order", "write", doc=self, throw=True)

		rows = [row for row in self.withholdings if not row.transferred]
		amount = flt(sum(flt(row.amount) for row in rows), 2)

		if amount <= 0:
			frappe.throw(_("Nothing is waiting to be transferred to the recipient."))

		source = enforcement.account(self.company)
		bank = payroll_accounts.bank_account(self.company)

		if not source or not bank:
			frappe.throw(
				_("Set the bank account and the account of component «{0}» first.").format(
					enforcement.ENFORCEMENT_COMPONENT
				)
			)

		posting_date = getdate(posting_date or nowdate())
		entry = frappe.new_doc("Journal Entry")
		entry.voucher_type = "Bank Entry"
		entry.company = self.company
		entry.posting_date = posting_date
		entry.cheque_no = self.document_number or self.name
		entry.cheque_date = posting_date
		entry.user_remark = _("{0}: {1}, IBAN {2}. {3}").format(
			self.name, self.recipient_name, self.recipient_iban, self.payment_purpose or ""
		)
		entry.append("accounts", {"account": source, "debit_in_account_currency": amount})
		entry.append("accounts", {"account": bank, "credit_in_account_currency": amount})
		entry.insert()
		entry.submit()

		for row in rows:
			row.transferred = 1
			row.transfer_entry = entry.name

		self.save()

		return entry.name
