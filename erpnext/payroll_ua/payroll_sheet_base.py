"""Спільна механіка двох нарахувань зарплати за місяць — офіційного й управлінського.

Документ нічого не зберігає окремо: суми рахуються з картки працівника (офіційна й готівкова
частини) за оплачуваними днями — тією самою арифметикою, що й «Аванс», — плюс затверджені премія
й надбавка, мінус уже виданий аванс і задаток. Оплачувані дні рахуються за календарем: робочі дні
місяця мінус неоплачувані відсутності. Нарахування в HRMS (Payroll Entry) лишається окремою дією і
виплату не блокує: гроші йдуть за оплачуваними днями, а не за наявністю Salary Slip.

Платіжні дати двох частин різні (офіційна — 1-го, готівкова — 5-6-го), тож і документи різні:
«Нарахування зарплати» платить лише на картку, «Нарахування управлінської зарплати» — лише з
каси. Рахують обидва однаково й по тому самому табелю — різниця лише в тому, яку половину
кожен із них показує підсумками, статусом і кнопкою виплати.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, formatdate, get_last_day, getdate

from erpnext.hr import payroll_accounts, payroll_tax
from erpnext.hr.salary_advance import (
	ADVANCE_CARD,
	ADVANCE_CASH,
	ATTENDANCE_FIELDS,
	plan_month,
)
from erpnext.payroll_ua.doctype.salary_approval.salary_approval import (
	get_coverage,
	missing_attendance_note,
)

DEPOSIT_COMPONENT = "Задаток"

# Ключі для днів і нарахованого авансу в мапі виплат — поряд із назвами компонентів,
# але компонентами не є.
ADVANCE_DAYS = "__advance_days"
ADVANCE_OFFICIAL = "__advance_official"

# Чи тримає документ виплату до затвердження премій — вмикається в тій половині,
# якою премії й доплати виплачуються.
REQUIRES_BONUS_APPROVAL = False

CARD = "card"
CASH = "cash"


class PayrollSheetBase(Document):
	"""Половина, яку платить документ, задається спадкоємцем — усе інше в них спільне."""

	part = CARD
	requires_bonus_approval = REQUIRES_BONUS_APPROVAL

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
		місяць від нього не залежить: гроші йдуть за оплачуваними днями і затвердженою премією,
		точно як аванс усередині місяця.

		Оплачувані дні рахуються за календарем — робочі дні мінус неоплачувані відсутності, —
		а не за табелем: обидві виплати того самого місяця мусять іти за одним правилом.
		"""
		self.advance_sheet = frappe.db.get_value(
			"Salary Advance", {"company": self.company, "period_start": self.period_start}
		)
		plan = {row.employee: row for row in plan_month(self.company, self.year, self.month)}
		slips = self._slips()
		extras = self._additional_salary()
		advances = self._paid_advance(extras)
		bonuses = self._approved_bonuses()
		official_paid = self._official_paid()
		debts = self._debt_carried()
		# Таблиця будується наново, а сліди виплати живуть лише тут — переносимо їх.
		paid_marks = {
			row.employee: (
				row.journal_entry_card,
				row.journal_entry_cash,
				row.journal_entry_tax,
				row.paid_date,
			)
			for row in self.employees
		}

		self.set("employees", [])

		for employee, entry in plan.items():
			slip = slips.get(employee)
			extra = extras.get(employee, {})
			advance = advances.get(employee, {})
			bonus = bonuses.get(employee) or {}
			# Премія й надбавка платяться лише готівкою: офіційна половина — це рівно оклад за
			# оплачувані дні, тож «Нараховано ОФ» завжди сходиться з денною ставкою.
			bonus_cash = flt(bonus.get("bonus")) + flt(bonus.get("allowance"))
			# Офіційна частина — нарахована сума: з неї утримуються ПДФО і військовий збір, тож
			# на картку йде вже залишок. Дні беруться ті самі, що й в авансі — за календарем,
			# а не за табелем (див. `plan_month`).
			taxes = payroll_tax.split(flt(entry.paid_official, 2), employee)
			earned_card = taxes.net
			earned_cash = flt(entry.paid_cash, 2) + bonus_cash
			advance_days = flt(advance.get(ADVANCE_DAYS))
			advance_official = flt(advance.get(ADVANCE_OFFICIAL))
			advance_card = flt(advance.get(ADVANCE_CARD))
			advance_cash = flt(advance.get(ADVANCE_CASH))
			deposit = flt(extra.get(DEPOSIT_COMPONENT))
			# Офіційно виплачене може бути більшим за зароблене: аванс видається 15-го, а
			# відпустку без збереження чи прогул проводять пізніше — і тоді людина вже
			# отримала на картку більше, ніж їй належить за оплачувані дні.
			paid_officially = flt(official_paid.get(employee, advance_official), 2)
			overpaid = max(flt(paid_officially - taxes.gross, 2), 0)
			# Утримуємо те, що людина справді отримала на руки — переплата на картку прийшла
			# вже без ПДФО і збору.
			debt_carried = flt(debts.get(employee), 2)
			deduction = flt(payroll_tax.net(overpaid, employee) + debt_carried, 2)
			cash_due = flt(earned_cash - advance_cash - deduction, 2)

			row = self.append(
				"employees",
				{
					"employee": employee,
					"employee_name": entry.employee_name,
					"tax_id": entry.tax_id,
					"department": entry.department,
					"manager": entry.manager,
					"paid_days": flt(entry.paid_days, 2),
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
					"bonus_cash": bonus_cash,
					"allowance": flt(bonus.get("allowance")),
					"gross_pay": flt(taxes.gross + earned_cash, 2),
					"advance_days": advance_days,
					"advance_official": advance_official,
					"advance_card": advance_card,
					"advance_cash": advance_cash,
					"deposit": deposit,
					# Аванс і задаток уже в кишені працівника, тож із залишку вони вираховуються
					# з тієї частини, якою були видані. Податки рахуються із залишку, а не з
					# усього місяця з відніманням чистого авансу: ставка та сама, але так
					# розклад у формі сходиться до копійки.
					"salary_card": max(flt(payroll_tax.net(taxes.gross - advance_official) - deposit, 2), 0),
					"official_paid": paid_officially,
					"official_overpaid": overpaid,
					"cash_deduction": deduction,
					"debt_carried": debt_carried,
					# Готівки може не вистачити на утримання — тоді працівник лишається винним
					# компанії, і борг переходить у наступний місяць (`_debt_carried`).
					"debt_forward": max(flt(-cash_due, 2), 0),
					"salary_cash": max(cash_due, 0),
					"salary_slip": slip and slip.name,
				},
			)

			(
				row.journal_entry_card,
				row.journal_entry_cash,
				row.journal_entry_tax,
				row.paid_date,
			) = paid_marks.get(employee, (None, None, None, None))
			row.paid = 1 if row.paid_date else 0
			# Премії затверджуються документом на весь місяць, але платяться по рядках:
			# людина без рядка в затвердженні лишається незакритою — премію їй могли
			# просто забути проставити.
			row.bonus_approved = 1 if not self.requires_bonus_approval or employee in bonuses else 0
			# Борг документа — лише його половина: другу половину платить інший документ
			# і в іншу дату.
			row.outstanding = 0 if row.paid else flt(row.get(self.amount_field), 2)
			self._set_attendance(row, entry)

			# Людина без заданого окладу лишається у відомості окремим рядком: інакше вона
			# просто зникає й ніхто не помічає, що картку не заповнили.
			if not flt(row.official_salary) and not flt(row.cash_salary):
				row.note = _("The salary is not set on the employee card")
			elif entry.relieving_date and getdate(entry.relieving_date) <= self.period_end:
				# Звільненого видно у відомості останній раз — з датою, щоб було ясно, чому
				# днів менше, ніж у решти.
				row.note = _("Dismissed on {0} — the days are counted up to that date").format(
					formatdate(entry.relieving_date)
				)
			elif not flt(entry.credited_days):
				row.note = _("No attendance for the period")
			elif self.pays_officially and not slip:
				row.note = _("Not accrued in HRMS yet — the payout does not wait for it")

		self.set_attendance_state()
		self.set_totals()

	def set_attendance_state(self):
		"""Місяць платиться тільки по зданому табелю: керівник мусить закрити «Затвердженням
		табеля» кожен день періоду, інакше оплачувані дні рахуються з дірки — відсутності,
		яку ніхто не проставив, у календарі не видно, і людина отримує повний місяць."""
		covered = get_coverage([row.employee for row in self.employees], self.period_start, self.period_end)

		for row in self.employees:
			row.attendance_approved = 1 if covered.get(row.employee) else 0
			row.attendance_note = "" if row.attendance_approved else missing_attendance_note()

	def _official_paid(self):
		"""Скільки кожному вже виплачено офіційно за цей місяць — нарахуванням.

		Поки видано лише аванс, це аванс; після виплати офіційної відомості — увесь місяць
		так, як його порахувала та відомість. Число потрібне готівковій половині: саме з
		нею зводиться переплата, якщо офіційно заплатили більше, ніж людина заробила.
		Офіційна відомість це число рахує сама з власних рядків, тож питати нема кого.
		"""
		if self.pays_officially:
			return {}

		sheet = frappe.db.get_value(
			"Payroll Sheet", {"company": self.company, "period_start": self.period_start}
		)

		if not sheet:
			return {}

		rows = frappe.get_all(
			"Payroll Sheet Item",
			filters={"parent": sheet, "parenttype": "Payroll Sheet"},
			fields=["employee", "paid", "earned_official", "advance_official"],
		)

		return {
			row.employee: flt(row.earned_official) if row.paid else flt(row.advance_official) for row in rows
		}

	def _debt_carried(self):
		"""Борг працівника з минулого місяця — те, чого не покрила його готівка.

		Борг живе лише в готівковій відомості: офіційну частину переплатою не чіпають —
		вона вже пройшла нарахуванням і податками, тож повертається з готівки або
		переноситься далі, поки не набереться чим утримати.
		"""
		if self.pays_officially:
			return {}

		previous = frappe.db.get_value(
			"Management Payroll Sheet",
			{"company": self.company, "period_end": add_days(self.period_start, -1)},
		)

		if not previous:
			return {}

		rows = frappe.get_all(
			"Payroll Sheet Item",
			filters={
				"parent": previous,
				"parenttype": "Management Payroll Sheet",
				"debt_forward": (">", 0),
			},
			fields=["employee", "debt_forward"],
		)

		return {row.employee: flt(row.debt_forward) for row in rows}

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
			fields=["employee", "advance_days", "advance_accrued", "advance_card", "advance_cash"],
		)

		return {
			row.employee: {
				ADVANCE_CARD: flt(row.advance_card),
				ADVANCE_CASH: flt(row.advance_cash),
				# Дні авансу тримаються поруч із сумою: інакше у відомості видно, скільки
				# заплатили, але не за що.
				ADVANCE_DAYS: flt(row.advance_days),
				# Нарахований аванс, до податків: із нього рахується залишок місяця.
				ADVANCE_OFFICIAL: flt(row.advance_accrued),
			}
			for row in rows
		}

	@frappe.whitelist()
	def advance_details(self, employee):
		"""Рядок авансу цього працівника — з чого склалася сума, яку відомість вирахувала.

		Аванс живе окремим документом, а у відомості від нього лишається одне число. Щоб
		бухгалтерія не відкривала другий документ заради перевірки, рядок віддається сюди
		цілком: нарахування, оплачувані дні й те, що пішло на картку.
		"""
		if not self.advance_sheet:
			return None

		row = frappe.db.get_value(
			"Salary Advance Item",
			# Лише виплачений аванс: нарахований, але не виданий, у відомості показувати
			# нічого не має — там стоїть нуль, і розкладу до нього не існує.
			{
				"parent": self.advance_sheet,
				"parenttype": "Salary Advance",
				"employee": employee,
				"paid": 1,
			},
			[
				"advance_days",
				"month_working_days",
				"official_salary",
				"advance_accrued",
				"advance_card",
				"advance_cash",
				"advance_total",
				"paid",
				"paid_on",
			],
			as_dict=True,
		)

		if not row:
			return None

		row.advance = self.advance_sheet

		return row

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
			fields=["employee", "bonus_amount", "allowance"],
		)

		return {
			row.employee: {
				"bonus": flt(row.bonus_amount),
				"allowance": flt(row.allowance),
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
		self.employees_without_attendance = len(
			[row for row in self.employees if not row.attendance_approved]
		)
		self.paid_employees = len([row for row in self.employees if row.paid])
		# Лічильники й підсумки шапки — необов'язкові: документ може їх не показувати, і тоді
		# писати їх нікуди (див. «Нарахування зарплати», де підсумки прибрані з форми).
		self._set_counter(
			"employees_not_accrued",
			len([row for row in self.employees if row.credited_days and not row.salary_slip]),
		)
		self._set_counter(
			"employees_without_salary", len([row for row in self.employees if not has_salary(row)])
		)

		for field, source in self.total_fields():
			self._set_counter(field, sum(flt(row.get(source)) for row in self.employees))

		self.status = self.derive_status()

	def _set_counter(self, field, value):
		if self.meta.has_field(field):
			self.set(field, value)

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

	def validate_salary_approved(self, targets):
		"""Премія — частина нарахування місяця: поки її не затвердили, виплачений місяць
		довелося б скасовувати й рахувати наново.

		Тримає це лише та половина, якою премії й доплати справді платяться (готівкова),
		і тримає порядково: людина із затвердженою премією платиться навіть тоді, коли
		сусідній рядок ще чекає на керівника.
		"""
		if not self.requires_bonus_approval:
			return

		missing = [row for row in targets if not row.bonus_approved]

		if not missing:
			return

		frappe.throw(
			_("The bonuses for {0} are not approved for {1} employees: {2}").format(
				formatdate(self.period_start, "MM.yyyy"),
				len(missing),
				", ".join([row.employee_name or row.employee for row in missing][:20])
				+ ("…" if len(missing) > 20 else ""),
			),
			title=_("Bonuses Not Approved"),
		)

	def validate_attendance_approved(self, targets):
		"""Без зданого табеля гроші не йдуть: суми ще можуть поїхати, а виплату потім
		доведеться скасовувати разом із нарахуванням."""
		missing = [row for row in targets if not row.attendance_approved]

		if not missing:
			return

		frappe.throw(
			_("The attendance sheet for {0} is not approved for {1} employees: {2}").format(
				formatdate(self.period_start, "MM.yyyy"),
				len(missing),
				", ".join([row.employee_name or row.employee for row in missing][:20])
				+ ("…" if len(missing) > 20 else ""),
			),
			title=_("Attendance Sheet Not Approved"),
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

		self.validate_attendance_approved(targets)
		self.validate_salary_approved(targets)

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

		# Податки цієї виплати — окремим проведенням: половина, яка платить готівкою, податків
		# не знає, тож проводить їх лише офіційна (див. `_post_taxes`).
		tax_voucher = self._post_taxes(targets, posting_date)

		if tax_voucher:
			vouchers.append(tax_voucher)

		for row in targets:
			row.paid_date = posting_date

			if tax_voucher:
				row.journal_entry_tax = tax_voucher

		# Нарахування в HRMS — після проведення грошей: половина, яка через HRMS не проходить,
		# нічого тут не робить (див. `after_payment`).
		self.after_payment([row.employee for row in targets])
		self.save()
		self.refresh_data()

		return vouchers

	def _post_taxes(self, targets, posting_date):
		"""Податки з тієї суми, яку саме зараз платимо: нараховане за місяць мінус аванс,
		за ставками кожного працівника."""
		if not self.pays_officially:
			return None

		pit = military = ssc = 0.0

		for row in targets:
			base = flt(flt(row.earned_official) - flt(row.advance_official), 2)

			if base <= 0:
				continue

			taxes = payroll_tax.split(base, row.employee)
			pit += taxes.pit
			military += taxes.military
			ssc += taxes.ssc

		return payroll_accounts.make_tax_entry(
			self.company,
			posting_date,
			_("Taxes on the salary {0}.{1}").format(self.month, self.year),
			pit=pit,
			military=military,
			ssc=ssc,
		)

	def after_payment(self, employees):
		"""Що документ робить у HRMS після виплати. Готівкова половина — нічого."""

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
