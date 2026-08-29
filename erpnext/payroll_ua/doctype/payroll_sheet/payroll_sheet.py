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

	def after_payment(self, employees):
		"""Виплата тягне за собою нарахування: на кожного оплаченого — зарплатний листок.

		Кадрам потрібен листок, а не тільки проведення: без нього людина в HRMS за місяць
		нічого не заробила. Робити його заздалегідь через Payroll Entry не виходить — той
		вимагає закритого табеля на всіх, тож місяць стояв би через одну незакриту людину.
		Помилка на комусь одному виплату не скасовує: гроші вже пішли, а листок можна
		створити пізніше — тому невдачі збираються і показуються списком.
		"""
		failed = []

		for employee in employees:
			try:
				self.ensure_salary_slip(employee)
			except Exception:
				frappe.log_error(title="Payroll Sheet: salary slip", message=frappe.get_traceback())
				failed.append(employee)

		if failed:
			frappe.msgprint(
				_("Paid, but the salary slip was not created for: {0}. See the error log.").format(
					", ".join(
						frappe.get_cached_value("Employee", name, "employee_name") or name for name in failed
					)
				),
				title=_("Salary Slip Not Created"),
				indicator="orange",
			)

	def ensure_salary_slip(self, employee):
		"""Листок працівника за цей місяць — уже наявний або новий, і обов'язково проведений.

		Чернетку теж доводиться подавати: коли людей більше тридцяти, HRMS створює листки
		у фоні й лишає їх непроведеними (див. `create_payroll`).
		"""
		existing = frappe.db.get_value(
			"Salary Slip",
			{
				"employee": employee,
				"start_date": self.period_start,
				"end_date": self.period_end,
				"docstatus": ("<", 2),
			},
			["name", "docstatus"],
			as_dict=True,
		)

		if existing:
			if not existing.docstatus:
				frappe.get_doc("Salary Slip", existing.name).submit()

			return existing.name

		slip = frappe.new_doc("Salary Slip")
		slip.employee = employee
		slip.company = self.company
		slip.payroll_frequency = "Monthly"
		slip.start_date = self.period_start
		slip.end_date = self.period_end
		slip.posting_date = self.period_end
		slip.insert()
		slip.submit()

		return slip.name

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

		# Понад тридцять працівників HRMS обробляє у фоні: на цей момент листків ще немає,
		# тож подавати нема чого — раніше цей виклик мовчки нічого не робив і весь місяць
		# лишався в чернетках. Те, що не встигло, подасть виплата (`ensure_salary_slip`).
		if entry.get_sal_slip_list(ss_status=0):
			entry.submit_salary_slips()
		else:
			frappe.msgprint(
				_(
					"The salary slips are being created in the background. Each one is submitted when its employee is paid."
				),
				title=_("Accrual Queued"),
				indicator="blue",
			)

		self.payroll_entry = entry.name
		self.refresh_data()

		return entry.name
