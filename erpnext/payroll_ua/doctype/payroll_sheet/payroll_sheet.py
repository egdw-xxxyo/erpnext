"""Зарплатна відомість за місяць — один документ замість походів по п'яти списках HRMS.

Відомість нічого не зберігає окремо: кожне число в ній читається зі штатних документів
(Attendance, Additional Salary, Salary Slip, GL Entry), а кнопки лише запускають штатні дії.
Тому перерахунок HRMS одразу видно у відомості, а не розходиться з нею.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, formatdate, get_last_day, getdate

from erpnext.hr.salary_advance import ADVANCE_CARD, ADVANCE_CASH, create_advance
from erpnext.hr.salary_split import CASH_COMPONENT

DEPOSIT_COMPONENT = "Задаток"


class PayrollSheet(Document):
	def before_naming(self):
		# `autoname` reads year and month, and it runs before validate.
		self.set_period()

	def validate(self):
		self.set_period()
		self.collect()

	def set_period(self):
		# Період вибирається одним полем-місяцем; `year` і `month` лишаються заради
		# іменування та сортування, тож заповнюємо їх з дати.
		if not self.period_start:
			frappe.throw(_("Month is required"))

		self.period_start = getdate(self.period_start).replace(day=1)
		self.period_end = get_last_day(self.period_start)
		self.year = self.period_start.year
		self.month = str(self.period_start.month)

	@frappe.whitelist()
	def refresh_data(self):
		self.set_period()
		self.collect()
		self.save()

		return self.name

	def collect(self):
		"""Перебудовує таблицю працівників з даних HRMS."""
		slips = self._slips()
		advances = self._additional_salary()
		attendance = self._attendance_days()
		outstanding = self._outstanding_by_party()

		self.set("employees", [])

		for employee in self._employees():
			slip = slips.get(employee.name)
			extra = advances.get(employee.name, {})
			card = flt(slip and slip.net_pay)
			cash = flt(slip and slip.cash)
			due = flt(outstanding.get(employee.name))

			row = self.append(
				"employees",
				{
					"employee": employee.name,
					"employee_name": employee.employee_name,
					"department": employee.department,
					"manager": employee.reports_to,
					"credited_days": flt(slip and slip.payment_days) or flt(attendance.get(employee.name)),
					"total_working_days": flt(slip and slip.total_working_days),
					"gross_pay": flt(slip and slip.gross_pay),
					"advance_card": flt(extra.get(ADVANCE_CARD)),
					"advance_cash": flt(extra.get(ADVANCE_CASH)),
					"salary_card": card,
					"salary_cash": cash,
					"deposit": flt(extra.get(DEPOSIT_COMPONENT)),
					"salary_slip": slip and slip.name,
					"outstanding": due,
					"paid": 1 if slip and not due else 0,
				},
			)

			if row.credited_days and row.total_working_days:
				row.daily_rate = flt(row.gross_pay) / flt(row.credited_days)

			if not slip:
				row.note = (
					_("No attendance for the period")
					if not attendance.get(employee.name)
					else _("Not accrued yet")
				)

		self.set_totals()

	def _employees(self):
		return frappe.get_all(
			"Employee",
			filters={
				"company": self.company,
				"status": "Active",
				"date_of_joining": ["<=", self.period_end],
			},
			fields=["name", "employee_name", "department", "reports_to"],
			order_by="department asc, employee_name asc",
		)

	def _slips(self):
		slips = frappe.get_all(
			"Salary Slip",
			filters={
				"company": self.company,
				"docstatus": ["<", 2],
				"start_date": [">=", self.period_start],
				"end_date": ["<=", self.period_end],
			},
			fields=["name", "employee", "gross_pay", "net_pay", "payment_days", "total_working_days"],
		)
		by_employee = {}

		for slip in slips:
			slip.cash = flt(
				frappe.db.get_value(
					"Salary Detail",
					{"parent": slip.name, "parenttype": "Salary Slip", "salary_component": CASH_COMPONENT},
					"amount",
				)
			)
			by_employee[slip.employee] = slip

		return by_employee

	def _additional_salary(self):
		rows = frappe.get_all(
			"Additional Salary",
			filters={
				"company": self.company,
				"docstatus": 1,
				"payroll_date": ["between", [self.period_start, self.period_end]],
				"salary_component": ["in", [ADVANCE_CARD, ADVANCE_CASH, DEPOSIT_COMPONENT]],
			},
			fields=["employee", "salary_component", "amount"],
		)
		by_employee = {}

		for row in rows:
			by_employee.setdefault(row.employee, {})
			by_employee[row.employee][row.salary_component] = flt(
				by_employee[row.employee].get(row.salary_component)
			) + flt(row.amount)

		return by_employee

	def _attendance_days(self):
		rows = frappe.db.sql(
			"""select employee, count(*) as days from `tabAttendance`
			where docstatus = 1 and company = %(company)s and status != 'Absent'
			and attendance_date between %(start)s and %(end)s group by employee""",
			{"company": self.company, "start": self.period_start, "end": self.period_end},
			as_dict=True,
		)

		return {row.employee: row.days for row in rows}

	def _outstanding_by_party(self):
		"""Скільки ще винні працівнику по рахунку зарплати до виплати.

		Готівкова частина живе одним рядком без контрагента, тож по працівниках видно лише
		офіційну — саме її й закриває банківський платіж.
		"""
		account = self.payable_account()

		if not account:
			return {}

		rows = frappe.db.sql(
			"""select party, sum(credit) - sum(debit) as due from `tabGL Entry`
			where is_cancelled = 0 and account = %(account)s and party_type = 'Employee'
			and posting_date between %(start)s and %(end)s group by party""",
			{"account": account, "start": self.period_start, "end": self.period_end},
			as_dict=True,
		)

		return {row.party: flt(row.due) for row in rows}

	def set_totals(self):
		self.total_employees = len(self.employees)
		self.employees_without_attendance = len([row for row in self.employees if not row.salary_slip])
		self.paid_employees = len([row for row in self.employees if row.paid and row.salary_card])

		for field, source in (
			("total_credited_days", "credited_days"),
			("total_gross", "gross_pay"),
			("total_advance_card", "advance_card"),
			("total_advance_cash", "advance_cash"),
			("total_salary_card", "salary_card"),
			("total_salary_cash", "salary_cash"),
			("total_outstanding", "outstanding"),
		):
			self.set(field, sum(flt(row.get(source)) for row in self.employees))

		self.status = self.derive_status()

	def derive_status(self):
		accrued = [row for row in self.employees if row.salary_slip]

		if not accrued:
			return "Draft"

		if not flt(self.total_outstanding):
			return "Paid"

		if self.paid_employees:
			return "Partly Paid"

		return "To Pay"

	# --- дії ------------------------------------------------------------------

	@frappe.whitelist()
	def calculate_advance(self, cutoff_day=15):
		self.validate_salary_approved()
		rows = create_advance(self.company, int(self.year), int(self.month), int(cutoff_day), dry_run=False)
		self.refresh_data()

		return len(rows)

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

	def validate_salary_approved(self):
		"""Гроші рахуємо тільки після «Затвердження ЗП» за цей місяць: саме воно кладе
		оклади в картки працівників, з яких HRMS будує нарахування."""
		approval = frappe.db.exists(
			"Salary Approval",
			{"company": self.company, "effective_from": self.period_start, "status": "Approved"},
		)

		if approval:
			return

		frappe.throw(
			_("Approve the salary for {0} first — there is no approved Salary Approval for {1}.").format(
				formatdate(self.period_start, "MM.yyyy"), self.company
			),
			title=_("Salary Not Approved"),
		)

	@frappe.whitelist()
	def pay(self, kind, posting_date=None):
		"""Проводить виплату: `advance` — аванс, `final` — розрахунок за місяць."""
		posting_date = getdate(
			posting_date or (self.period_end if kind == "final" else None) or self.period_start
		)
		vouchers = []

		if kind == "advance":
			payouts = (
				(
					self.bank_account(),
					self.advance_account(),
					flt(self.total_advance_card),
					_("Advance to cards"),
				),
				(
					self.cash_account(),
					self.advance_account(),
					flt(self.total_advance_cash),
					_("Advance in cash"),
				),
			)
		else:
			payouts = (
				(
					self.bank_account(),
					self.payable_account(),
					flt(self.total_salary_card),
					_("Salary to cards"),
				),
				(
					self.cash_account(),
					self.cash_payable_account(),
					flt(self.total_salary_cash),
					_("Salary in cash"),
				),
			)

		for paid_from, paid_to, amount, remark in payouts:
			if not flt(amount, 2):
				continue

			vouchers.append(self._make_journal_entry(paid_from, paid_to, amount, posting_date, remark, kind))

		self.refresh_data()

		return vouchers

	def _make_journal_entry(self, paid_from, paid_to, amount, posting_date, remark, kind):
		if not paid_from or not paid_to:
			frappe.throw(_("Set the payroll accounts for company {0} first.").format(self.company))

		is_bank = paid_from == self.bank_account()
		title = f"{remark} {self.month}.{self.year}"
		entry = frappe.new_doc("Journal Entry")
		entry.voucher_type = "Bank Entry" if is_bank else "Cash Entry"
		entry.company = self.company
		entry.posting_date = posting_date
		entry.cheque_no = title
		entry.cheque_date = posting_date
		entry.user_remark = title

		# Офіційну частину закриваємо по кожному працівнику окремо — саме так її нарахував HRMS,
		# інакше рахунок не зійдеться по контрагентах.
		if is_bank and kind == "final":
			for row in self.employees:
				if flt(row.salary_card, 2):
					entry.append(
						"accounts",
						{
							"account": paid_to,
							"party_type": "Employee",
							"party": row.employee,
							"debit_in_account_currency": flt(row.salary_card, 2),
						},
					)
			amount = sum(flt(row.salary_card, 2) for row in self.employees)
		else:
			entry.append("accounts", {"account": paid_to, "debit_in_account_currency": flt(amount, 2)})

		entry.append("accounts", {"account": paid_from, "credit_in_account_currency": flt(amount, 2)})
		entry.insert()
		entry.submit()

		return entry.name

	# --- рахунки --------------------------------------------------------------

	def payable_account(self):
		return frappe.get_cached_value("Company", self.company, "default_payroll_payable_account")

	def bank_account(self):
		account = frappe.get_cached_value("Company", self.company, "default_bank_account")

		if account:
			return account

		# У компанії може не бути рахунку за замовчуванням — беремо єдиний банківський,
		# і мовчимо лише тоді, коли вибір неоднозначний.
		accounts = frappe.get_all(
			"Account",
			filters={"company": self.company, "account_type": "Bank", "is_group": 0},
			pluck="name",
		)

		return accounts[0] if len(accounts) == 1 else None

	def cash_account(self):
		return frappe.get_cached_value("Company", self.company, "default_cash_account")

	def cash_payable_account(self):
		return self._component_account(CASH_COMPONENT)

	def advance_account(self):
		return self._component_account(ADVANCE_CARD)

	def _component_account(self, component):
		return frappe.db.get_value(
			"Salary Component Account", {"parent": component, "company": self.company}, "account"
		)
