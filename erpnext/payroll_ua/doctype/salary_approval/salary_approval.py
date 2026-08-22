"""Затвердження премій за місяць — премія й надбавка одним документом.

Оклад тут не змінюється: він приходить із чинного призначення структури і показується лише
як база, з якої рахується відсоток премії. Змінити оклад можна окремим документом
«Зміна окладу» (`Salary Change`), і завжди з майбутнього місяця.

Документ нічого не рахує «в собі»: при затвердженні премія й надбавка стають окремими
`Additional Salary` на кінець місяця, далі все рахує штатний HRMS. Поки премії за місяць не
затверджені, «Зарплатна відомість» не дасть ані нарахувати, ані виплатити.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, date_diff, flt, formatdate, get_last_day, getdate

from erpnext.hr.salary_advance import attendance_summary
from erpnext.hr.salary_split import salary_parts_on

ALLOWANCE_COMPONENT = "Надбавка"
BONUS_COMPONENT = "Премія"


class SalaryApproval(Document):
	def onload(self):
		# Табель живе поза документом і міняється після збереження: рахуємо його при кожному
		# відкритті, інакше вже затверджений документ показував би нулі.
		self.set_attendance_state()

	def before_naming(self):
		# `autoname` reads year and month, and it runs before validate.
		self.set_period()

	def validate(self):
		self.set_period()
		self.set_attendance_state()

		for row in self.employees:
			# Премія — відсоток від повного окладу, обидві частини разом.
			base = flt(row.official_salary) + flt(row.cash_salary)
			row.bonus_amount = flt(base * flt(row.bonus_percent) / 100, 2)
			row.total_salary = base + row.bonus_amount + flt(row.allowance)

		self.total_employees = len(self.employees)

		for field, source in (
			("total_official", "official_salary"),
			("total_cash", "cash_salary"),
			("total_bonus", "bonus_amount"),
			("total_allowance", "allowance"),
			("total_salary", "total_salary"),
		):
			self.set(field, sum(flt(row.get(source)) for row in self.employees))

	def set_period(self):
		"""Період — одне поле-місяць; `year` і `month` лишаються в документі заради
		іменування та сортування, тож тримаємо їх у синхроні з датою."""
		if not self.effective_from:
			frappe.throw(_("Month is required"))

		self.effective_from = getdate(self.effective_from).replace(day=1)
		self.year = self.effective_from.year
		self.month = str(self.effective_from.month)

	def set_attendance_state(self):
		"""Позначає, у кого табель за місяць уже затверджений — рядок без затвердження
		видно в таблиці попередженням, а `approve` на такому документі не спрацює.

		Заразом кладе в рядок сам табель: дні по статусах, зараховані дні й години — щоб
		умови оплати читалися поруч з тим, за що платять.
		"""
		employees = [row.employee for row in self.employees]
		covered = get_attendance_coverage(employees, self.effective_from)
		start, end = month_range(self.effective_from)
		summary = attendance_summary(employees, start, end)

		for row in self.employees:
			row.attendance_approved = 1 if covered.get(row.employee) else 0
			row.attendance_note = "" if row.attendance_approved else missing_attendance_note()
			row.update(summary.get(row.employee) or {})
			# Оклад — не введення, а база премії: беремо той, що діяв у цьому місяці, тож
			# затверджена наперед зміна окладу не зачіпає премію за вже закритий місяць.
			row.official_salary, row.cash_salary = salary_parts_on(row.employee, end)

	@frappe.whitelist()
	def load_employees(self):
		"""Тягне активних працівників компанії з окладом, чинним у цьому місяці."""
		known = {row.employee for row in self.employees}

		for employee in get_month_employees(self.company, self.effective_from):
			if employee["employee"] in known:
				continue

			self.append("employees", employee)

		self.save()

		return len(self.employees)

	@frappe.whitelist()
	def approve(self):
		"""Розкладає затверджені премії й надбавки по штатних документах HRMS."""
		if self.status == "Approved":
			frappe.throw(_("This approval has already been applied."))

		self.validate_attendance_approved()

		payroll_date = get_last_day(self.effective_from)
		applied = {"bonus": 0, "allowance": 0}

		for row in self.employees:
			if flt(row.bonus_amount) and self._make_additional_salary(
				row, BONUS_COMPONENT, row.bonus_amount, payroll_date
			):
				applied["bonus"] += 1

			if flt(row.allowance) and self._make_additional_salary(
				row, ALLOWANCE_COMPONENT, row.allowance, payroll_date
			):
				applied["allowance"] += 1

		self.status = "Approved"
		self.save()

		return applied

	def _make_additional_salary(self, row, component, amount, payroll_date):
		existing = frappe.db.exists(
			"Additional Salary",
			{
				"employee": row.employee,
				"salary_component": component,
				"payroll_date": payroll_date,
				"docstatus": ["<", 2],
			},
		)

		if existing:
			return False

		doc = frappe.get_doc(
			{
				"doctype": "Additional Salary",
				"employee": row.employee,
				"company": self.company,
				"salary_component": component,
				"amount": flt(amount, 2),
				"payroll_date": payroll_date,
				"overwrite_salary_structure_amount": 0,
				"custom_pay_in_cash": 1 if row.pay_bonus_in_cash else 0,
			}
		)
		doc.insert(ignore_permissions=True)
		doc.submit()

		return True

	def validate_attendance_approved(self):
		"""Зарплату рахуємо тільки по затвердженому табелю: поки місяць не закритий
		керівником, суми ще можуть поїхати."""
		missing = [row.employee_name or row.employee for row in self.employees if not row.attendance_approved]

		if not missing:
			return

		frappe.throw(
			_("The attendance sheet for {0} is not approved for {1} employees: {2}").format(
				formatdate(self.effective_from, "MM.yyyy"),
				len(missing),
				", ".join(missing[:20]) + ("…" if len(missing) > 20 else ""),
			),
			title=_("Attendance Sheet Not Approved"),
		)


def month_range(effective_from) -> tuple:
	start = getdate(effective_from).replace(day=1)

	return start, get_last_day(start)


def get_attendance_coverage(employees: list[str], effective_from) -> dict:
	"""Кожен день місяця має входити в поданий «Затвердження табеля» цього працівника."""
	start, end = month_range(effective_from)

	return get_coverage(employees, start, end)


def get_coverage(employees: list[str], start, end) -> dict:
	"""Чи закритий поданими «Затвердженнями табеля» кожен день періоду.

	Період можна закрити кількома документами (керівник здає його частинами), тож рахуємо
	об'єднання днів, а не окремі документи. Аванс питає про першу половину місяця, а
	затвердження ЗП — про місяць цілком.
	"""
	if not employees:
		return {}

	start, end = getdate(start), getdate(end)

	Approval = frappe.qb.DocType("Attendance Sheet Approval")
	Row = frappe.qb.DocType("Attendance Sheet Approval Employee")

	periods = (
		frappe.qb.from_(Approval)
		.join(Row)
		.on(Row.parent == Approval.name)
		.select(Row.employee, Approval.from_date, Approval.to_date)
		.where(
			(Approval.docstatus == 1)
			& (Approval.from_date <= end)
			& (Approval.to_date >= start)
			& (Row.employee.isin(employees))
		)
	).run(as_dict=True)

	days_in_period = {add_days(start, offset) for offset in range(date_diff(end, start) + 1)}
	covered = {}

	for period in periods:
		first = max(getdate(period.from_date), start)
		last = min(getdate(period.to_date), end)
		days = covered.setdefault(period.employee, set())
		days.update(add_days(first, offset) for offset in range(date_diff(last, first) + 1))

	return {employee: covered.get(employee, set()) >= days_in_period for employee in employees}


def missing_attendance_note() -> str:
	return _("The attendance sheet of this employee is not approved for the whole month")


@frappe.whitelist()
def get_employees(company: str, effective_from: str) -> list[dict]:
	"""Список працівників для нового документа — форма тягне його сама, без кнопки."""
	frappe.has_permission("Salary Approval", throw=True)

	return get_month_employees(company, effective_from)


def get_month_employees(company: str, effective_from) -> list[dict]:
	employees = frappe.get_all(
		"Employee",
		filters={"company": company, "status": "Active"},
		fields=["name", "employee_name", "department", "reports_to"],
		order_by="department asc, employee_name asc",
	)

	names = [employee.name for employee in employees]
	covered = get_attendance_coverage(names, effective_from)
	start, end = month_range(effective_from)
	summary = attendance_summary(names, start, end)

	rows = []

	for employee in employees:
		official, cash = salary_parts_on(employee.name, end)
		rows.append(
			{
				**(summary.get(employee.name) or {}),
				"employee": employee.name,
				"employee_name": employee.employee_name,
				"department": employee.department,
				"manager": employee.reports_to,
				"official_salary": official,
				"cash_salary": cash,
				"attendance_approved": 1 if covered.get(employee.name) else 0,
				"attendance_note": "" if covered.get(employee.name) else missing_attendance_note(),
			}
		)

	return rows
