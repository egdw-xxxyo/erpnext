"""Аванс — перший платіж місяця, по день відсікання включно (за домовленістю — 15-те).

Місячний Salary Slip лишається єдиним документом нарахування. Аванс — це виплата всередині
місяця: сума рахується за оплачуваними днями першої половини, а в листку вона повертається
відрахуваннями «Аванс», тож другий платіж = залишок.

Обидві частини зарплати діляться однаково:

	денна_ставка   = частина_окладу / робочі_дні(місяць)
	аванс_частини  = денна_ставка × оплачувані_дні(1..відсікання)

Оплачувані дні рахуються **за календарем**, а не за табелем: робочі дні від прийняття на
роботу по день відсікання мінус єдина неоплачувана відсутність — лікарняний понад
`SICK_DAYS_PAID` днів. Усе інше (присутність, відпустка, зокрема без збереження, прогул і
лікарняний у межах норми) платиться як робочий день, а незакритий табель аванс не зменшує:
день без жодної відмітки вважається відпрацьованим.

Кожна половина — окремий компонент («Аванс на картку» / «Аванс готівкою»), щоб у листку було
видно з назви, звідки платили.

	bench --site frontend execute erpnext.hr.salary_advance.create_advance \
	    --kwargs "{'company': 'КАЛЬХЕОН', 'year': 2026, 'month': 4, 'dry_run': False}"
"""

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, get_last_day, getdate

from erpnext.hr import payroll_tax
from erpnext.hr.salary_split import salary_parts_on

ADVANCE_COMPONENT = "Аванс"
ADVANCE_CARD = "Аванс на картку"
ADVANCE_CASH = "Аванс готівкою"

DEFAULT_CUTOFF_DAY = 15

# Скільки дня зараховується авансу — так само, як його оплачує листок.
DAY_WEIGHT = {
	"Present": 1.0,
	"Work From Home": 1.0,
	"On Leave": 1.0,
	"Absent": 0.0,
}

# Скільки днів офіційного лікарняного оплачується на місяць — понад норму день не платиться.
SICK_DAYS_PAID = 5

# Скільки годин має повний робочий день, коли зміна не задана.
DEFAULT_DAY_HOURS = 8.0

EMPTY_STATS = {
	"credited_days": 0.0,
	"present_days": 0.0,
	"leave_days": 0.0,
	"unpaid_leave_days": 0.0,
	"sick_days": 0.0,
	"absent_days": 0.0,
	"overtime_hours": 0.0,
	"shortfall_hours": 0.0,
}


def plan_month(company, year, month) -> list:
	"""Той самий розрахунок, але за повний місяць — база «Зарплатної відомості».

	Відомість платить залишок місяця, тож рахувати його мусить та сама арифметика, що й аванс:
	інакше дві виплати того самого місяця розходяться в днях і ставці. Рядки з нульовим табелем
	лишаються — у відомості мусить бути видно кожного, навіть без відпрацьованих днів.

	Оплачувані дні місяця — `paid_days`: робочі дні за календарем мінус відпустка й лікарняний,
	точно як в авансі. Табель (`credited_days`) лишається довідкою: він пояснює місяць, але
	суму більше не задає.
	"""
	return plan_advance(
		company,
		year,
		month,
		cutoff=get_last_day(getdate(f"{int(year)}-{int(month):02d}-01")),
		skip_empty=False,
		skip_without_salary=False,
	)


