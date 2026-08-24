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
from frappe.utils import flt, getdate

from erpnext.hr import payroll_accounts
from erpnext.hr.salary_advance import (
	ADVANCE_CARD,
	ADVANCE_CASH,
	DEFAULT_CUTOFF_DAY,
	apply_advance,
	period,
	period_norm,
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

		self.period_working_days = period_norm(self.company, self.year, self.month, self.cutoff_day)[0]
		self.total_employees = len(self.employees)
		self.employees_without_attendance = len(
			[row for row in self.employees if not row.attendance_approved]
		)

		self.status = self.derive_status()

	def derive_status(self):
		"""«Виплачено» — рішення бухгалтера, а не наслідок першого проведення.

		Раніше документ ставав виплаченим, щойно закривався перший працівник, у якого вже було
		відрахування: решта людей ще чекала грошей, а місяць у списку виглядав закритим. Тепер
		статус сам доходить лише до «Частково виплачено», а «Виплачено» ставить `mark_paid`.
		"""
		if any(row.additional_salary_card or row.additional_salary_cash for row in self.employees):
			if self.status == "Paid" and not self.unpaid_rows():
				return "Paid"

			return "Partly Paid" if any(row.paid for row in self.employees) else "To Pay"

		return "Draft"

	def unpaid_rows(self):
		"""Кого ще не закрили — рядок з сумою, який не оплачений."""
		return [row for row in self.employees if flt(row.advance_total, 2) and not row.paid]

	# --- дії ------------------------------------------------------------------

	@frappe.whitelist()
	def calculate(self):
		"""Перебудовує таблицю з табеля: суми рахуються за зарахованими днями."""
		if any(row.additional_salary_card or row.additional_salary_cash for row in self.employees):
			frappe.throw(_("The advance has already been created — cancel it before recalculating."))

		rows = plan_advance(self.company, self.year, self.month, self.cutoff_day)
		self.set("employees", [])

		for row in rows:
			self.append("employees", row_values(row))

		self.save()

		return len(self.employees)

	@frappe.whitelist()
	def create_advance(self, employees=None):
		"""Створює відрахування «Аванс» — після цього суми в таблиці вже не редагуються.

		`employees` — кого саме оформляємо; без нього оформляються всі. Рядок можна провести
		окремо: бухгалтерія закриває людину за людиною, а не весь місяць одним рухом.
		"""
		selected = frappe.parse_json(employees) if isinstance(employees, str) else employees
		targets = [
			row
			for row in self.employees
			if flt(row.advance_total) and (not selected or row.employee in selected)
		]

		if not targets:
			frappe.throw(_("There is nothing to pay: every advance is zero."))

		# Незатверджений табель авансу не блокує: аванс — строкова виплата за КЗпП, і платимо
		# ми його однаково. Стан табеля лишається в рядку (позначка й підказка) як попередження.
		self.validate_structure_assigned(targets)

		rows = [
			{"employee": row.employee, "official": flt(row.advance_card), "cash": flt(row.advance_cash)}
			for row in targets
		]

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
	def pay(self, posting_date=None, employees=None):
		"""Проводить виплату авансу: банк — на картки, каса — готівкою.

		`employees` — кого саме платимо. Виплата завжди адресна: гроші йдуть людині, а не
		документу, тож списком «усі одразу» аванс не закривається.
		"""
		if self.status == "Draft":
			frappe.throw(_("Create the advance first."))

		selected = frappe.parse_json(employees) if isinstance(employees, str) else employees

		if not selected:
			frappe.throw(_("Choose the employee to pay — the advance is paid row by row."))
		targets = [
			row
			for row in self.employees
			if flt(row.advance_total, 2)
			and not row.paid
			and (row.additional_salary_card or row.additional_salary_cash)
			and (not selected or row.employee in selected)
		]

		if not targets:
			frappe.throw(_("There is nothing left to pay here."))

		posting_date = getdate(posting_date or self.payment_date or self.cutoff_date())
		vouchers = []

		paid_to = payroll_accounts.advance_account(self.company)
		# Рахунок авансу зазвичай персональний (розрахунки з працівниками), тож розкладаємо
		# борг по контрагентах — без цього проведення на такий рахунок не збережеться.
		by_party = paid_to and payroll_accounts.requires_party(paid_to)
		payouts = (
			(payroll_accounts.bank_account(self.company), _("Advance to cards"), "advance_card"),
			(payroll_accounts.cash_account(self.company), _("Advance in cash"), "advance_cash"),
		)

		for paid_from, remark, source in payouts:
			parties = [(row.employee, flt(row.get(source), 2)) for row in targets if flt(row.get(source), 2)]
			amount = sum(party_amount for _employee, party_amount in parties)

			if not amount:
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

			# проведення лишається в рядку: з нього видно, чим саме закрита ця людина
			for row in targets:
				if flt(row.get(source), 2):
					row.set(f"journal_entry_{source.replace('advance_', '')}", voucher)

		for row in targets:
			row.paid = 1
			row.paid_on = posting_date

		self.payment_date = posting_date
		self.save()

		return vouchers

	@frappe.whitelist()
	def mark_paid(self):
		"""Закриває документ вручну — і тільки коли по кожному рядку гроші вже пішли."""
		unpaid = self.unpaid_rows()

		if unpaid:
			frappe.throw(
				_("{0} employees are not paid yet: {1}").format(
					len(unpaid),
					", ".join([row.employee_name or row.employee for row in unpaid][:20])
					+ ("…" if len(unpaid) > 20 else ""),
				),
				title=_("The Advance Is Not Paid in Full"),
			)

		if not self.employees:
			frappe.throw(_("There is nothing to close: the advance has no employees."))

		self.status = "Paid"
		self.save()

		return self.status

	@frappe.whitelist()
	def settle(self, posting_date=None, employees=None):
		"""Оформити й виплатити одним рухом — те, що бухгалтер робить у житті одним рішенням.

		Рядок, у якого відрахування ще немає, спершу оформлюється; далі все як у `pay`.
		"""
		selected = frappe.parse_json(employees) if isinstance(employees, str) else employees
		pending = [
			row
			for row in self.employees
			if flt(row.advance_total, 2)
			and not row.paid
			and not (row.additional_salary_card or row.additional_salary_cash)
			and (not selected or row.employee in selected)
		]

		if pending:
			self.create_advance(employees=[row.employee for row in pending])
			self.reload()

		return self.pay(posting_date=posting_date, employees=selected)

	def validate_structure_assigned(self, rows=None):
		"""Без чинного призначення структури HRMS не приймає жодного `Additional Salary`,
		а помилка звідти називає лише перший id — тож перевіряємо самі й одразу списком."""
		assigned = set(
			frappe.get_all(
				"Salary Structure Assignment",
				filters={
					"docstatus": 1,
					"employee": ("in", [row.employee for row in rows or self.employees]),
					"from_date": ("<=", period(self.year, self.month, self.cutoff_day)[1]),
				},
				pluck="employee",
			)
		)
		missing = [
			row.employee_name or row.employee
			for row in rows or self.employees
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


def row_values(row) -> dict:
	"""Рядок таблиці з порахованого — однаково для перерахунку і для нового документа."""
	values = {
		field: row.get(field)
		for field in (
			"employee",
			"employee_name",
			"department",
			"manager",
			"official_salary",
			"cash_salary",
			"month_working_days",
			"planned_days",
			"planned_hours",
			"credited_days",
			"present_days",
			"leave_days",
			"unpaid_leave_days",
			"sick_days",
			"absent_days",
			"half_days",
			"overtime_hours",
			"shortfall_hours",
			"working_hours",
			"daily_rate",
		)
	}
	values["advance_card"] = row.official
	# Готівкову частину за замовчуванням не платимо: у розрахунку вона лише довідкова
	# (`cash_salary`), а суму бухгалтерія вписує руками, коли аванс дійсно дають готівкою.
	values["advance_cash"] = 0

	return values


def missing_attendance_note() -> str:
	return _("The attendance sheet of this employee is not approved for the first half of the month")


@frappe.whitelist()
def get_employees(company: str, period_start: str, cutoff_day: int = DEFAULT_CUTOFF_DAY) -> dict:
	"""Попередній розрахунок для нового документа — форма тягне його сама, без кнопки."""
	frappe.has_permission("Salary Advance", throw=True)

	start = getdate(period_start)
	rows = plan_advance(company, start.year, start.month, int(cutoff_day or DEFAULT_CUTOFF_DAY))
	covered = get_coverage(
		[row.employee for row in rows], start.replace(day=1), period(start.year, start.month, cutoff_day)[2]
	)

	days, hours = period_norm(company, start.year, start.month, int(cutoff_day or DEFAULT_CUTOFF_DAY))
	employees = [
		{
			**row_values(row),
			"advance_total": row.official,
			"attendance_approved": 1 if covered.get(row.employee) else 0,
			"attendance_note": "" if covered.get(row.employee) else missing_attendance_note(),
		}
		for row in rows
	]

	return {"employees": employees, "period_working_days": days, "period_working_hours": hours}


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
