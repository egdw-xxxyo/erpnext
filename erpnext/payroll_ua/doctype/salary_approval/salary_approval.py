"""Затвердження ЗП на місяць — умови оплати одним документом, як звикла бухгалтерія.

Документ нічого не рахує «в собі»: при затвердженні дві частини окладу лягають у картку
працівника (а звідти хук `erpnext.hr.salary_split` створює призначення структури), а премія й
надбавка — окремими `Additional Salary` на кінець місяця. Далі все рахує штатний HRMS.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_last_day, getdate

ALLOWANCE_COMPONENT = "Надбавка"
BONUS_COMPONENT = "Премія"


class SalaryApproval(Document):
	def validate(self):
		self.effective_from = getdate(f"{self.year}-{int(self.month):02d}-01")

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

	@frappe.whitelist()
	def load_employees(self):
		"""Тягне активних працівників компанії з поточними сумами з їхніх карток."""
		known = {row.employee for row in self.employees}

		for employee in frappe.get_all(
			"Employee",
			filters={"company": self.company, "status": "Active"},
			fields=[
				"name",
				"employee_name",
				"department",
				"reports_to",
				"custom_official_salary",
				"custom_cash_salary",
			],
			order_by="department asc, employee_name asc",
		):
			if employee.name in known:
				continue

			self.append(
				"employees",
				{
					"employee": employee.name,
					"employee_name": employee.employee_name,
					"department": employee.department,
					"manager": employee.reports_to,
					"official_salary": flt(employee.custom_official_salary),
					"cash_salary": flt(employee.custom_cash_salary),
				},
			)

		self.save()

		return len(self.employees)

	@frappe.whitelist()
	def approve(self):
		"""Розкладає затверджені умови по штатних документах HRMS."""
		if self.status == "Approved":
			frappe.throw(_("This approval has already been applied."))

		payroll_date = get_last_day(self.effective_from)
		applied = {"salary": 0, "bonus": 0, "allowance": 0}

		for row in self.employees:
			if self._apply_salary(row):
				applied["salary"] += 1

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

	def _apply_salary(self, row):
		employee = frappe.get_doc("Employee", row.employee)
		official, cash = flt(row.official_salary), flt(row.cash_salary)

		if (
			flt(employee.get("custom_official_salary")) == official
			and flt(employee.get("custom_cash_salary")) == cash
			and getdate(employee.get("custom_salary_effective_from") or "1900-01-01") == self.effective_from
		):
			return False

		employee.custom_official_salary = official
		employee.custom_cash_salary = cash
		employee.custom_salary_effective_from = self.effective_from
		employee.save()

		return True

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