def plan_advance(
	company,
	year,
	month,
	cutoff_day=DEFAULT_CUTOFF_DAY,
	cutoff=None,
	skip_empty=True,
	skip_without_salary=True,
) -> list:
	"""Рахує аванс по кожному працівнику компанії, нічого не записуючи.

	`cutoff` — по який день рахувати (за замовчуванням день відсікання авансу);
	`skip_empty` — чи відкидати тих, у кого нема зарахованих днів;
	`skip_without_salary` — чи відкидати тих, у кого оклад не заданий (обидві частини нульові).
	"""
	period_start, period_end, computed_cutoff = period(year, month, cutoff_day)
	cutoff = getdate(cutoff) if cutoff else computed_cutoff

	# Звільнений серед місяця працівник лишається в розрахунку: зароблене за відпрацьовану
	# частину місяця йому винні так само, і саме тут його востаннє видно. Дні йому рахуються
	# лише по дату звільнення — за неї він уже не працював (див. `_employee_period`).
	employees = frappe.get_all(
		"Employee",
		filters=[
			["company", "=", company],
			["status", "in", ["Active", "Left"]],
			["date_of_joining", "<=", period_end],
		],
		fields=[
			"name",
			"employee_name",
			"department",
			"reports_to",
			"holiday_list",
			"date_of_joining",
			"relieving_date",
			"custom_tax_id",
		],
		order_by="department asc, employee_name asc",
	)

	stats = attendance_stats([employee.name for employee in employees], period_start, cutoff)
	absences = absence_days([employee.name for employee in employees], period_start, cutoff)
	day_hours = standard_day_hours()
	holiday_dates = {}
	rows = []

	for employee in employees:
		# Звільнені до початку періоду в ньому вже нічого не заробили.
		if employee.relieving_date and getdate(employee.relieving_date) < period_start:
			continue

		official, cash = salary_parts_on(employee.name, period_end)

		if skip_without_salary and not (official + cash):
			continue

		holidays = _holiday_list(employee, company)

		if not holidays:
			frappe.throw(
				_("Set the holiday list for {0} — without it every day counts as a working day.").format(
					employee.employee_name or employee.name
				),
				title=_("No Holiday List"),
			)

		first, last = _employee_period(employee, period_start, cutoff)
		month_days = _working_days(period_start, period_end, holidays)
		planned_days = _working_days(first, last, holidays)
		attendance = stats.get(employee.name) or frappe._dict(EMPTY_STATS)

		# Табель за межами роботи в компанії не рахується: людині, звільненій 20-го, хтось
		# міг проставити дні до кінця місяця, і вона отримала б за них зарплату.
		if first > period_start or last < cutoff:
			attendance = (attendance_stats([employee.name], first, last) or {}).get(
				employee.name
			) or frappe._dict(EMPTY_STATS)

		credited_days = flt(attendance.credited_days, 2)
		# Аванс платиться за календарем: із запланованих днів вилітає лише лікарняний понад
		# норму — за нього платить не компанія.
		advance_days = _paid_days(
			first, last, holidays, absences.get(employee.name) or {}, planned_days, holiday_dates
		)

		if not month_days or (skip_empty and advance_days <= 0):
			continue

		rate_official = flt(official) / month_days if month_days else 0
		rate_cash = flt(cash) / month_days if month_days else 0

		rows.append(
			frappe._dict(
				employee=employee.name,
				employee_name=employee.employee_name,
				department=employee.department,
				manager=employee.reports_to,
				official_salary=flt(official),
				cash_salary=flt(cash),
				month_working_days=month_days,
				planned_days=planned_days,
				planned_hours=flt(planned_days * day_hours, 2),
				credited_days=credited_days,
				present_days=flt(attendance.present_days, 2),
				leave_days=flt(attendance.leave_days, 2),
				unpaid_leave_days=flt(attendance.unpaid_leave_days, 2),
				sick_days=flt(attendance.sick_days, 2),
				absent_days=flt(attendance.absent_days, 2),
				overtime_hours=flt(attendance.overtime_hours, 2),
				shortfall_hours=flt(attendance.shortfall_hours, 2),
				working_hours=flt(
					credited_days * day_hours
					+ flt(attendance.overtime_hours)
					- flt(attendance.shortfall_hours),
					2,
				),
				tax_id=employee.custom_tax_id,
				relieving_date=employee.relieving_date,
				daily_rate=flt(rate_official + rate_cash, 2),
				official=flt(rate_official * credited_days, 2),
				official_net=payroll_tax.net(rate_official * credited_days),
				cash=flt(rate_cash * credited_days, 2),
				# Аванс має власну базу днів, тож і власні суми: остаточний розрахунок далі
				# рахується за табелем і сам зніме те, що людина не відпрацювала.
				advance_days=advance_days,
				advance_official=flt(rate_official * advance_days, 2),
				advance_official_net=payroll_tax.net(rate_official * advance_days),
				advance_cash=flt(rate_cash * advance_days, 2),
			)
		)

	for row in rows:
		# сумісність зі старим друком і викликами з відомості
		row.days = f"{row.credited_days:g}/{row.month_working_days:g}"
		# На руки йде вже без податків: офіційна частина оподаткована, готівкова — ні.
		row.advance_total = flt(row.advance_official_net + row.advance_cash, 2)
		# Ті самі числа під нейтральними іменами: у авансі це дні до відсікання, у відомості
		# (`plan_month`) — увесь місяць. Обидва документи платять за одним правилом, тож і
		# читають одні поля — «advance_*» там читалося б як помилка.
		row.paid_days = row.advance_days
		row.paid_official = row.advance_official
		row.paid_official_net = row.advance_official_net
		row.paid_cash = row.advance_cash

	return rows


