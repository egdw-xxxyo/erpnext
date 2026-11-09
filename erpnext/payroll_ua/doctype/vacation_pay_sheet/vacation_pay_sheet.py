"""Відомість відпускних — «взято» і «оплачено офіційно» окремо.

Працівники беруть відпустку частинами, як їм треба, а закон вимагає офіційну виплату блоком
(одна з частин щорічної відпустки — від 14 календарних днів). Тому відомість не платить за
кожною заявкою: вона веде баланс днів і дає оплатити накопичене одним рухом.

* **взято** — календарні дні відпустки з табеля й заявок за весь час (`average_pay.absence_calendar`);
* **оплачено** — дні, відмічені в картці працівника як уже оплачені офіційно (`custom_vacation_paid_opening`),
  плюс дні, оплачені цією відомістю раніше;
* **баланс** — перше мінус друге; оплата закриває найстаріші неоплачені дні (FIFO).

Відпускні рахуються за середньою зарплатою (`average_pay.vacation_average`) на дату початку
оплачуваного блоку, оподатковуються як офіційна зарплата, платяться на картку.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_last_day, getdate, nowdate

from erpnext.hr import average_pay, payroll_accounts, payroll_tax
from erpnext.hr.salary_advance import _holiday_dates, _holiday_list
from erpnext.payroll_ua import vacation_rules

# Далі цієї дати табель не дивимось — відпусток раніше за ERP не буде.
EARLIEST = "2000-01-01"


class VacationPaySheet(Document):
	def before_naming(self):
		self.set_period()

	def validate(self):
		self.set_period()
		self.collect()

	def on_trash(self):
		if any(row.paid for row in self.employees):
			frappe.throw(_("The sheet has paid vacations — it cannot be deleted."))

	def set_period(self):
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
		"""Перебудовує таблицю: виплачені рядки лишаються як є, решта рахується наново."""
		paid_rows = [row for row in self.employees if row.paid]
		previous = {row.employee: row for row in self.employees if not row.paid}
		frozen = {row.employee for row in paid_rows}
		employees = frappe.get_all(
			"Employee",
			filters={"company": self.company, "status": "Active"},
			fields=[
				"name",
				"employee_name",
				"department",
				"holiday_list",
				"date_of_joining",
				"custom_tax_id",
				vacation_rules.OPENING_FIELD,
			],
			order_by="department asc, employee_name asc",
		)
		names = [employee.name for employee in employees]
		holiday_cache = {}
		holiday_lists = {employee.name: _holiday_list(employee, self.company) for employee in employees}
		absences = average_pay.absence_calendar(
			names,
			EARLIEST,
			self.period_end,
			lambda name: _holiday_dates(holiday_lists.get(name), EARLIEST, self.period_end, holiday_cache),
		)
		paid_before = self._paid_through_sheets(names)
		rows = []

		for employee in employees:
			days = sorted((absences.get(employee.name) or {}).get(average_pay.VACATION) or [])
			opening = flt(employee.get(vacation_rules.OPENING_FIELD))
			paid_total = paid_before.get(employee.name, 0)

			if not days:
				continue

			row = self._row(employee, days, opening, paid_total, previous.get(employee.name))

			# Оплачений блок лишається в рядку як було; новий рядок тому ж працівнику — лише
			# коли після нього ще є неоплачені дні.
			if row["unpaid_days"] or employee.name not in frozen:
				rows.append(row)

		self.employees = paid_rows

		for row in rows:
			self.append("employees", row)

		self.employees.sort(key=lambda row: (row.department or "", row.employee_name or "", row.paid or 0))

		for index, row in enumerate(self.employees, start=1):
			row.idx = index

		self.set_totals()

	def _paid_through_sheets(self, employees) -> dict:
		if not employees:
			return {}

		rows = frappe.get_all(
			"Vacation Pay Sheet Item",
			filters={"parenttype": "Vacation Pay Sheet", "employee": ("in", employees), "paid": 1},
			fields=["employee", "pay_days"],
		)
		result = {}

		for row in rows:
			result[row.employee] = result.get(row.employee, 0) + cint(row.pay_days)

		return result

	def _row(self, employee, days, opening, paid_total, previous) -> dict:
		covered = int(opening) + int(paid_total)
		remaining = vacation_rules.split_unpaid(days, covered)
		unpaid = len(remaining)
		earned = vacation_rules.entitled_days(employee.date_of_joining, self.period_end)
		pay_days = self._pay_days(previous, unpaid)
		notes = []

		row = {
			"employee": employee.name,
			"employee_name": employee.employee_name,
			"tax_id": employee.custom_tax_id,
			"department": employee.department,
			"requested_days": len(days),
			"opening_paid_days": opening,
			"sheet_paid_days": paid_total,
			"unpaid_days": unpaid,
			"entitled_days": earned,
			"entitlement_balance": earned - len(days),
			"pay_days": pay_days,
		}

		if earned - len(days) < 0:
			notes.append(_("Taken {0} days, earned by law {1}.").format(len(days), earned))

		if opening > len(days):
			notes.append(_("Marked as paid more days ({0}) than were requested.").format(opening))

		if pay_days:
			first, last = remaining[0], remaining[pay_days - 1]
			average = average_pay.vacation_average(
				frappe._dict(name=employee.name, date_of_joining=employee.date_of_joining), first
			)
			taxes = payroll_tax.split(flt(average * pay_days, 2), employee.name)
			row.update(
				{
					"first_day": first,
					"last_day": last,
					"due_date": vacation_rules.due_date(first),
					"average": average,
					"gross": taxes.gross,
					"withheld": taxes.withheld,
					"net": taxes.net,
					"ssc": taxes.ssc,
				}
			)

			if vacation_rules.is_late(first, nowdate()):
				notes.append(
					_("Late: the vacation pay was due by {0}.").format(vacation_rules.due_date(first))
				)

			if pay_days < vacation_rules.MIN_PART and unpaid > pay_days:
				notes.append(
					_("Law: one part of the vacation is at least {0} days.").format(vacation_rules.MIN_PART)
				)

			if pay_days > vacation_rules.MAX_TOTAL:
				notes.append(_("More than {0} days at once.").format(vacation_rules.MAX_TOTAL))

		row["note"] = "\n".join(notes)

		return row

	def _pay_days(self, previous, unpaid) -> int:
		"""Скільки днів платити зараз: вибір людини зберігається, поки не з'явилися нові дні."""
		if previous is None or cint(previous.pay_days) == cint(previous.unpaid_days):
			return unpaid

		return max(min(cint(previous.pay_days), unpaid), 0)

	def set_totals(self):
		rows = self.employees
		self.total_employees = len(rows)
		self.paid_employees = len([row for row in rows if row.paid])
		payable = [row for row in rows if row.paid or cint(row.pay_days) > 0]

		if not payable:
			self.status = "Draft"
		elif all(row.paid for row in payable):
			self.status = "Paid"
		elif self.paid_employees:
			self.status = "Partly Paid"
		else:
			self.status = "To Pay"

	@frappe.whitelist()
	def set_opening(self, employee, days):
		"""Скільки днів відпустки працівнику вже оплачено офіційно — швидка міграція."""
		frappe.has_permission("Employee", "write", throw=True)
		days = flt(days)

		if days < 0:
			frappe.throw(_("The days already paid cannot be negative."))

		frappe.db.set_value("Employee", employee, vacation_rules.OPENING_FIELD, days)

		return self.refresh_data()

	@frappe.whitelist()
	def set_pay_days(self, employee, days):
		"""Скільки днів із балансу платити зараз цьому працівнику."""
		row = next((row for row in self.employees if row.employee == employee and not row.paid), None)

		if not row:
			frappe.throw(_("{0} has nothing to change here.").format(employee))

		days = cint(days)

		if days < 0 or days > cint(row.unpaid_days):
			frappe.throw(_("Choose from 0 to {0} days.").format(cint(row.unpaid_days)))

		row.pay_days = days

		return self.refresh_data()

	@frappe.whitelist()
	def pay(self, posting_date=None, employees=None):
		"""Нараховує й виплачує обрані блоки: нарахування, виплата на картку, податки."""
		selected = frappe.parse_json(employees) if isinstance(employees, str) else employees

		if not selected:
			frappe.throw(_("Choose the employee to pay — the vacation is paid row by row."))

		targets = [
			row
			for row in self.employees
			if not row.paid and row.employee in selected and cint(row.pay_days) > 0
		]

		if not targets:
			frappe.throw(_("There is nothing left to pay here."))

		for row in targets:
			if cint(row.pay_days) > cint(row.unpaid_days):
				frappe.throw(
					_("{0}: {1} days to pay, only {2} unpaid.").format(
						row.employee_name or row.employee, cint(row.pay_days), cint(row.unpaid_days)
					)
				)

		posting_date = getdate(posting_date or nowdate())
		remark = _("Vacation pay {0}.{1}").format(self.month, self.year)
		accrual = self._post_accrual(targets, posting_date, remark)
		card = payroll_accounts.make_journal_entry(
			self.company,
			payroll_accounts.bank_account(self.company),
			payroll_accounts.payable_account(self.company),
			sum(flt(row.net) for row in targets),
			posting_date,
			remark,
			parties=[(row.employee, flt(row.net, 2)) for row in targets],
		)
		taxes = [payroll_tax.split(row.gross, row.employee) for row in targets]
		tax = payroll_accounts.make_tax_entry(
			self.company,
			posting_date,
			_("Taxes on the vacation pay {0}.{1}").format(self.month, self.year),
			pit=sum(item.pit for item in taxes),
			military=sum(item.military for item in taxes),
			ssc=sum(item.ssc for item in taxes),
		)

		for row in targets:
			row.paid = 1
			row.paid_date = posting_date
			row.journal_entry_accrual = accrual
			row.journal_entry_card = card
			row.journal_entry_tax = tax

		self.set_totals()
		self.save()
		self.refresh_data()

		return [accrual, card, tax]

	def _post_accrual(self, targets, posting_date, remark) -> str:
		"""Нарахування відпускних на кожного працівника: витрати на оплату праці проти зарплатного пасиву."""
		payable = payroll_accounts.payable_account(self.company)
		expense = payroll_accounts.salary_expense_account(self.company)

		if not payable or not expense:
			frappe.throw(_("Set the payroll accounts for company {0} first.").format(self.company))

		entry = frappe.new_doc("Journal Entry")
		entry.voucher_type = "Journal Entry"
		entry.company = self.company
		entry.posting_date = posting_date
		entry.cheque_no = remark
		entry.cheque_date = posting_date
		entry.user_remark = remark
		entry.append(
			"accounts",
			{
				"account": expense,
				"debit_in_account_currency": flt(sum(flt(row.gross) for row in targets), 2),
				"cost_center": frappe.get_cached_value("Company", self.company, "cost_center"),
			},
		)

		for row in targets:
			entry.append(
				"accounts",
				{
					"account": payable,
					"party_type": "Employee",
					"party": row.employee,
					"credit_in_account_currency": flt(row.gross, 2),
				},
			)

		entry.insert()
		entry.submit()

		return entry.name
