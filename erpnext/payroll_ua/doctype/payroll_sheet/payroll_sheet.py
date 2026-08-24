"""Зарплатна відомість за місяць — один документ замість походів по п'яти списках HRMS.

Відомість нічого не зберігає окремо: кожне число в ній читається зі штатних документів
(Attendance, Additional Salary, Salary Slip, GL Entry), а кнопки лише запускають штатні дії.
Тому перерахунок HRMS одразу видно у відомості, а не розходиться з нею.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, formatdate, get_last_day, getdate

from erpnext.hr import payroll_accounts
from erpnext.hr.salary_advance import ADVANCE_CARD, ADVANCE_CASH, attendance_summary
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
		self.advance_sheet = frappe.db.get_value(
			"Salary Advance", {"company": self.company, "period_start": self.period_start}
		)
		slips = self._slips()
		advances = self._additional_salary()
		attendance = self._attendance_days()
		outstanding = self._outstanding_by_party()
		employees = self._employees()
		stats = attendance_summary([row.name for row in employees], self.period_start, self.period_end)
		# Таблиця будується наново з HRMS, а сліди виплати живуть лише тут — переносимо їх.
		paid_marks = {
			row.employee: (row.journal_entry_card, row.journal_entry_cash, row.paid_date)
			for row in self.employees
		}

		self.set("employees", [])

		for employee in employees:
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

			row.journal_entry_card, row.journal_entry_cash, row.paid_date = paid_marks.get(
				employee.name, (None, None, None)
			)
			# Готівкова частина лежить на рахунку без контрагента, тож борг по працівнику її не
			# бачить: рядок з готівкою вважається закритим лише після проведення виплати.
			if cash and not row.paid_date:
				row.paid = 0
			self._set_attendance(row, stats.get(employee.name))

			if row.credited_days and row.total_working_days:
				row.daily_rate = flt(row.gross_pay) / flt(row.credited_days)

			if not slip:
				row.note = (
					_("No attendance for the period")
					if not attendance.get(employee.name)
					else _("Not accrued yet")
				)

		self.set_totals()

	def _set_attendance(self, row, summary):
		"""Розклад табеля за місяць — те саме, що бачить «Аванс», лише за повний період.

		`credited_days` тут лишається від листка: платить HRMS, а не наш підрахунок.
		"""
		for field, value in (summary or {}).items():
			if field != "credited_days":
				row.set(field, value)

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
		self.bonus_approved = 1 if self.bonus_approval() else 0
		self.total_employees = len(self.employees)
		self.employees_without_attendance = len([row for row in self.employees if not row.credited_days])
		self.employees_not_accrued = len(
			[row for row in self.employees if row.credited_days and not row.salary_slip]
		)
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
		"""«Виплачено» ставить бухгалтер кнопкою — сам документ доходить лише до «Частково».

		Нульовий залишок ще не означає закритий місяць: рядок без нарахування дає нуль так само,
		як і виплачений, тож автоматичне «Виплачено» ховало людей, яким ще винні.
		"""
		accrued = [row for row in self.employees if row.salary_slip]

		if not accrued:
			return "Draft"

		if self.status == "Paid" and not self.unpaid_rows():
			return "Paid"

		if self.paid_employees:
			return "Partly Paid"

		return "To Pay"

	def unpaid_rows(self):
		"""Кому ще винні: нарахований рядок із сумою, який не проведений."""
		return [
			row
			for row in self.employees
			if row.salary_slip and (flt(row.salary_card, 2) or flt(row.salary_cash, 2)) and not row.paid
		]

	# --- дії ------------------------------------------------------------------

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

	def bonus_approval(self):
		"""Затверджені премії за цей місяць — без них місяць не рахується і не платиться."""
		return frappe.db.exists(
			"Salary Approval",
			{"company": self.company, "effective_from": self.period_start, "status": "Approved"},
		)

	def validate_salary_approved(self):
		"""Премія — частина нарахування місяця: якщо її ще не затвердили, порахований і
		виплачений місяць довелося б скасовувати й рахувати наново."""
		if self.bonus_approval():
			return

		frappe.throw(
			_("Approve the bonuses for {0} first — there is no approved bonus sheet for {1}.").format(
				formatdate(self.period_start, "MM.yyyy"), self.company
			),
			title=_("Bonuses Not Approved"),
		)

	@frappe.whitelist()
	def mark_paid(self):
		"""Закриває відомість вручну — і тільки коли по кожному рядку гроші вже пішли."""
		unpaid = self.unpaid_rows()

		if unpaid:
			frappe.throw(
				_("{0} employees are not paid yet: {1}").format(
					len(unpaid),
					", ".join([row.employee_name or row.employee for row in unpaid][:20])
					+ ("…" if len(unpaid) > 20 else ""),
				),
				title=_("The Salary Is Not Paid in Full"),
			)

		if not [row for row in self.employees if row.salary_slip]:
			frappe.throw(_("There is nothing to close: the salary is not accrued yet."))

		self.status = "Paid"
		self.save()

		return self.status

	@frappe.whitelist()
	def pay(self, posting_date=None, employees=None):
		"""Проводить остаточний розрахунок за місяць. Аванс платиться окремим документом.

		`employees` — кого саме платимо. Виплата адресна: гроші йдуть людині, а не документу,
		тож усю відомість одним рухом не закрити.
		"""
		self.validate_salary_approved()

		selected = frappe.parse_json(employees) if isinstance(employees, str) else employees

		if not selected:
			frappe.throw(_("Choose the employee to pay — the salary is paid row by row."))
		targets = [
			row
			for row in self.employees
			if row.salary_slip
			and (flt(row.salary_card, 2) or flt(row.salary_cash, 2))
			and not row.paid
			and (not selected or row.employee in selected)
		]

		if not targets:
			frappe.throw(_("There is nothing left to pay here."))

		posting_date = getdate(posting_date or self.period_end)
		vouchers = []
		payouts = (
			(
				payroll_accounts.bank_account(self.company),
				payroll_accounts.payable_account(self.company),
				_("Salary to cards"),
				"salary_card",
				# Офіційну частину закриваємо по кожному працівнику окремо — саме так її нарахував
				# HRMS, інакше рахунок не зійдеться по контрагентах.
				True,
			),
			(
				payroll_accounts.cash_account(self.company),
				payroll_accounts.cash_payable_account(self.company),
				_("Salary in cash"),
				"salary_cash",
				False,
			),
		)

		for paid_from, paid_to, remark, source, by_party in payouts:
			parties = [(row.employee, flt(row.get(source), 2)) for row in targets if flt(row.get(source), 2)]
			amount = sum(party_amount for _employee, party_amount in parties)

			if not flt(amount, 2):
				continue

			voucher = payroll_accounts.make_journal_entry(
				self.company,
				paid_from,
				paid_to,
				amount,
				posting_date,
				f"{remark} {self.month}.{self.year}",
				parties=parties if by_party else None,
			)
			vouchers.append(voucher)

			# Проведення лишається в рядку: з нього видно, чим саме закрита ця людина.
			for row in targets:
				if flt(row.get(source), 2):
					row.set(f"journal_entry_{source.replace('salary_', '')}", voucher)

		for row in targets:
			row.paid_date = posting_date

		self.save()
		self.refresh_data()

		return vouchers

	# --- рахунки --------------------------------------------------------------

	def payable_account(self):
		return payroll_accounts.payable_account(self.company)

	def bank_account(self):
		return payroll_accounts.bank_account(self.company)