def apply_advance(company, year, month, rows) -> list:
	"""Створює відрахування «Аванс» на кінець місяця по вже порахованих рядках.

	У відрахування йде сума, яку працівник справді отримав на руки: на картку — офіційна
	частина за вирахуванням ПДФО і військового збору. Інакше листок вирахував би з картки
	більше, ніж туди дійшло.
	"""
	_ensure_components()
	month_end = get_last_day(getdate(f"{int(year)}-{int(month):02d}-01"))
	created = []

	for row in rows:
		# Звільненому все належне платиться в день звільнення (ст. 116 КЗпП), і HRMS тримає те
		# саме правило: відрахування з датою пізнішою за звільнення він не приймає.
		payroll_date = payroll_date_for(row["employee"], month_end)

		for amount, component in (
			(flt(row.get("official_net", row.get("official"))), ADVANCE_CARD),
			(flt(row.get("cash")), ADVANCE_CASH),
		):
			if not flt(amount, 2):
				continue

			created.append(_make_additional_salary(row["employee"], company, payroll_date, amount, component))

	return created


def reschedule_deductions_on_relieving(doc, method=None):
	"""Employee.on_update: переносить відрахування, які лишилися за датою звільнення.

	Аванс міг бути вже оформлений на кінець місяця, а людину звільнили серед місяця — тоді
	відрахування не потрапляє в її останній листок (він закінчується днем звільнення), і аванс
	просто лишається невирахуваним. Переставляємо його на день звільнення — туди, де за ст. 116
	КЗпП і має бути розрахунок.
	"""
	if not doc.get("relieving_date"):
		return

	relieving = getdate(doc.relieving_date)
	rows = frappe.get_all(
		"Additional Salary",
		filters={"employee": doc.name, "docstatus": 1, "payroll_date": (">", relieving)},
		fields=["name", "salary_component", "amount", "company", "payroll_date", "type"],
	)
	moved = []

	for row in rows:
		try:
			old = frappe.get_doc("Additional Salary", row.name)
			old.flags.ignore_permissions = True
			old.cancel()
			new = frappe.get_doc(
				{
					"doctype": "Additional Salary",
					"employee": doc.name,
					"company": row.company,
					"salary_component": row.salary_component,
					"amount": row.amount,
					"payroll_date": relieving,
					"overwrite_salary_structure_amount": 0,
				}
			)
			new.insert(ignore_permissions=True)
			new.submit()
			moved.append(
				f"{row.salary_component}: {frappe.format(row.payroll_date, {'fieldtype': 'Date'})} → {frappe.format(relieving, {'fieldtype': 'Date'})}"
			)
		except Exception:
			frappe.log_error(
				title=f"Не вдалося перенести відрахування на дату звільнення: {row.name}",
				message=frappe.get_traceback(),
			)

	if moved:
		frappe.msgprint(
			_("The deductions were moved to the dismissal date: {0}").format(", ".join(moved)),
			indicator="orange",
			alert=True,
		)


def payroll_date_for(employee, month_end):
	"""Дата відрахування: кінець місяця, а для звільненого — день звільнення."""
	relieving = frappe.db.get_value("Employee", employee, "relieving_date")

	if relieving and getdate(relieving) < getdate(month_end):
		return getdate(relieving)

	return getdate(month_end)


