"""Нарахування зарплати за місяць — офіційна половина, та, що йде на картку.

Документ рахує місяць по табелю (див. `erpnext.payroll_ua.payroll_sheet_base`), нараховує його
в HRMS і платить лише офіційну частину — за домовленістю 1-го числа. Готівкову половину того
самого місяця платить окремий документ «Нарахування управлінської зарплати», бо вона йде з каси
й на кілька днів пізніше.
"""

import frappe
from frappe import _

from erpnext.payroll_ua.payroll_sheet_base import CARD, PayrollSheetBase


class PayrollSheet(PayrollSheetBase):
	part = CARD

	@frappe.whitelist()
	def create_payroll(self):
		"""Створює і подає Payroll Entry за місяць — по працівниках з повним табелем."""
		self.validate_salary_approved()

		if self.payroll_entry and frappe.db.get_value("Payroll Entry", self.payroll_entry, "docstatus") == 1:
			frappe.throw(
				_("Payroll Entry {0} is already submitted for this sheet.").format(self.payroll_entry)
			)

		entry = frappe.new_doc("Payroll Entry")
		entry.company = self.company
		entry.posting_date = self.period_end
		entry.payroll_frequency = "Monthly"
		entry.start_date = self.period_start
		entry.end_date = self.period_end
		entry.validate_attendance = 1
		entry.exchange_rate = 1
		entry.payroll_payable_account = self.payable_account()
		entry.payment_account = self.bank_account()
		entry.fill_employee_details()

		unmarked = {row["employee"] for row in (entry.get_employees_with_unmarked_attendance() or [])}
		entry.employees = [row for row in entry.employees if row.employee not in unmarked]

		if not entry.employees:
			frappe.throw(_("Nobody has a complete timesheet for this period."))

		for index, row in enumerate(entry.employees, 1):
			row.idx = index

		entry.insert()
		entry.submit()
		entry.submit_salary_slips()

		self.payroll_entry = entry.name
		self.refresh_data()

		return entry.name
