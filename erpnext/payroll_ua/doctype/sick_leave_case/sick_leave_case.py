"""Випадок лікарняного — один ЕЛН у межах «Випадку непрацездатності».

* Середня й відсоток фіксуються на перший день усієї хвороби (`sick_rules.calculate`);
  дні роботодавця — лише ті, що не вичерпали попередні ЕЛН цієї хвороби.
* Частина роботодавця платиться зарплатою місяця, коли випадок проведено
  (`sick_rules.employer_pay` у `salary_advance.plan_advance`).
* Частина фонду приходить на рахунок компанії коли завгодно: «Отримано від фонду» записує
  надходження на працівника, «Виплатити частину фонду» платить на картку й проводить податки.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, date_diff, flt, formatdate, getdate, nowdate

from erpnext.hr import average_pay, payroll_accounts
from erpnext.hr.salary_advance import _holiday_dates, _holiday_list
from erpnext.payroll_ua import enforcement, sick_rules
from erpnext.payroll_ua.doctype.incapacity_case import incapacity_case

SOCIAL_STATUSES = [
	"Not Requested",
	"Requested, Waiting for Money",
	"Money Received, Waiting for Payment",
	"Paid by Social Security",
]


class SickLeaveCase(Document):
	def validate(self):
		if not (self.employee and self.start_date and self.end_date):
			return

		self.set_incapacity_case()
		self.set_period()
		self.validate_chain()
		self.validate_not_shortened()
		self.validate_overlap()

		if not self.employer_paid_date:
			self.calculate()

		if not flt(self.fund_received_amount):
			self.fund_gross = self.fund_expected
			self._set_fund_taxes()

		self.set_status()
		self.set_limit_warning()

	def set_limit_warning(self):
		year_days = 0

		if self.case_type in sick_rules.ILLNESS_CASE_TYPES and self.start_date:
			year = getdate(self.start_date).year
			others = frappe.get_all(
				"Sick Leave Case",
				filters={
					"employee": self.employee,
					"name": ("!=", self.name or ""),
					"docstatus": ("<", 2),
					"case_type": ("in", sick_rules.ILLNESS_CASE_TYPES),
					"start_date": ("between", [f"{year}-01-01", f"{year}-12-31"]),
				},
				pluck="calendar_days",
			)
			year_days = sum(int(days or 0) for days in others) + int(self.calendar_days or 0)

		self.limit_warning = "\n".join(
			sick_rules.duration_warnings(self.case_type, self.illness_days, year_days)
		)

	def on_update(self):
		self.mark_attendance()
		incapacity_case.refresh(self.incapacity_case)

	def after_delete(self):
		incapacity_case.refresh(self.incapacity_case)

	def before_submit(self):
		if not (self.eln_number or "").strip():
			frappe.throw(
				_("Enter the ЕЛН number: it appears once the ЕЛН is processed in the ПФУ e-services portal."),
				title=_("ЕЛН Number Missing"),
			)

		self.closed = 1
		self.set_status()

	def before_update_after_submit(self):
		self.set_status()

	def on_cancel(self):
		if self.is_paid():
			frappe.throw(_("The sick leave case is already paid — it cannot be cancelled."))

		self.db_set("status", "Cancelled", update_modified=False)
		incapacity_case.refresh(self.incapacity_case)

	def on_trash(self):
		if self.is_paid():
			frappe.throw(_("The sick leave case is already paid — it cannot be deleted."))

	def is_paid(self) -> bool:
		return bool(self.employer_paid_date or self.je_fund_receipt or self.je_fund_card)

	@frappe.whitelist()
	def recalculate(self):
		"""Перераховує випадок за поточними даними працівника (стаж, середня)."""
		frappe.has_permission("Sick Leave Case", "write", doc=self, throw=True)

		if self.docstatus != 0:
			frappe.throw(_("Only a draft case can be recalculated. Cancel and amend it to change it."))

		if self.employer_paid_date:
			frappe.throw(_("The employer part is already paid — the case cannot be recalculated."))

		self.save()

	def set_incapacity_case(self):
		if not self.incapacity_case:
			parent = frappe.new_doc("Incapacity Case")
			parent.employee = self.employee
			parent.company = self.company
			parent.case_type = self.case_type
			parent.start_date = self.start_date
			parent.end_date = self.end_date
			parent.flags.ignore_permissions = True
			parent.insert()
			self.incapacity_case = parent.name

			return

		parent = frappe.db.get_value(
			"Incapacity Case", self.incapacity_case, ["employee", "company", "case_type"], as_dict=True
		)

		if self.employee and parent.employee != self.employee:
			frappe.throw(_("Incapacity case {0} belongs to another employee.").format(self.incapacity_case))

		self.employee = parent.employee
		self.company = parent.company
		self.case_type = parent.case_type

	def set_period(self):
		if getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("The last day is before the first day."))

		self.start_date = getdate(self.start_date)
		self.end_date = getdate(self.end_date)
		self.calendar_days = date_diff(self.end_date, self.start_date) + 1

	def siblings(self) -> list:
		return frappe.get_all(
			"Sick Leave Case",
			filters={
				"incapacity_case": self.incapacity_case,
				"name": ("!=", self.name or ""),
				"docstatus": ("!=", 2),
			},
			fields=["name", "eln_number", "start_date", "end_date"],
			order_by="start_date asc",
		)

	def validate_chain(self):
		"""ЕЛН однієї хвороби йдуть без перерви: наступний починається наступного дня. Перерва —
		це вже новий випадок непрацездатності."""
		rows = sorted(
			[
				*self.siblings(),
				frappe._dict(name=self.name, start_date=self.start_date, end_date=self.end_date),
			],
			key=lambda row: getdate(row.start_date),
		)
		previous = None

		for row in rows:
			if previous and getdate(row.start_date) != getdate(add_days(previous.end_date, 1)):
				frappe.throw(
					_(
						"{0} does not continue {1}: a continuation starts the day after the previous one ends. A gap means a new incapacity case."
					).format(row.name or _("This certificate"), previous.name or _("this certificate"))
				)

			previous = row

		before = [
			row for row in rows if row.name != self.name and getdate(row.end_date) < getdate(self.start_date)
		]
		self.prior_days = sum(date_diff(row.end_date, row.start_date) + 1 for row in before)
		self.illness_days = sum(date_diff(row.end_date, row.start_date) + 1 for row in rows)
		self.illness_start = getdate(rows[0].start_date)

	def validate_not_shortened(self):
		"""Випадок лише росте: його дні вже стоять у табелі «Лікарняним» і заблоковані там,
		тож обрізаний випадок лишив би в табелі лікарняні без причини. Помилкові дні
		прибирає скасування випадку, а не тихе скорочення."""
		before = self.get_doc_before_save()

		if not before or not before.start_date or not before.end_date:
			return

		if getdate(self.start_date) > getdate(before.start_date) or getdate(self.end_date) < getdate(
			before.end_date
		):
			frappe.throw(
				_(
					"A sick leave case cannot be shortened: it covered {0} — {1}, and these days are marked as sick leave in the timesheet. Extend it, or delete the case and mark the days again."
				).format(formatdate(before.start_date), formatdate(before.end_date)),
				title=_("The Case Cannot Be Shortened"),
			)

	def validate_overlap(self):
		other = frappe.db.get_value(
			"Sick Leave Case",
			{
				"employee": self.employee,
				"name": ("!=", self.name or ""),
				"docstatus": ("!=", 2),
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
		result = sick_rules.calculate(
			employee,
			self.case_type,
			self.start_date,
			self.calendar_days,
			illness_start=self.illness_start,
			prior_days=self.prior_days,
			average_period=(self.average_period_start, self.average_period_end),
			average_override=self.average_override,
		)
		average = result.average

		self.insurance_years = result.record.years
		self.insurance_months = result.record.months
		self.percent = result.percent
		self.percent_reason = result.percent_reason
		self.average_calculated = average.calculated
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

		if average.get("overridden"):
			lines.append(
				_("Set by hand per the social security: {0} a day instead of the calculated {1}.").format(
					average.average, average.calculated
				)
			)

		if self.average_period_start:
			lines.append(_("The calculation period was set by hand."))

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
		taxes = sick_rules.taxes(flt(self.fund_gross), self.employee, self.case_type)
		self.fund_withheld = taxes.withheld
		self.fund_net = taxes.net
		self.fund_ssc = taxes.ssc

	def set_status(self):
		if self.docstatus == 2:
			self.status = "Cancelled"
		elif self.fund_paid_date:
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

	def advance_social_status(self, status):
		order = SOCIAL_STATUSES.index
		if order(status) > order(self.social_status or SOCIAL_STATUSES[0]):
			self.social_status = status
			self.social_status_date = nowdate()

	@frappe.whitelist()
	def set_social_status(self, status, status_date=None):
		"""Де заява в соцстрахуванні: не подано, подано й чекаємо гроші, гроші прийшли, виплачено."""
		frappe.has_permission("Sick Leave Case", "write", doc=self, throw=True)

		if status not in SOCIAL_STATUSES:
			frappe.throw(_("Unknown social security status {0}").format(status))

		if self.docstatus == 2:
			frappe.throw(_("The sick leave case is cancelled."))

		self.db_set(
			{"social_status": status, "social_status_date": getdate(status_date or nowdate())},
			update_modified=False,
		)
		self.add_comment("Info", _("Social security status: {0}").format(_(status)))

	@frappe.whitelist()
	def receive_fund(self, posting_date=None, amount=None):
		"""Гроші від фонду прийшли на рахунок компанії — записуємо їх у борг перед працівником."""
		frappe.has_permission("Sick Leave Case", "write", doc=self, throw=True)

		if self.docstatus != 1:
			frappe.throw(_("Submit the sick leave case first."))

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

		self.advance_social_status("Money Received, Waiting for Payment")
		self.save()

		return entry.name

	@frappe.whitelist()
	def pay_fund(self, posting_date=None):
		"""Виплачує працівнику отримане від фонду: на картку — без податків, податки — окремо."""
		frappe.has_permission("Sick Leave Case", "write", doc=self, throw=True)

		if self.docstatus != 1:
			frappe.throw(_("Submit the sick leave case first."))

		if not self.je_fund_receipt:
			frappe.throw(_("Record the money from the fund first."))

		if self.fund_paid_date:
			frappe.throw(_("The fund part is already paid."))

		posting_date = getdate(posting_date or nowdate())
		taxes = sick_rules.taxes(flt(self.fund_gross), self.employee, self.case_type)
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
		self.advance_social_status("Paid by Social Security")
		self.save()

		return [card, tax]


@frappe.whitelist()
def find_unregistered(company):
	"""Дні «Лікарняного» в табелі, яких немає в жодному випадку, — готові чернетки випадків."""
	frappe.has_permission("Sick Leave Case", "create", throw=True)

	runs = unregistered_runs(company)
	created = []

	for run in runs:
		case = frappe.new_doc("Sick Leave Case")
		case.employee = run.employee
		case.company = company
		case.start_date = run.from_date
		case.end_date = run.to_date
		case.insert()
		created.append(case.name)

	return created


@frappe.whitelist()
def get_unregistered_days(employee):
	"""Для нового випадку з форми: дні «Лікарняного» з табеля цього працівника без випадку."""
	frappe.has_permission("Sick Leave Case", "create", throw=True)
	company = frappe.db.get_value("Employee", employee, "company")

	return [
		{"from_date": run.from_date, "to_date": run.to_date} for run in unregistered_runs(company, employee)
	]


def unregistered_runs(company, employee=None) -> list:
	"""Суцільні відрізки днів «Лікарняного» в табелі, що не належать жодному випадку.

	Відрізок не рветься на вихідних: ЕЛН іде календарними днями, а табель вихідні не
	відмічає."""
	filters = {"company": company, "docstatus": 1, "status": "Sick Leave"}
	case_filters = {"company": company, "docstatus": ("!=", 2)}

	if employee:
		filters["employee"] = employee
		case_filters["employee"] = employee

	rows = frappe.get_all(
		"Attendance",
		filters=filters,
		fields=["employee", "employee_name", "attendance_date"],
		order_by="employee asc, attendance_date asc",
	)
	covered = {}

	for case in frappe.get_all(
		"Sick Leave Case", filters=case_filters, fields=["employee", "start_date", "end_date"]
	):
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

	return runs


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


@frappe.whitelist()
def average_breakdown(employee, start_date, incapacity_case=None, from_month=None, to_month=None):
	"""Розклад середньої по місяцях для вікна розрахунку: заробіток, дні й підсумок.

	Дата події — перший день усієї хвороби; без `from_month`/`to_month` період автоматичний."""
	frappe.has_permission("Sick Leave Case", "read", throw=True)

	if incapacity_case:
		start_date = frappe.db.get_value("Incapacity Case", incapacity_case, "start_date") or start_date

	person = frappe._dict(frappe.get_cached_doc("Employee", employee).as_dict())
	months = average_pay.month_range(from_month, to_month) if from_month and to_month else None
	details = average_pay.sick_average_details(person, getdate(start_date), months)

	return {
		"rows": [
			{**row, "month": str(row.month), "label": formatdate(row.month, "MM.yyyy")}
			for row in details.rows
		],
		"earnings": details.earnings,
		"days": details.days,
		"uncapped": details.uncapped,
		"limit": details.limit,
		"capped": details.capped,
		"average": details.average,
		"from_salary": details.from_salary,
		"short_tenure": details.short_tenure,
		"tenure_months": details.tenure_months,
		"minimum_wage": details.minimum_wage,
		"period_start": str(details.period_start) if details.period_start else None,
		"period_end": str(details.period_end) if details.period_end else None,
	}