def create_advance(
	company, year, month, cutoff_day=DEFAULT_CUTOFF_DAY, dry_run=True, require_attendance=True
):
	"""Рахує і (якщо не пробний прогін) створює аванс за першу половину місяця."""
	if not frappe.db.exists("Salary Component", ADVANCE_COMPONENT):
		frappe.throw(_("Salary Component {0} does not exist.").format(ADVANCE_COMPONENT))

	period_start, _period_end, cutoff = period(year, month, cutoff_day)
	rows = plan_advance(company, year, month, cutoff_day)
	_report(rows, period_start, cutoff, dry_run)

	if dry_run:
		return rows

	apply_advance(company, year, month, rows)
	frappe.db.commit()

	return rows


def period_norm(company, year, month, cutoff_day=DEFAULT_CUTOFF_DAY) -> tuple:
	"""Норма першої половини місяця за календарем компанії: робочі дні й години.

	Довідкове число для шапки документа — на відміну від рядків, воно нічиє і рахується
	за списком вихідних компанії, а не працівника.
	"""
	period_start, _period_end, cutoff = period(year, month, cutoff_day)
	holidays = frappe.get_cached_value("Company", company, "default_holiday_list")
	days = _working_days(period_start, cutoff, holidays)

	return days, flt(days * standard_day_hours(), 2)


def period(year, month, cutoff_day=DEFAULT_CUTOFF_DAY) -> tuple:
	period_start = getdate(f"{int(year)}-{int(month):02d}-01")
	period_end = get_last_day(period_start)
	cutoff = min(getdate(f"{int(year)}-{int(month):02d}-{int(cutoff_day):02d}"), period_end)

	return period_start, period_end, cutoff


def _employee_period(employee, period_start, cutoff) -> tuple:
	"""Межі першої половини для конкретного працівника — з урахуванням прийому і звільнення."""
	first = max(period_start, getdate(employee.date_of_joining or period_start))
	last = cutoff

	if employee.relieving_date:
		last = min(cutoff, getdate(employee.relieving_date))

	return first, last


def standard_day_hours() -> float:
	"""Годин у повному робочому дні — з налаштувань HR, інакше вісім."""
	return flt(frappe.db.get_single_value("HR Settings", "standard_working_hours")) or DEFAULT_DAY_HOURS


ATTENDANCE_FIELDS = (
	"present_days",
	"leave_days",
	"unpaid_leave_days",
	"sick_days",
	"absent_days",
	"overtime_hours",
	"shortfall_hours",
)


def attendance_summary(employees: list, start, end) -> dict:
	"""Готові значення полів табеля по кожному працівнику — те, що показують усі три
	зарплатні документи однаково: розклад днів, зараховані дні й години."""
	stats = attendance_stats(employees, start, end)
	day_hours = standard_day_hours()
	summary = {}

	for employee in employees:
		entry = stats.get(employee) or frappe._dict(EMPTY_STATS)
		values = {field: flt(entry.get(field), 2) for field in ATTENDANCE_FIELDS}
		values["credited_days"] = flt(entry.get("credited_days"), 2)
		values["working_hours"] = flt(
			values["credited_days"] * day_hours + values["overtime_hours"] - values["shortfall_hours"], 2
		)
		summary[employee] = values

	return summary


def attendance_stats(employees: list, start, end) -> dict:
	"""Розклад табеля по кожному працівнику за період: дні по статусах і години.

	`credited_days` — те, за що платиться аванс. Неоплачувана відпустка не зараховується:
	у табелі це «On Leave» із заявкою на тип з ознакою `is_lwp`. Решта чисел нічого не
	рахує, вони лише пояснюють суму керівникові.
	"""
	if not employees:
		return {}

	rows = frappe.get_all(
		"Attendance",
		filters={
			"docstatus": 1,
			"employee": ("in", employees),
			"attendance_date": ("between", [start, end]),
		},
		fields=[
			"employee",
			"status",
			"leave_application",
			"overtime_hours",
			"shortfall_hours",
		],
	)

	unpaid = _unpaid_leaves({row.leave_application for row in rows if row.leave_application})
	stats = {}

	for row in rows:
		entry = stats.setdefault(row.employee, frappe._dict(EMPTY_STATS.copy()))
		lwp = row.leave_application in unpaid

		if row.status in ("Present", "Work From Home"):
			entry.present_days += 1
		elif row.status == "Sick Leave":
			entry.sick_days += 1
		elif row.status == "Absent":
			entry.absent_days += 1
		elif row.status == "On Leave":
			entry["unpaid_leave_days" if lwp else "leave_days"] += 1

		entry.overtime_hours += flt(row.overtime_hours)
		entry.shortfall_hours += flt(row.shortfall_hours)

		if not lwp:
			entry.credited_days += DAY_WEIGHT.get(row.status, 0.0)

	return stats


