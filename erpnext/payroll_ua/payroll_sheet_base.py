"""Спільна механіка двох нарахувань зарплати за місяць — офіційного й управлінського.

Документ нічого не зберігає окремо: суми рахуються з картки працівника (офіційна й готівкова
частини) за табелем — тією самою арифметикою, що й «Аванс», — плюс затверджені премія й надбавка,
мінус уже виданий аванс і задаток. Нарахування в HRMS (Payroll Entry) лишається окремою дією і
виплату не блокує: гроші йдуть за відпрацьованими днями, а не за наявністю Salary Slip.

Платіжні дати двох частин різні (офіційна — 1-го, готівкова — 5-6-го), тож і документи різні:
«Нарахування зарплати» платить лише на картку, «Нарахування управлінської зарплати» — лише з
каси. Рахують обидва однаково й по тому самому табелю — різниця лише в тому, яку половину
кожен із них показує підсумками, статусом і кнопкою виплати.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, formatdate, get_last_day, getdate

from erpnext.hr import payroll_accounts, payroll_tax
from erpnext.hr.salary_advance import (
	ADVANCE_CARD,
	ADVANCE_CASH,
	ATTENDANCE_FIELDS,
	plan_month,
)

DEPOSIT_COMPONENT = "Задаток"

CARD = "card"
CASH = "cash"


class PayrollSheetBase(Document):
	"""Половина, яку платить документ, задається спадкоємцем — усе інше в них спільне."""

	part = CARD

	@property
	def amount_field(self):
		return "salary_card" if self.part == CARD else "salary_cash"

	@property
	def pays_officially(self):
		"""Офіційна половина йде через HRMS: нарахування, листок, борг по кожному працівнику."""
		return self.part == CARD

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
		"""Перебудовує таблицю: суми рахуються так само, як в авансі — зі структури й табеля.

		Раніше кожне число читалося з Salary Slip, тож до нарахування відомість показувала нулі
		й платити не давала. Нарахування — окрема дія бухгалтерії (Payroll Entry), а виплата за
		місяць від нього не залежить: гроші йдуть за відпрацьованими днями і затвердженою
		премією, точно як аванс усередині місяця.
		"""
		self.advance_sheet = frappe.db.get_value(
			"Salary Advance", {"company": self.company, "period_start": self.period_start}
		)
		plan = {row.employee: row for row in plan_month(self.company, self.year, self.month)}
		slips = self._slips()
		extras = self._additional_salary()
		advances = self._paid_advance(extras)
		bonuses = self._approved_bonuses()
		# Таблиця будується наново, а сліди виплати живуть лише тут — переносимо їх.
		paid_marks = {
			row.employee: (row.journal_entry_card, row.journal_entry_cash, row.paid_date)
			for row in self.employees
		}

		self.set("employees", [])

		for employee, entry in plan.items():
			slip = slips.get(employee)
			extra = extras.get(employee, {})
			advance = advances.get(employee, {})
			bonus = bonuses.get(employee) or {}
			# Премія й надбавка — частина місяця, а не окрема виплата: премію могли призначити
			# готівкою, тож вона додається до тієї частини, якою її платять.
			bonus_cash = flt(bonus.get("bonus")) if bonus.get("in_cash") else 0
			bonus_card = flt(bonus.get("bonus")) - bonus_cash + flt(bonus.get("allowance"))
			# Офіційна частина (разом із премією на картку) — нарахована сума: з неї утримуються
			# ПДФО і військовий збір, тож на картку йде вже залишок.
			taxes = payroll_tax.split(flt(entry.official, 2) + bonus_card, employee)
			earned_card = taxes.net
			earned_cash = flt(entry.cash, 2) + bonus_cash
			advance_card = flt(advance.get(ADVANCE_CARD))
			advance_cash = flt(advance.get(ADVANCE_CASH))
			deposit = flt(extra.get(DEPOSIT_COMPONENT))

			row = self.append(
				"employees",
				{
					"employee": employee,
					"employee_name": entry.employee_name,
					"department": entry.department,
					"manager": entry.manager,
					"credited_days": flt(entry.credited_days, 2),
					"total_working_days": flt(entry.month_working_days, 2),
					"daily_rate": flt(entry.daily_rate, 2),
					"official_salary": flt(entry.official_salary, 2),
					"cash_salary": flt(entry.cash_salary, 2),
					"earned_official": taxes.gross,
					"taxes_withheld": taxes.withheld,
					"employer_ssc": taxes.ssc,
					"earned_card": earned_card,
					"earned_cash": earned_cash,
					"bonus_amount": flt(bonus.get("bonus")),
					"allowance": flt(bonus.get("allowance")),
					"gross_pay": flt(taxes.gross + earned_cash, 2),
					"advance_card": advance_card,
					"advance_cash": advance_cash,
					"deposit": deposit,
					# Аванс і задаток уже в кишені працівника, тож із залишку вони вираховуються
					# з тієї частини, якою були видані.
					"salary_card": max(flt(earned_card - advance_card - deposit, 2), 0),
					"salary_cash": max(flt(earned_cash - advance_cash, 2), 0),
					"salary_slip": slip and slip.name,
				},
			)

			row.journal_entry_card, row.journal_entry_cash, row.paid_date = paid_marks.get(
				employee, (None, None, None)
			)
			row.paid = 1 if row.paid_date else 0
			# Борг документа — лише його половина: другу половину платить інший документ
			# і в іншу дату.
			row.outstanding = 0 if row.paid else flt(row.get(self.amount_field), 2)
			self._set_attendance(row, entry)

			# Людина без заданого окладу лишається у відомості окремим рядком: інакше вона
			# просто зникає й ніхто не помічає, що картку не заповнили.
			if not flt(row.official_salary) and not flt(row.cash_salary):
				row.note = _("The salary is not set on the employee card")
			elif not flt(entry.credited_days):
				row.note = _("No attendance for the period")
			elif self.pays_officially and not slip:
				row.note = _("Not accrued in HRMS yet — the payout does not wait for it")

		self.set_totals()

	def _paid_advance(self, extras):
		"""Скільки авансу працівник уже отримав на руки.

		З «Авансу» беруться лише проведені рядки: нарахований, але не виплачений аванс із
		залишку вираховувати не можна — людина його ще не бачила. Якщо документа авансу за
		місяць немає, лишається сума відрахувань `Additional Salary`.
		"""
		if not self.advance_sheet:
			return extras

		rows = frappe.get_all(
			"Salary Advance Item",
			filters={"parent": self.advance_sheet, "parenttype": "Salary Advance", "paid": 1},
			fields=["employee", "advance_card", "advance_cash"],
		)

		return {
			row.employee: {
				ADVANCE_CARD: flt(row.advance_card),
				ADVANCE_CASH: flt(row.advance_cash),
			}
			for row in rows
		}

	def _approved_bonuses(self):
		"""Премія й надбавка з затвердженого «Затвердження премій» за цей місяць."""
		approval = frappe.db.get_value(
			"Salary Approval",
			{"company": self.company, "effective_from": self.period_start, "status": "Approved"},
		)

		if not approval:
			return {}

		rows = frappe.get_all(
			"Salary Approval Item",
			filters={"parent": approval, "parenttype": "Salary Approval"},
			fields=["employee", "bonus_amount", "allowance", "pay_bonus_in_cash"],
		)

		return {
			row.employee: {
				"bonus": flt(row.bonus_amount),
				"allowance": flt(row.allowance),
				"in_cash": bool(row.pay_bonus_in_cash),
			}
			for row in rows
		}

	def _set_attendance(self, row, entry):
		"""Розклад табеля за місяць — те саме, що бачить «Аванс», лише за повний період."""
		for field in (*ATTENDANCE_FIELDS, "working_hours"):
			row.set(field, flt(entry.get(field), 2))

	def _slips(self):
		"""Нарахування HRMS — тільки посилання: суми відомість рахує сама, а листок лишається
		в рядку, щоб було видно, чи місяць уже проведений у HRMS."""
		slips = frappe.get_all(
			"Salary Slip",
			filters={
				"company": self.company,
				"docstatus": ["<", 2],
				"start_date": [">=", self.period_start],
				"end_date": ["<=", self.period_end],
			},
			fields=["name", "employee"],
		)

		return {slip.employee: slip for slip in slips}

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

	def set_totals(self):
		self.bonus_approved = 1 if self.bonus_approval() else 0
		self.total_employees = len(self.employees)
		self.employees_without_attendance = len([row for row in self.employees if not row.credited_days])
		self.employees_not_accrued = len(
			[row for row in self.employees if row.credited_days and not row.salary_slip]
		)
		self.employees_without_salary = len([row for row in self.employees if not has_salary(row)])
		self.paid_employees = len([row for row in self.employees if row.paid])

		for field, source in self.total_fields():
			self.set(field, sum(flt(row.get(source)) for row in self.employees))

		self.status = self.derive_status()

	def total_fields(self) -> tuple:
		"""Підсумки шапки — спільні числа місяця плюс ті, що стосуються власної половини."""
		common = (
			("total_credited_days", "credited_days"),
			("total_gross", "gross_pay"),
			("total_outstanding", "outstanding"),
		)

		if self.pays_officially:
			return (
				*common,
				("total_taxes", "taxes_withheld"),
				("total_employer_ssc", "employer_ssc"),
				("total_advance_card", "advance_card"),
				("total_salary_card", "salary_card"),
			)

		return (
			*common,
			("total_advance_cash", "advance_cash"),
			("total_salary_cash", "salary_cash"),
		)

	def derive_status(self):
		"""«Виплачено» ставить бухгалтер кнопкою — сам документ доходить лише до «Частково».

		Нульовий залишок ще не означає закритий місяць: рядок без нарахування дає нуль так само,
		як і виплачений, тож автоматичне «Виплачено» ховало людей, яким ще винні.
		"""
		if not self.employees:
			return "Draft"

		if self.status == "Paid" and not self.unpaid_rows():
			return "Paid"

		if self.paid_employees:
			return "Partly Paid"

		return "To Pay"

	def unpaid_rows(self):
		"""Кому ще винні: рядок із сумою до виплати, який не проведений."""
		return [row for row in self.employees if flt(row.get(self.amount_field), 2) and not row.paid]

	# --- дії ------------------------------------------------------------------

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

		if not self.employees:
			frappe.throw(_("There is nothing to close: the sheet has no employees."))

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
			if flt(row.get(self.amount_field), 2)
			and not row.paid
			and (not selected or row.employee in selected)
		]

		if not targets:
			frappe.throw(_("There is nothing left to pay here."))

		posting_date = getdate(posting_date or self.period_end)
		vouchers = []

		for paid_from, paid_to, remark, source, by_party in self.payouts():
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

	def payouts(self) -> tuple:
		"""Звідки й куди йдуть гроші цього документа — одна половина, один рух."""
		if self.pays_officially:
			return (
				(
					payroll_accounts.bank_account(self.company),
					payroll_accounts.payable_account(self.company),
					_("Salary to cards"),
					"salary_card",
					# Офіційну частину закриваємо по кожному працівнику окремо — саме так її
					# нарахував HRMS, інакше рахунок не зійдеться по контрагентах.
					True,
				),
			)

		return (
			(
				payroll_accounts.cash_account(self.company),
				payroll_accounts.cash_payable_account(self.company),
				_("Salary in cash"),
				"salary_cash",
				False,
			),
		)

	# --- рахунки --------------------------------------------------------------

	def payable_account(self):
		return payroll_accounts.payable_account(self.company)

	def bank_account(self):
		return payroll_accounts.bank_account(self.company)


def has_salary(row) -> bool:
	"""Чи заданий у картці працівника оклад — хоч одна з двох частин."""
	return bool(flt(row.official_salary) or flt(row.cash_salary))
