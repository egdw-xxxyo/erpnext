"""Зміна окладу з майбутнього місяця.

Оклад ніколи не міняється «заднім числом»: документ приймає лише перше число майбутнього
місяця, тож закритий або поточний місяць рахується за тими сумами, за якими його й починали.

Сам документ нічого не рахує: при затвердженні нові суми лягають у картку працівника, а звідти
хук `erpnext.hr.salary_split` створює призначення структури з потрібною датою. Історію окладів
видно у звіті «Історія окладів» і на картці працівника.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, formatdate, get_first_day, get_last_day, getdate, nowdate

from erpnext.hr.payroll_tax import reservation_minimum
from erpnext.hr.salary_split import apply_salary_to_employee, has_submitted_slip, salary_parts_on
from erpnext.hr.team import visible_employees


class SalaryChange(Document):
	def onload(self):
		# Мінімум бронювання живе в налаштуваннях і міняється постановою — форма читає
		# його звідси, щоб не питати сервер на кожен рядок.
		self.set_onload("reservation_minimum", flt(self.reservation_minimum) or reservation_minimum())

	def before_naming(self):
		# `autoname` reads year and month, and it runs before validate.
		self.set_period()

	def validate(self):
		self.set_period()
		self.set_reservation_minimum()
		self.validate_future_month()
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

	def validate_future_month(self):
		"""Поточний місяць уже рахується — оклад можна міняти лише з наступного."""
		if self.status == "Approved":
			return

		if self.effective_from > getdate(get_first_day(nowdate())):
			return

		frappe.throw(
			_("The salary may only be changed from a future month, {0} has already started.").format(
				formatdate(self.effective_from, "MM.yyyy")
			),
			title=_("Month Already Started"),
		)

	def set_current_salary(self):
		"""Чинний оклад — той, що діє на дату зміни, а не той, що в картці: наперед
		затверджена зміна вже лежить у картці й показала б майбутню суму."""
		for row in self.employees:
			row.current_official, row.current_cash = salary_parts_on(row.employee, self.effective_from)
			row.current_total = flt(row.current_official) + flt(row.current_cash)

			# Порожній рядок означає «лишити як є», а не «обнулити оклад»: нову суму
			# бухгалтер вводить сам, а доти рядок повторює чинний оклад.
			if not flt(row.new_official) and not flt(row.new_cash):
				row.new_official, row.new_cash = row.current_official, row.current_cash

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
		премій: оклад міняє той, хто веде людину."""
		period_start = getdate(self.effective_from).replace(day=1)

		return visible_employees(self.company, period_start, get_last_day(period_start))

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
			if apply_salary_to_employee(row.employee, row.new_official, row.new_cash, self.effective_from):
				applied += 1

		self.status = "Approved"
		self.save()

		return applied


def is_changed(row) -> bool:
	return flt(row.new_official) != flt(row.current_official) or flt(row.new_cash) != flt(row.current_cash)


@frappe.whitelist()
def get_employees(company: str, effective_from: str) -> list[dict]:
	"""Список працівників для нового документа — форма тягне його сама, без кнопки."""
	frappe.has_permission("Salary Change", throw=True)

	period_start = getdate(effective_from).replace(day=1)

	return get_month_employees(
		company,
		effective_from,
		employees=visible_employees(company, period_start, get_last_day(period_start)),
	)


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

	employees = frappe.get_all(
		"Employee",
		filters=scope,
		or_filters=[
			["relieving_date", "is", "not set"],
			["relieving_date", ">=", period_start],
		],
		fields=["name", "employee_name", "department", "reports_to"],
		order_by="department asc, employee_name asc",
	)

	rows = []

	for employee in employees:
		official, cash = salary_parts_on(employee.name, effective_from)
		rows.append(
			{
				"employee": employee.name,
				"employee_name": employee.employee_name,
				"department": employee.department,
				"manager": employee.reports_to,
				"current_official": official,
				"current_cash": cash,
				"current_total": official + cash,
				"new_official": official,
				"new_cash": cash,
				"new_total": official + cash,
			}
		)

	return rows