def absence_days(employees: list, start, end) -> dict:
	"""Неоплачувані дні по кожному працівнику: `{працівник: {дата: вага}}`.

	Платяться всі планові робочі дні — присутність, відпустка (зокрема без збереження),
	прогул і офіційний лікарняний у межах `SICK_DAYS_PAID` днів періоду. Знімається лише
	лікарняний понад норму: за нього платить не компанія. Вага дня — 1, для півдня — 0.5.
	"""
	if not employees:
		return {}

	start, end = getdate(start), getdate(end)
	absences = {}

	marked = frappe.get_all(
		"Attendance",
		filters={
			"docstatus": 1,
			"employee": ("in", employees),
			"attendance_date": ("between", [start, end]),
			"status": "Sick Leave",
		},
		fields=["employee", "attendance_date"],
		order_by="attendance_date asc",
	)
	sick_seen = {}

	for row in marked:
		# Офіційний лікарняний оплачується, але не більше ніж `SICK_DAYS_PAID` дні періоду.
		sick_seen[row.employee] = seen = sick_seen.get(row.employee, 0) + 1

		if seen > SICK_DAYS_PAID:
			absences.setdefault(row.employee, {})[getdate(row.attendance_date)] = 1

	return absences


def _paid_days(first, last, holiday_list, absences, planned_days, holiday_dates) -> float:
	"""Оплачувані дні: заплановані робочі мінус неоплачувані відсутності (див. `absence_days`)."""
	if not absences or planned_days <= 0:
		return flt(planned_days, 2)

	holidays = _holiday_dates(holiday_list, first, last, holiday_dates)
	first, last = getdate(first), getdate(last)
	lost = sum(weight for day, weight in absences.items() if first <= day <= last and day not in holidays)

	return flt(max(planned_days - lost, 0), 2)


def _holiday_dates(holiday_list, start, end, cache) -> set:
	"""Свята й вихідні зі списку — щоб відпустка не «з'їдала» день, який і так не робочий."""
	key = (holiday_list, getdate(start), getdate(end))

	if key not in cache:
		cache[key] = (
			{
				getdate(row.holiday_date)
				for row in frappe.get_all(
					"Holiday",
					filters={"parent": holiday_list, "holiday_date": ["between", [start, end]]},
					fields=["holiday_date"],
				)
			}
			if holiday_list
			else set()
		)

	return cache[key]


def _unpaid_leaves(applications: set) -> set:
	if not applications:
		return set()

	rows = frappe.get_all(
		"Leave Application",
		filters={"name": ("in", list(applications))},
		fields=["name", "leave_type"],
	)
	lwp = {
		leave_type
		for leave_type in {row.leave_type for row in rows}
		if frappe.db.get_value("Leave Type", leave_type, "is_lwp")
	}

	return {row.name for row in rows if row.leave_type in lwp}


def _holiday_list(employee, company):
	return employee.holiday_list or frappe.get_cached_value("Company", company, "default_holiday_list")


def _working_days(start, end, holiday_list):
	"""Робочі дні періоду — календарні мінус вихідні та свята зі списку працівника.

	Той самий підрахунок, що й у листку при `include_holidays_in_total_working_days = 0`.
	"""
	start, end = getdate(start), getdate(end)

	if end < start:
		return 0

	days = date_diff(end, start) + 1

	if not holiday_list:
		return days

	holidays = frappe.db.count("Holiday", {"parent": holiday_list, "holiday_date": ["between", [start, end]]})

	return days - holidays


