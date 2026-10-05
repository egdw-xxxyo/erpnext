"""Зміна окладу з майбутнього місяця (або з поточного, поки не платили аванс).

Оклад не міняється «заднім числом»: документ приймає перше число майбутнього місяця, а
поточний — лише до `CURRENT_MONTH_LAST_DAY` числа і лише поки за цей місяць не виплатили
аванс. Виплачений аванс уже порахований за старим окладом, тож міняти базу після нього
означало б платити місяць двома різними ставками.

Документ живе у два кроки: «Зберегти» лишає чернетку, «Затвердити» кладе оклади в картки
й закриває документ від правок.

Сам документ нічого не рахує: при затвердженні нові суми лягають у картку працівника, а звідти
хук `erpnext.hr.salary_split` створює призначення структури з потрібною датою. Історію окладів
видно у звіті «Історія окладів» і на картці працівника.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, flt, formatdate, get_first_day, get_last_day, getdate, nowdate

from erpnext.hr.payroll_tax import reservation_average_minimum, reservation_minimum
from erpnext.hr.salary_split import (
	apply_salary_to_employee,
	base_salary_parts_on,
	employment_rate,
	has_submitted_slip,
)
from erpnext.hr.team import visible_employees

# До якого числа поточного місяця ще можна змінити оклад із цього ж місяця.
CURRENT_MONTH_LAST_DAY = 14


class SalaryChange(Document):
	def onload(self):
		# Мінімум бронювання живе в налаштуваннях і міняється постановою — форма читає
		# його звідси, щоб не питати сервер на кожен рядок.
		self.set_onload("reservation_minimum", flt(self.reservation_minimum) or reservation_minimum())
		self.set_onload("reservation_average_minimum", reservation_average_minimum())
		self.set_onload("company_others", self.company_others())

	def before_naming(self):
		# `autoname` reads year and month, and it runs before validate.
		self.set_period()

	def validate(self):
		self.validate_not_approved()
		self.set_period()
		self.set_reservation_minimum()
		self.validate_month()
		self.set_current_salary()
		self.set_totals()

	def set_period(self):
		if not self.effective_from:
			frappe.throw(_("Month is required"))

		self.effective_from = getdate(self.effective_from).replace(day=1)
		self.year = self.effective_from.year
		self.month = str(self.effective_from.month)

	def set_reservation_minimum(self):
		"""Мінімум бронювання фіксується документом: постанова його міняє, а затверджена
		зміна має лишитися з тим числом, за яким її погоджували."""
		if not flt(self.reservation_minimum):
			self.reservation_minimum = reservation_minimum()

	def validate_not_approved(self):
		"""Затверджений документ уже в картках працівників — правити його нема куди."""
		if self.is_new() or self.flags.approving:
			return

		if frappe.db.get_value("Salary Change", self.name, "status") == "Approved":
			frappe.throw(
				_("This change is approved — create a new document to change the salary again."),
				title=_("Change Already Approved"),
			)

	def validate_month(self):
		"""Майбутній місяць — завжди; поточний — до 14 числа і поки не платили аванс."""
		if self.status == "Approved":
			return

		month_start = getdate(get_first_day(nowdate()))

		if self.effective_from > month_start:
			return

		if self.effective_from < month_start:
			frappe.throw(
				_("The salary may only be changed from a future month, {0} has already started.").format(
					formatdate(self.effective_from, "MM.yyyy")
				),
				title=_("Month Already Started"),
			)

		if getdate(nowdate()).day > CURRENT_MONTH_LAST_DAY:
			frappe.throw(
				_(
					"The current month may be changed only up to the {0}th — after that the salary changes from the next month."
				).format(CURRENT_MONTH_LAST_DAY),
				title=_("Month Already Started"),
			)

		self.validate_no_paid_advance()

	def validate_no_paid_advance(self):
		"""Аванс за цей місяць уже на руках — він порахований за старим окладом, тож і
		решта місяця має піти за ним."""
		advances = frappe.get_all(
			"Salary Advance",
			filters={"company": self.company, "period_start": self.effective_from, "docstatus": ["<", 2]},
			pluck="name",
		)

		if not advances:
			return

		paid = frappe.get_all(
			"Salary Advance Item",
			filters={"parent": ["in", advances], "parenttype": "Salary Advance", "paid": 1},
			limit=1,
		)

		if not paid:
			return

		frappe.throw(
			_(
				"The advance for {0} is already paid — the salary of this month can no longer be changed."
			).format(formatdate(self.effective_from, "MM.yyyy")),
			title=_("Advance Already Paid"),
		)

	def set_current_salary(self):
		"""Чинний оклад — той, що діє на дату зміни, а не той, що в картці: наперед
		затверджена зміна вже лежить у картці й показала б майбутню суму."""
		cards = employee_cards([row.employee for row in self.employees])
		_month, accrued = accrued_last_month(self.company) if self.company else (None, {})

		for row in self.employees:
			row.current_official, row.current_cash, row.current_bonus = base_salary_parts_on(
				row.employee, self.effective_from
			)
			row.current_total = flt(row.current_official) + flt(row.current_cash)
			card = cards.get(row.employee) or frappe._dict()
			row.reservation_required = card.get("custom_reservation_salary") or 0
			# Новий оклад піде в картку, тож і ставка тут — з картки, а не з минулого місяця.
			row.employment_rate = employment_rate(card)

			# Затверджений документ лишається з тим нарахованим, яке бачив при погодженні.
			if self.status != "Approved":
				row.accrued_last_month = accrued.get(row.employee, 0)

			# Порожній рядок означає «лишити як є», а не «обнулити оклад»: нову суму
			# бухгалтер вводить сам, а доти рядок повторює чинний оклад.
			if not flt(row.new_official) and not flt(row.new_cash):
				row.new_official, row.new_cash = row.current_official, row.current_cash

			if flt(row.new_bonus) < 0:
				frappe.throw(_("Official Bonus cannot be negative."))

			row.new_total = flt(row.new_official) + flt(row.new_cash)
			row.change_amount = flt(row.new_total - row.current_total, 2)
			row.change_percent = (
				flt(row.change_amount / row.current_total * 100, 2) if row.current_total else 0
			)

	def set_totals(self):
		changed = [row for row in self.employees if is_changed(row)]

		self.total_employees = len(self.employees)
		self.employees_changed = len(changed)
		self.total_current = sum(flt(row.current_total) for row in changed)
		self.total_new = sum(flt(row.new_total) for row in changed)
		self.total_change = flt(self.total_new - self.total_current, 2)
		# Критичність підприємства дивиться на середню зарплату всієї компанії, а не одного
		# списку: керівник бачить лише своїх, тож решту компанії додаємо з чинними окладами.
		others = self.company_others()
		listed = [row for row in self.employees if paid_official(row) > 0]
		count = len(listed) + others["count"]
		self.average_salary = (
			flt((sum(paid_official(row) for row in listed) + others["total"]) / count, 2) if count else 0
		)

		# Закон дивиться не на прогноз, а на факт: що нараховано за останній календарний
		# місяць. Затверджений документ лишається з тим числом, яке бачив при погодженні.
		if self.status != "Approved" and self.company:
			accrued = company_accrued_average(self.company)
			self.average_accrued = accrued["average"]
			self.average_accrued_month = accrued["month"]

	def company_others(self) -> dict:
		"""Офіційний заробіток решти компанії за цей місяць — тих, кого в документі немає."""
		if not self.company or not self.effective_from:
			return {"total": 0.0, "count": 0}

		return others_official(self.company, self.effective_from, [row.employee for row in self.employees])

	def validate_no_processed_slip(self, rows):
		"""Місяць із поданим розрахунковим листком уже порахований: нове призначення
		структури туди не стане, і зміна тихо загубилася б."""
		blocked = [
			row.employee_name or row.employee
			for row in rows
			if has_submitted_slip(row.employee, self.effective_from)
		]

		if not blocked:
			return

		frappe.throw(
			_("The salary for {0} is already processed for {1} employees: {2}").format(
				formatdate(self.effective_from, "MM.yyyy"),
				len(blocked),
				", ".join(blocked[:20]) + ("…" if len(blocked) > 20 else ""),
			),
			title=_("Salary Already Processed"),
		)

	@frappe.whitelist()
	def refresh_reservation_minimum(self):
		"""Підтягує чинний мінімум бронювання в чернетку — постанова могла змінити його
		після створення документа."""
		if self.status == "Approved":
			frappe.throw(_("This change has already been applied."))

		self.reservation_minimum = reservation_minimum()
		self.save()

		return self.reservation_minimum

	def visible_employees(self):
		"""Підлеглі поточного користувача — та сама вибірка, що й у табелі та в затвердженні
		премій: оклад міняє той, хто веде людину. Менеджер з персоналу веде оклад будь-кого."""
		return editable_employees(self.company, self.effective_from)

	@frappe.whitelist()
	def load_employees(self):
		"""Тягне активних працівників компанії з окладом, чинним на дату зміни."""
		known = {row.employee for row in self.employees}

		for employee in get_month_employees(
			self.company, self.effective_from, employees=self.visible_employees()
		):
			if employee["employee"] in known:
				continue

			self.append("employees", employee)

		self.save()

		return len(self.employees)

	@frappe.whitelist()
	def approve(self):
		"""Кладе нові оклади в картки працівників — призначення структури створює хук."""
		if self.status == "Approved":
			frappe.throw(_("This change has already been applied."))

		changed = [row for row in self.employees if is_changed(row)]

		if not changed:
			frappe.throw(_("No salary is changed here — the new amounts equal the current ones."))

		self.validate_no_processed_slip(changed)

		applied = 0

		for row in changed:
			if apply_salary_to_employee(
				row.employee, row.new_official, row.new_cash, self.effective_from, bonus=flt(row.new_bonus)
			):
				applied += 1

		self.status = "Approved"
		self.flags.approving = True
		self.save()

		return applied


def paid_official(row) -> float:
	"""Що людині справді нарахують офіційно: оклад на її ставці плюс доплата місяця."""
	return flt(
		flt(row.get("new_official")) * (flt(row.get("employment_rate")) or 1) + flt(row.get("new_bonus")), 2
	)


def others_official(company: str, effective_from, listed: list[str]) -> dict:
	"""Сума офіційного заробітку й кількість працівників компанії поза списком `listed`.

	Працівник без офіційного окладу в середню не входить: офіційно йому нічого не
	нараховують, і він лише занизив би її.
	"""
	listed = set(listed)
	total, count = 0.0, 0

	for row in get_month_employees(company, effective_from):
		if row["employee"] in listed:
			continue

		amount = paid_official(row)

		if amount > 0:
			total += amount
			count += 1

	return {"total": flt(total, 2), "count": count}


@frappe.whitelist()
def get_company_others(company: str, effective_from: str, employees: str | list | None = None) -> dict:
	"""Те саме для нового документа, який сервер ще не завантажував. Віддає лише суму й
	кількість — чужих окладів керівник звідси не побачить."""
	frappe.has_permission("Salary Change", throw=True)

	return others_official(company, effective_from, frappe.parse_json(employees) or [])


def accrued_last_month(company: str, on_date=None) -> tuple:
	"""Офіційно нараховане кожному за останній календарний місяць: (місяць, {працівник: сума}).

	Закон перевіряє не оклад, а нараховане: людина з лікарняним чи днями без збереження
	отримує менше окладу й може випасти з бронювання, хоч оклад у неї й достатній. Береться
	з «Нарахування зарплати» цього місяця; поки його немає — порожньо.
	"""
	month = getdate(add_months(getdate(on_date or nowdate()).replace(day=1), -1))
	sheet = frappe.db.get_value(
		"Payroll Sheet", {"company": company, "period_start": month, "docstatus": ("<", 2)}
	)

	if not sheet:
		return month, {}

	rows = frappe.get_all(
		"Payroll Sheet Item",
		filters={"parent": sheet, "parenttype": "Payroll Sheet", "earned_official": (">", 0)},
		fields=["employee", "earned_official"],
	)

	return month, {row.employee: flt(row.earned_official) for row in rows}


def company_accrued_average(company: str, on_date=None) -> dict:
	"""Середня нарахована офіційна зарплата компанії за останній календарний місяць.

	Саме її вимагає постанова № 76 для критичності: фонд нарахованої зарплати місяця, що
	передує поданню, поділений на кількість працівників, яким нараховано.
	"""
	month, amounts = accrued_last_month(company, on_date)

	return {
		"month": month,
		"average": flt(sum(amounts.values()) / len(amounts), 2) if amounts else 0.0,
		"count": len(amounts),
	}


@frappe.whitelist()
def get_employee_accrued(employee: str) -> dict:
	"""Нараховане працівникові за останній місяць — для попередження в його картці."""
	frappe.has_permission("Employee", "read", employee, throw=True)

	month, amounts = accrued_last_month(frappe.db.get_value("Employee", employee, "company"))

	return {"month": month, "amount": amounts.get(employee, 0.0)}


def is_changed(row) -> bool:
	return (
		flt(row.new_official) != flt(row.current_official)
		or flt(row.new_cash) != flt(row.current_cash)
		or flt(row.new_bonus) != flt(row.current_bonus)
	)


def employee_cards(employees: list[str]) -> dict:
	"""Що рядок бере з картки працівника: позначку бронювання й ставку зайнятості."""
	if not employees:
		return {}

	rows = frappe.get_all(
		"Employee",
		filters={"name": ["in", employees]},
		fields=["name", "custom_reservation_salary", "employment_type", "custom_employment_rate"],
	)

	return {row.name: row for row in rows}


@frappe.whitelist()
def get_employees(company: str, effective_from: str) -> list[dict]:
	"""Список працівників для нового документа — форма тягне його сама, без кнопки."""
	frappe.has_permission("Salary Change", throw=True)

	return get_month_employees(company, effective_from, employees=editable_employees(company, effective_from))


def editable_employees(company: str, effective_from) -> list[str] | None:
	"""Чиї оклади користувач може міняти: керівник — своїх підлеглих, менеджер з персоналу —
	усієї компанії (`None`), як і в картці працівника (`salary_split.restrict_salary_editing`)."""
	if "HR Manager" in frappe.get_roles():
		return None

	period_start = getdate(effective_from).replace(day=1)

	return visible_employees(company, period_start, get_last_day(period_start))


def get_month_employees(company: str, effective_from, employees: list[str] | None = None) -> list[dict]:
	"""Ті самі люди, що й в авансі та відомості за цей місяць.

	Правило одне на всі зарплатні документи: компанія, працював хоч день у місяці —
	зокрема прийнятий усередині місяця й звільнений усередині місяця. Раніше список брав
	лише `Active` без дат, тож у зміну окладу потрапляв той, хто ще не вийшов на роботу,
	і не потрапляв той, кого звільняють наприкінці місяця.
	"""
	period_start = getdate(effective_from).replace(day=1)
	period_end = get_last_day(period_start)
	# `employees` — кого саме тягнути; `None` означає всю компанію (виклик без керівника).
	if employees is not None and not employees:
		return []

	scope = [
		["company", "=", company],
		["status", "in", ["Active", "Left"]],
		["date_of_joining", "<=", period_end],
	]

	if employees is not None:
		scope.append(["name", "in", employees])

	_month, accrued = accrued_last_month(company)
	employees = frappe.get_all(
		"Employee",
		filters=scope,
		or_filters=[
			["relieving_date", "is", "not set"],
			["relieving_date", ">=", period_start],
		],
		fields=[
			"name",
			"employee_name",
			"department",
			"reports_to",
			"custom_reservation_salary",
			"employment_type",
			"custom_employment_rate",
		],
		order_by="department asc, employee_name asc",
	)

	rows = []

	for employee in employees:
		official, cash, bonus = base_salary_parts_on(employee.name, effective_from)
		rows.append(
			{
				"employee": employee.name,
				"employee_name": employee.employee_name,
				"department": employee.department,
				"manager": employee.reports_to,
				"reservation_required": employee.custom_reservation_salary or 0,
				"employment_rate": employment_rate(employee),
				"accrued_last_month": accrued.get(employee.name, 0),
				"current_official": official,
				"current_cash": cash,
				"current_bonus": bonus,
				"current_total": official + cash,
				"new_official": official,
				"new_cash": cash,
				"new_bonus": bonus,
				"new_total": official + cash,
			}
		)

	return rows
