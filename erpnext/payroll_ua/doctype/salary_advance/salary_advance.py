"""Аванс за першу половину місяця — окремий документ, бо платиться в інший строк.

Виплата двічі на місяць — вимога КЗпП, тож аванс не чекає на закриття місяця: він рахується
за відпрацьовані дні з 1-го по день відсікання (за замовчуванням 15-те) і того ж дня
виплачується. Документ нічого не тримає в собі: суми стають `Additional Salary`
(«Аванс на картку» / «Аванс готівкою»), а виплата — `Journal Entry`. У «Зарплатній відомості»
той самий аванс потім видно окремими колонками і він же зменшує остаточний розрахунок.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, formatdate, getdate

from erpnext.hr import payroll_accounts
from erpnext.hr.salary_advance import (
	ADVANCE_CARD,
	ADVANCE_CASH,
	DEFAULT_CUTOFF_DAY,
	apply_advance,
	period,
	plan_advance,
)
from erpnext.payroll_ua.doctype.salary_approval.salary_approval import get_coverage


class SalaryAdvance(Document):
	def before_naming(self):
		# `autoname` reads year and month, and it runs before validate.
		self.set_period()

	def validate(self):
		self.set_period()
		self.set_attendance_state()
		self.set_totals()

	def set_period(self):
		if not self.period_start:
			frappe.throw(_("Month is required"))

		self.period_start = getdate(self.period_start).replace(day=1)
		self.year = self.period_start.year
		self.month = str(self.period_start.month)
		self.cutoff_day = int(self.cutoff_day or DEFAULT_CUTOFF_DAY)

		if not 1 <= self.cutoff_day <= 28:
			frappe.throw(_("The cut-off day must be between 1 and 28."))

		if not self.payment_date:
			self.payment_date = self.cutoff_date()

	def cutoff_date(self):
		return period(self.year, self.month, self.cutoff_day)[2]

	def set_attendance_state(self):
		"""Аванс платиться серед місяця, тож табель має бути затверджений лише по день
		відсікання — цілий місяць на 15-те закрити ніхто не може."""
		covered = get_coverage(
			[row.employee for row in self.employees], self.period_start, self.cutoff_date()
		)

		for row in self.employees:
			row.attendance_approved = 1 if covered.get(row.employee) else 0
			row.attendance_note = "" if row.attendance_approved else missing_attendance_note()

	def set_totals(self):
		for row in self.employees:
			row.advance_total = flt(row.advance_card) + flt(row.advance_cash)

		self.total_employees = len(self.employees)
		self.employees_without_attendance = len(
			[row for row in self.employees if not row.attendance_approved]
		)

		for field, source in (
			("total_credited_days", "credited_days"),
			("total_advance_card", "advance_card"),
			("total_advance_cash", "advance_cash"),
			("total_advance", "advance_total"),
		):
			self.set(field, sum(flt(row.get(source)) for row in self.employees))

		self.status = self.derive_status()

	def derive_status(self):
		if self.employees and all(row.paid for row in self.employees):
			return "Paid"

		if any(row.additional_salary_card or row.additional_salary_cash for row in self.employees):
			return "To Pay"

		return "Draft"

	# --- дії ------------------------------------------------------------------

	@frappe.whitelist()
	def calculate(self):
		"""Перебудовує таблицю з табеля: суми рахуються за зарахованими днями."""
		if self.status != "Draft":
			frappe.throw(_("The advance has already been created — cancel it before recalculating."))

		rows = plan_advance(self.company, self.year, self.month, self.cutoff_day)
		self.set("employees", [])

		for row in rows:
			self.append(
				"employees",
				{
					"employee": row.employee,
					"employee_name": row.employee_name,
					"department": row.department,
					"manager": row.manager,
					"official_salary": row.official_salary,
					"cash_salary": row.cash_salary,
					"month_working_days": row.month_working_days,
					"planned_days": row.planned_days,
					"credited_days": row.credited_days,
					"daily_rate": row.daily_rate,
					"advance_card": row.official,
					"advance_cash": row.cash,
				},
			)

		self.save()

		return len(self.employees)

	@frappe.whitelist()
	def create_advance(self):
		"""Створює відрахування «Аванс» — після цього суми в таблиці вже не редагуються."""
		self.validate_attendance_approved()
		self.validate_structure_assigned()

		rows = [
			{"employee": row.employee, "official": flt(row.advance_card), "cash": flt(row.advance_cash)}
			for row in self.employees
			if flt(row.advance_total)
		]

		if not rows:
			frappe.throw(_("There is nothing to pay: every advance is zero."))

		apply_advance(self.company, self.year, self.month, rows)
		self.link_additional_salary()
		self.save()

		return len(rows)

	def link_additional_salary(self):
		"""Підтягує створені відрахування в рядки, щоб з документа було видно, чим саме
		аванс оформлений."""
		payroll_date = period(self.year, self.month, self.cutoff_day)[1]
		existing = frappe.get_all(
			"Additional Salary",
			filters={
				"company": self.company,
				"docstatus": 1,
				"payroll_date": payroll_date,
				"salary_component": ["in", [ADVANCE_CARD, ADVANCE_CASH]],
			},
			fields=["name", "employee", "salary_component", "amount"],
		)
		by_employee = {}

		for row in existing:
			by_employee.setdefault(row.employee, {})[row.salary_component] = row

		for row in self.employees:
			created = by_employee.get(row.employee, {})
			card, cash = created.get(ADVANCE_CARD), created.get(ADVANCE_CASH)
			row.additional_salary_card = card and card.name
			row.additional_salary_cash = cash and cash.name

			# Відрахування — джерело істини: суму могли поправити руками вже в ньому.
			if card:
				row.advance_card = flt(card.amount)
			if cash:
				row.advance_cash = flt(cash.amount)

	@frappe.whitelist()
	def pay(self, posting_date=None):
		"""Проводить виплату авансу: банк — на картки, каса — готівкою."""
		if self.status == "Draft":
			frappe.throw(_("Create the advance first."))

		posting_date = getdate(posting_date or self.payment_date or self.cutoff_date())
		vouchers = []

		paid_to = payroll_accounts.advance_account(self.company)
		# Рахунок авансу зазвичай персональний (розрахунки з працівниками), тож розкладаємо
		# борг по контрагентах — без цього проведення на такий рахунок не збережеться.
		by_party = paid_to and payroll_accounts.requires_party(paid_to)
		payouts = (
			(
				payroll_accounts.bank_account(self.company),
				flt(self.total_advance_card),
				_("Advance to cards"),
				"advance_card",
			),
			(
				payroll_accounts.cash_account(self.company),
				flt(self.total_advance_cash),
				_("Advance in cash"),
				"advance_cash",
			),
		)

		for paid_from, amount, remark, source in payouts:
			if not flt(amount, 2):
				continue

			parties = (
				[(row.employee, flt(row.get(source))) for row in self.employees if flt(row.get(source), 2)]
				if by_party
				else None
			)

			vouchers.append(
				payroll_accounts.make_journal_entry(
					self.company,
					paid_from,
					paid_to,
					amount,
					posting_date,
					f"{remark} {self.month}.{self.year}",
					parties=parties,
				)
			)

		for row in self.employees:
			row.paid = 1 if flt(row.advance_total) else 0

		self.payment_date = posting_date
		self.save()

		return vouchers

	def validate_structure_assigned(self):
		"""Без чинного призначення структури HRMS не приймає жодного `Additional Salary`,
		а помилка звідти називає лише перший id — тож перевіряємо самі й одразу списком."""
		assigned = set(
			frappe.get_all(
				"Salary Structure Assignment",
				filters={
					"docstatus": 1,
					"employee": ("in", [row.employee for row in self.employees]),
					"from_date": ("<=", period(self.year, self.month, self.cutoff_day)[1]),
				},
				pluck="employee",
			)
		)
		missing = [
			row.employee_name or row.employee
			for row in self.employees
			if flt(row.advance_total) and row.employee not in assigned
		]

		if not missing:
			return

		frappe.throw(
			_("{0} employees have no salary structure assigned: {1}").format(
				len(missing), ", ".join(missing[:20]) + ("…" if len(missing) > 20 else "")
			),
			title=_("No Salary Structure"),
		)

	def validate_attendance_approved(self):
		"""Аванс платимо за затверджені дні: поки керівник не здав першу половину місяця,
		дні ще можуть змінитися, а гроші вже пішли б."""
		missing = [row.employee_name or row.employee for row in self.employees if not row.attendance_approved]

		if not missing:
			return

		frappe.throw(
			_("The attendance sheet up to {0} is not approved for {1} employees: {2}").format(
				formatdate(self.cutoff_date(), "dd.MM.yyyy"),
				len(missing),
				", ".join(missing[:20]) + ("…" if len(missing) > 20 else ""),
			),
			title=_("Attendance Sheet Not Approved"),
		)


def missing_attendance_note() -> str:
	return _("The attendance sheet of this employee is not approved for the first half of the month")


@frappe.whitelist()
def get_employees(company: str, period_start: str, cutoff_day: int = DEFAULT_CUTOFF_DAY) -> list[dict]:
	"""Попередній розрахунок для нового документа — форма тягне його сама, без кнопки."""
	frappe.has_permission("Salary Advance", throw=True)

	start = getdate(period_start)
	rows = plan_advance(company, start.year, start.month, int(cutoff_day or DEFAULT_CUTOFF_DAY))
	covered = get_coverage(
		[row.employee for row in rows], start.replace(day=1), period(start.year, start.month, cutoff_day)[2]
	)

	return [
		{
			"employee": row.employee,
			"employee_name": row.employee_name,
			"department": row.department,
			"manager": row.manager,
			"official_salary": row.official_salary,
			"cash_salary": row.cash_salary,
			"month_working_days": row.month_working_days,
			"planned_days": row.planned_days,
			"credited_days": row.credited_days,
			"daily_rate": row.daily_rate,
			"advance_card": row.official,
			"advance_cash": row.cash,
			"advance_total": row.advance_total,
			"attendance_approved": 1 if covered.get(row.employee) else 0,
			"attendance_note": "" if covered.get(row.employee) else missing_attendance_note(),
		}
		for row in rows
	]


def create_monthly_advance():
	"""Щоденний планувальник: у день відсікання готує аванс по кожній компанії.

	Документ створюється чернеткою — гроші сам ніхто не відправляє, бухгалтерія лише
	відкриває готовий розрахунок і натискає «Виплатити».
	"""
	today = getdate()

	if today.day != DEFAULT_CUTOFF_DAY:
		return

	for company in frappe.get_all("Company", pluck="name"):
		period_start = today.replace(day=1)

		if frappe.db.exists("Salary Advance", {"company": company, "period_start": period_start}):
			continue

		try:
			doc = frappe.new_doc("Salary Advance")
			doc.company = company
			doc.period_start = period_start
			doc.cutoff_day = DEFAULT_CUTOFF_DAY
			doc.insert(ignore_permissions=True)
			doc.calculate()
		except Exception:
			frappe.log_error(title=f"Не вдалося підготувати аванс: {company}", message=frappe.get_traceback())