def _ensure_components():
	"""Створює компоненти авансу, копіюючи рахунки з наявного «Аванс»."""
	source = frappe.get_doc("Salary Component", ADVANCE_COMPONENT)

	for component, in_cash in ((ADVANCE_CARD, 0), (ADVANCE_CASH, 1)):
		if frappe.db.exists("Salary Component", component):
			continue

		doc = frappe.get_doc(
			{
				"doctype": "Salary Component",
				"salary_component": component,
				"salary_component_abbr": "AVCARD" if not in_cash else "AVCASH",
				"type": "Deduction",
				"depends_on_payment_days": 0,
				"amount_based_on_formula": 0,
				"accounts": [{"company": row.company, "account": row.account} for row in source.accounts],
			}
		)
		doc.insert(ignore_permissions=True)


def _make_additional_salary(employee, company, payroll_date, amount, component):
	existing = frappe.db.exists(
		"Additional Salary",
		{
			"employee": employee,
			"salary_component": component,
			"payroll_date": payroll_date,
			"docstatus": ["<", 2],
		},
	)

	if existing:
		return existing

	doc = frappe.get_doc(
		{
			"doctype": "Additional Salary",
			"employee": employee,
			"company": company,
			"salary_component": component,
			"amount": amount,
			"payroll_date": payroll_date,
			"overwrite_salary_structure_amount": 0,
			"custom_pay_in_cash": 1 if component == ADVANCE_CASH else 0,
		}
	)
	doc.insert(ignore_permissions=True)
	doc.submit()

	return doc.name


def _report(rows, period_start, cutoff, dry_run):
	print(
		f"Аванс {period_start:%d.%m.%Y}–{cutoff:%d.%m.%Y}"
		f"{' (пробний прогін)' if dry_run else ''}: {len(rows)} працівників"
	)

	for row in rows:
		print(
			f"  {row.employee:<14} {row.employee_name:<28} дні {row.days:>9}"
			f"  офіційно {row.official:>10,.2f}  готівкою {row.cash:>10,.2f}"
		)

	print(
		f"  Разом: офіційно {sum(r.official for r in rows):,.2f},"
		f" готівкою {sum(r.cash for r in rows):,.2f}"
	)


def unlink_advance(company, year, month, dry_run=True):
	"""Скасовує аванс місяця — потрібно, якщо суми довелось перерахувати."""
	payroll_date = get_last_day(getdate(f"{int(year)}-{int(month):02d}-01"))
	names = frappe.get_all(
		"Additional Salary",
		filters={
			"company": company,
			"salary_component": ["in", [ADVANCE_CARD, ADVANCE_CASH]],
			"payroll_date": payroll_date,
			"docstatus": 1,
		},
		pluck="name",
	)
	print(f"Скасувати {len(names)} відрахувань авансу за {payroll_date}")

	if dry_run:
		return names

	for name in names:
		frappe.get_doc("Additional Salary", name).cancel()

	frappe.db.commit()

	return names


UNPAID_LEAVE = "__unpaid_leave"


def _day_note(row, leave_abbrs) -> dict | None:
	if row.overtime_hours:
		return {"text": f"+{flt(row.overtime_hours):g}", "kind": "over"}

	if row.shortfall_hours:
		return {"text": f"-{flt(row.shortfall_hours):g}", "kind": "under"}

	abbr = leave_abbrs.get(row.leave_type)

	return {"text": abbr, "kind": "leave"} if abbr else None


