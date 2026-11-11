"""Випадок лікарняного — один на хворобу, з усіма ЕЛН-продовженнями.

* Середня й відсоток фіксуються на перший день випадку (`sick_rules.calculate`).
* Частина роботодавця (перші дні випадку) платиться зарплатою місяця, коли випадок закрито
  (`sick_rules.employer_pay` у `salary_advance.plan_advance`).
* Частина фонду приходить на рахунок компанії коли завгодно: «Отримано від фонду» записує
  надходження на працівника, «Виплатити частину фонду» платить на картку й проводить податки.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, date_diff, flt, formatdate, getdate, nowdate

from erpnext.hr import payroll_accounts, payroll_tax
from erpnext.hr.salary_advance import _holiday_dates, _holiday_list
from erpnext.payroll_ua import enforcement, sick_rules


class SickLeaveCase(Document):
	def validate(self):
		self.set_period()
		self.validate_overlap()

		if not self.employer_paid_date:
			self.calculate()

		if not flt(self.fund_received_amount):
			self.fund_gross = self.fund_expected
			self._set_fund_taxes()

		self.set_status()

	def on_update(self):
		self.mark_attendance()

	def on_trash(self):
		if self.employer_paid_date or self.je_fund_receipt or self.je_fund_card:
			frappe.throw(_("The sick leave case is already paid — it cannot be deleted."))

	def set_period(self):
		rows = sorted(self.certificates or [], key=lambda row: getdate(row.from_date))

		if not rows:
			frappe.throw(_("Add at least one sick leave certificate (ЕЛН)."))

		previous = None

		for index, row in enumerate(rows, start=1):
			row.idx = index

			if getdate(row.to_date) < getdate(row.from_date):
				frappe.throw(
					_("Certificate {0}: the last day is before the first day.").format(row.eln_number)
				)

			row.days = date_diff(row.to_date, row.from_date) + 1

			if previous and getdate(row.from_date) != add_days(previous.to_date, 1):
				frappe.throw(
					_(
						"Certificate {0} does not continue {1}: a continuation starts the day after the previous one ends. A gap means a new sick leave case."
					).format(row.eln_number, previous.eln_number)
				)

			previous = row

		self.certificates = rows
		self.start_date = getdate(rows[0].from_date)
		self.end_date = getdate(rows[-1].to_date)
		self.calendar_days = date_diff(self.end_date, self.start_date) + 1

	def validate_overlap(self):
		other = frappe.db.get_value(
			"Sick Leave Case",
			{
				"employee": self.employee,
				"name": ("!=", self.name or ""),
				"start_date": ("<=", self.end_date),
				"end_date": (">=", self.start_date),
			},
		)

		if other:
			frappe.throw(_("These days are already in sick leave case {0}.").format(other))

	def employee_doc(self):
		return frappe.get_cached_doc("Employee", self.employee).as_dict()

	def calculate(self):
		employee = frappe._dict(self.employee_doc())
		result = sick_rules.calculate(employee, self.case_type, self.start_date, self.calendar_days)
		average = result.average

		self.insurance_years = result.record.years
		self.insurance_months = result.record.months
		self.percent = result.percent
		self.percent_reason = result.percent_reason
		self.average_daily = average.average
		self.daily_pay = result.daily_pay
		self.average_note = self._average_note(average)
		self.employer_days = result.employer_days
		self.fund_days = result.fund_days
		self.employer_gross = result.employer.gross
		self.employer_withheld = result.employer.withheld
		self.employer_net = result.employer.net
		self.employer_ssc = result.employer.ssc
		self.fund_expected = result.fund.gross

	def _average_note(self, average) -> str:
		lines = []

		if average.from_salary:
			lines.append(_("No earnings in the calculation period — taken from the official salary."))
		elif average.period_start:
			lines.append(
				_("{0} – {1}: earnings {2} over {3} days.").format(
					formatdate(average.period_start),
					formatdate(average.period_end),
					frappe.format(average.earnings, {"fieldtype": "Currency"}),
					average.days,
				)
			)

		if average.capped == "max_base":
			lines.append(
				_("Capped by the maximum SSC base: {0} a day instead of {1}.").format(
					average.limit, average.uncapped
				)
			)
		elif average.capped == "short_tenure":
			lines.append(
				_(
					"Insurance record under 6 months: capped by the minimum wage, {0} a day instead of {1}."
				).format(average.limit, average.uncapped)
			)

		return "\n".join(lines)

	def _set_fund_taxes(self):
		taxes = payroll_tax.split(flt(self.fund_gross), self.employee)
		self.fund_withheld = taxes.withheld
		self.fund_net = taxes.net
		self.fund_ssc = taxes.ssc

	def set_status(self):
		if self.fund_paid_date:
			self.status = "Paid"
		elif self.je_fund_receipt:
			self.status = "Fund Received"
		elif self.employer_paid_date or (self.closed and not self.employer_days):
			self.status = "Paid" if not self.fund_days else "Employer Paid"
		elif self.closed:
			self.status = "Closed"
		else:
			self.status = "Open"

	def mark_attendance(self):
		"""Проставляє «Лікарняний» у табелі на робочі дні випадку, де відмітки ще немає."""
		employee = frappe.get_cached_doc("Employee", self.employee)
		holidays = _holiday_dates(_holiday_list(employee, self.company), self.start_date, self.end_date, {})
		last = min(getdate(self.end_date), getdate(nowdate()))
		existing = {
			getdate(row.attendance_date): row.status
			for row in frappe.get_all(
				"Attendance",
				filters={
					"employee": self.employee,
					"docstatus": ("!=", 2),
					"attendance_date": ("between", [self.start_date, self.end_date]),
				},
				fields=["attendance_date", "status"],
			)
		}
		conflicts = []
		day = getdate(self.start_date)

		while day <= last:
			if day not in holidays:
				status = existing.get(day)

				if status is None:
					attendance = frappe.new_doc("Attendance")
					attendance.employee = self.employee
					attendance.company = self.company
					attendance.attendance_date = day
					attendance.status = "Sick Leave"
					attendance.flags.ignore_permissions = True
					attendance.insert()
					attendance.submit()
				elif status != "Sick Leave":
					conflicts.append(formatdate(day))

			day = add_days(day, 1)

		note = _("Attendance shows another status on: {0}.").format(", ".join(conflicts)) if conflicts else ""

		if (self.note or "") != note:
			self.db_set("note", note, update_modified=False)

	@frappe.whitelist()
	def receive_fund(self, posting_date=None, amount=None):
		"""Гроші від фонду прийшли на рахунок компанії — записуємо їх у борг перед працівником."""
		frappe.has_permission("Sick Leave Case", "write", doc=self, throw=True)

		if not self.fund_days:
			frappe.throw(_("The fund pays nothing in this case."))

		if self.je_fund_receipt:
			frappe.throw(_("The money from the fund is already recorded."))

		amount = flt(amount or self.fund_expected, 2)

		if amount <= 0:
			frappe.throw(_("Enter the amount received from the fund."))

		posting_date = getdate(posting_date or nowdate())
		payable = payroll_accounts.payable_account(self.company)
		bank = payroll_accounts.bank_account(self.company)

		if not payable or not bank:
			frappe.throw(_("Set the payroll accounts for company {0} first.").format(self.company))

		remark = _("Sick pay from the fund, {0}, {1}").format(self.employee_name or self.employee, self.name)
		entry = frappe.new_doc("Journal Entry")
		entry.voucher_type = "Bank Entry"
		entry.company = self.company
		entry.posting_date = posting_date
		entry.cheque_no = self.name
		entry.cheque_date = posting_date
		entry.user_remark = remark
		entry.append("accounts", {"account": bank, "debit_in_account_currency": amount})
		entry.append(
			"accounts",
			{
				"account": payable,
				"party_type": "Employee",
				"party": self.employee,
				"credit_in_account_currency": amount,
			},
		)
		entry.insert()
		entry.submit()

		self.fund_received_amount = amount
		self.fund_received_date = posting_date
		self.je_fund_receipt = entry.name
		self.fund_gross = amount
		self._set_fund_taxes()

		if flt(amount - flt(self.fund_expected), 2):
			self.add_comment(
				"Info",
				_("The fund paid {0}, the calculation expected {1}.").format(amount, self.fund_expected),
			)

		self.save()

		return entry.name

	@frappe.whitelist()
	def pay_fund(self, posting_date=None):
		"""Виплачує працівнику отримане від фонду: на картку — без податків, податки — окремо."""
		frappe.has_permission("Sick Leave Case", "write", doc=self, throw=True)

		if not self.je_fund_receipt:
			frappe.throw(_("Record the money from the fund first."))

		if self.fund_paid_date:
			frappe.throw(_("The fund part is already paid."))

		posting_date = getdate(posting_date or nowdate())
		taxes = payroll_tax.split(flt(self.fund_gross), self.employee)
		# Виконавчі документи утримуються й з лікарняних, але не з допомоги у зв'язку з
		# вагітністю та пологами (ст. 73 Закону «Про виконавче провадження»).
		items = (
			[]
			if self.case_type == "Maternity"
			else enforcement.calculate(self.employee, self.company, taxes.net, posting_date)
		)
		enforcement.check_account(self.company, items)
		self.fund_enforcement = enforcement.total(items)
		to_card = flt(taxes.net - self.fund_enforcement, 2)
		card = payroll_accounts.make_journal_entry(
			self.company,
			payroll_accounts.bank_account(self.company),
			payroll_accounts.payable_account(self.company),
			to_card,
			posting_date,
			_("Sick pay (fund part) {0}").format(self.name),
			parties=[(self.employee, to_card)],
		)
		enforcement.post(
			self.company,
			self.employee,
			items,
			posting_date,
			payroll_accounts.payable_account(self.company),
			self.doctype,
			self.name,
			base=taxes.net,
		)
		tax = payroll_accounts.make_tax_entry(
			self.company,
			posting_date,
			_("Taxes on the sick pay (fund part) {0}").format(self.name),
			pit=taxes.pit,
			military=taxes.military,
			ssc=taxes.ssc,
		)

		self.fund_paid_date = posting_date
		self.je_fund_card = card
		self.je_fund_tax = tax
		self.save()

		return [card, tax]


@frappe.whitelist()
def find_unregistered(company):
	"""Дні «Лікарняного» в табелі, яких немає в жодному випадку, — готові чернетки випадків."""
	frappe.has_permission("Sick Leave Case", "create", throw=True)

	rows = frappe.get_all(
		"Attendance",
		filters={"company": company, "docstatus": 1, "status": "Sick Leave"},
		fields=["employee", "employee_name", "attendance_date"],
		order_by="employee asc, attendance_date asc",
	)
	cases = frappe.get_all(
		"Sick Leave Case",
		filters={"company": company},
		fields=["employee", "start_date", "end_date"],
	)
	covered = {}

	for case in cases:
		covered.setdefault(case.employee, []).append((getdate(case.start_date), getdate(case.end_date)))

	runs = []
	cache = {}

	for row in rows:
		day = getdate(row.attendance_date)

		if any(start <= day <= end for start, end in covered.get(row.employee, [])):
			continue

		last = runs[-1] if runs else None

		if (
			last
			and last.employee == row.employee
			and _continues(last.to_date, day, row.employee, company, cache)
		):
			last.to_date = day
			continue

		runs.append(
			frappe._dict(employee=row.employee, employee_name=row.employee_name, from_date=day, to_date=day)
		)

	created = []

	for run in runs:
		case = frappe.new_doc("Sick Leave Case")
		case.employee = run.employee
		case.company = company
		case.append(
			"certificates",
			{"eln_number": _("Not entered"), "from_date": run.from_date, "to_date": run.to_date},
		)
		case.insert()
		created.append(case.name)

	return created


def _continues(previous, day, employee, company, cache) -> bool:
	"""Чи день продовжує той самий випадок: між ними лише вихідні."""
	if date_diff(day, previous) == 1:
		return True

	holidays = _holiday_dates(
		_holiday_list(frappe.get_cached_doc("Employee", employee), company), previous, day, cache
	)
	gap = previous

	while True:
		gap = add_days(gap, 1)

		if getdate(gap) >= day:
			return True

		if getdate(gap) not in holidays:
			return False