@frappe.whitelist()
def attendance_calendar(employee: str, start: str, end: str, part: str = "official") -> dict:
	"""`part` — чия це половина: офіційна платить прогул, готівкова — ні (див. `absence_days`)."""
	from hrms.hr.attendance_marks import (
		DAY_ABBR,
		DAY_CONTEXT,
		get_abbr,
		get_color,
		get_leave_abbreviations,
	)

	if not frappe.has_permission("Attendance", "read"):
		frappe.throw(_("Not permitted to read attendance"), frappe.PermissionError)

	start, end = getdate(start), getdate(end)
	card = frappe.db.get_value(
		"Employee",
		employee,
		["company", "holiday_list", "date_of_joining", "relieving_date"],
		as_dict=True,
	)

	if not card:
		frappe.throw(_("Employee {0} not found").format(employee))

	holiday_list = card.holiday_list or frappe.get_cached_value(
		"Company", card.company, "default_holiday_list"
	)
	holidays = {}

	if holiday_list:
		holidays = {
			str(row.holiday_date): {
				"description": row.description,
				"status": "Weekly Off" if row.weekly_off else "Holiday",
			}
			for row in frappe.get_all(
				"Holiday",
				filters={"parent": holiday_list, "holiday_date": ("between", [start, end])},
				fields=["holiday_date", "description", "weekly_off"],
			)
		}

	rows = frappe.get_all(
		"Attendance",
		filters={
			"docstatus": 1,
			"employee": employee,
			"attendance_date": ("between", [start, end]),
		},
		fields=[
			"attendance_date",
			"status",
			"leave_type",
			"leave_application",
			"overtime_hours",
			"shortfall_hours",
		],
	)

	leave_abbrs = get_leave_abbreviations()
	unpaid_applications = _unpaid_leaves({row.leave_application for row in rows if row.leave_application})
	days = {}
	used = []

	for row in rows:
		unpaid = row.status == "On Leave" and row.leave_application in unpaid_applications
		key = UNPAID_LEAVE if unpaid else row.status

		days[str(row.attendance_date)] = {
			"status": row.status,
			"label": _("Unpaid Leave") if unpaid else _(row.status),
			"mark": get_abbr(row.status),
			"color": get_color("Absent") if unpaid else get_color(row.status),
			"note": _day_note(row, leave_abbrs),
			"leave_type": row.leave_type,
			"unpaid": unpaid,
			"weight": 0.0 if unpaid else DAY_WEIGHT.get(row.status, 0.0),
		}

		if key not in used:
			used.append(key)

	for key, holiday in holidays.items():
		if key in days:
			continue

		days[key] = {
			"status": holiday["status"],
			"label": holiday["description"] or _(holiday["status"]),
			"mark": get_abbr(holiday["status"]),
			"color": get_color(holiday["status"]),
			"note": None,
			"leave_type": None,
			"unpaid": False,
			"weight": 0.0,
		}

		if holiday["status"] not in used:
			used.append(holiday["status"])

	first = max(start, getdate(card.date_of_joining)) if card.date_of_joining else start
	last = min(end, getdate(card.relieving_date)) if card.relieving_date else end
	unpaid_days = (absence_days([employee], start, end) or {}).get(employee) or {}

	# Готівкова половина за прогул не платить — у її календарі ці дні стоять неоплачуваними.
	if part == "cash":
		unpaid_days = dict(unpaid_days)

		for row in rows:
			if row.status == "Absent":
				unpaid_days[getdate(row.attendance_date)] = 1

	day = start

	# Чим саме день оплачується, видно тільки поруч із календарем: свято й вихідний не
	# оплачуються ніколи, дні поза періодом роботи — теж, а робочий день коштує стільки,
	# скільки лишилося після неоплачуваних відсутностей.
	while day <= end:
		key = str(day)
		entry = days.get(key)

		if key not in holidays:
			if not entry:
				entry = days[key] = {
					"status": None,
					"label": _("Working Day"),
					"mark": None,
					"color": None,
					"note": None,
					"leave_type": None,
					"unpaid": False,
					"weight": 0.0,
				}

			if first <= day <= last:
				entry["paid"] = flt(max(1 - flt(unpaid_days.get(day, 0)), 0), 2)
			else:
				entry["outside_employment"] = True

		if card.date_of_joining and getdate(card.date_of_joining) == day:
			days[key]["boundary"] = "joined"
		elif card.relieving_date and getdate(card.relieving_date) == day:
			days[key]["boundary"] = "relieved"

		day = add_days(day, 1)

	return {
		"start": str(start),
		"end": str(end),
		"days": days,
		"joined_on": str(card.date_of_joining) if card.date_of_joining else None,
		"relieved_on": str(card.relieving_date) if card.relieving_date else None,
		"weekdays": [_(name, context=DAY_CONTEXT) for name in DAY_ABBR],
		"legend": [
			{
				"status": status,
				"label": _("Unpaid Leave") if status == UNPAID_LEAVE else _(status),
				"mark": get_abbr("On Leave" if status == UNPAID_LEAVE else status),
				"color": get_color("Absent" if status == UNPAID_LEAVE else status),
			}
			for status in used
		],
		"holiday_list": holiday_list,
	}
