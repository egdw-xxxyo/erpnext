"""Перенесення табелів (Department Timesheet) у штатний облік HRMS.

Рядки табеля стають записами Attendance, а дні відпусток і лікарняних — заявками
Leave Application. Усі місяці разом переносить патч
`erpnext.patches.v15_0.migrate_department_timesheet` (на кожній міграції, один раз).
Окремий місяць можна прогнати руками:

    bench --site frontend execute \
        erpnext.patches.migrate_department_timesheet_to_attendance.execute \
        --kwargs "{'month': 'Квітень', 'year': '2026', 'dry_run': False}"

Правила зарахування днів повторюють серверний скрипт create_monthly_payroll_settlement:

    Робочий день / Присутній, забув пропуск            -> Attendance «Present»
    Відсутність по годинах, absence_hours < 5          -> Attendance «Present»
    Відсутність по годинах, absence_hours >= 5         -> Attendance «Absent»
    Відсутній (прогул)                                 -> Attendance «Absent»
    Відпустка                                          -> Leave Application «Відпустка»
    Відпустка за власний рахунок                       -> Leave Application (is_lwp)
    Лікарняний, перші 5 днів місяця                    -> «Лікарняний (оплачуваний)»
    Лікарняний, 6-й день і далі                        -> «Лікарняний без оплати» (is_lwp)
    Вихідний день                                      -> пропускається
"""

import frappe
from frappe.utils import add_days, getdate

PRESENT_STATUSES = {"Робочий день", "Присутній, забув пропуск"}
ABSENT_STATUSES = {"Відсутній (прогул)"}
HOURLY_ABSENCE = "Відсутність по годинах"
HOURLY_ABSENCE_FULL_DAY = 5
SKIP_STATUSES = {"Вихідний день"}

LEAVE_TYPE_BY_STATUS = {
	"Відпустка": "Відпустка",
	"Відпустка за власний рахунок": "Відпустка за власний рахунок",
}
SICK_STATUS = "Лікарняний"
SICK_PAID = "Лікарняний (оплачуваний)"
SICK_UNPAID = "Лікарняний без оплати"
SICK_PAID_DAYS_PER_MONTH = 5

READY_STATUS = "Передано в бухгалтерію"


def execute(month=None, year=None, dry_run=True):
	if not frappe.db.table_exists("Department Timesheet"):
		print("Department Timesheet не існує — нічого мігрувати")
		return

	if not month or not year:
		frappe.throw("Вкажіть month і year, напр. month='Квітень', year='2026'")

	entries, histogram, conflicts = _collect(month, year)
	print(f"Рядків табеля: {sum(histogram.values())}, розподіл: {histogram}")

	for conflict in conflicts:
		print(f"КОНФЛІКТ: {conflict}")

	attendance_rows = [e for e in entries if not e.get("leave_type")]
	leave_applications = _group_leaves(entries)
	print(
		f"План: Attendance={len(attendance_rows)}, Leave Application={len(leave_applications)}, "
		f"пропущено вихідних={histogram.get('Вихідний день', 0)}"
	)

	if dry_run:
		print("dry_run=True — нічого не записано")
		return

	created = {"attendance": 0, "leave": 0, "skipped": 0}
	problems = []

	for row in attendance_rows:
		if frappe.db.exists(
			"Attendance",
			{"employee": row["employee"], "attendance_date": row["date"], "docstatus": ("<", 2)},
		):
			created["skipped"] += 1
			continue

		try:
			doc = frappe.get_doc(
				{
					"doctype": "Attendance",
					"employee": row["employee"],
					"attendance_date": row["date"],
					"status": row["attendance_status"],
					"company": row["company"],
				}
			)
			doc.insert(ignore_permissions=True)
			doc.submit()
			created["attendance"] += 1
		except Exception as exc:
			problems.append((row["employee"], row["date"], row["attendance_status"], str(exc)))

	for application in leave_applications:
		if _leave_exists(application):
			created["skipped"] += 1
			continue

		try:
			doc = frappe.get_doc(
				{
					"doctype": "Leave Application",
					"employee": application["employee"],
					"leave_type": application["leave_type"],
					"from_date": application["from_date"],
					"to_date": application["to_date"],
					"status": "Approved",
					"company": application["company"],
					"description": f"Міграція табеля за {month} {year}",
				}
			)
			doc.insert(ignore_permissions=True)
			doc.submit()
			created["leave"] += 1
		except Exception as exc:
			problems.append(
				(application["employee"], application["from_date"], application["leave_type"], str(exc))
			)

	frappe.db.commit()
	print(f"Створено: {created}")
	print(f"Помилок: {len(problems)}")
	for problem in problems:
		print(f"  {problem}")


def _leave_exists(application):
	"""Заявка на ці дні вже є — повторний прогін не має плодити дублі."""
	return frappe.db.exists(
		"Leave Application",
		{
			"employee": application["employee"],
			"leave_type": application["leave_type"],
			"from_date": ("<=", application["to_date"]),
			"to_date": (">=", application["from_date"]),
			"docstatus": ("<", 2),
		},
	)


def periods():
	"""Місяці, за якими є готові табелі — (month, year) без повторів."""
	if not frappe.db.table_exists("Department Timesheet"):
		return []

	rows = frappe.get_all(
		"Department Timesheet",
		filters={"status_tabel": READY_STATUS},
		fields=["month", "year"],
		group_by="month, year",
		order_by="year asc, month asc",
	)

	return [(row.month, row.year) for row in rows if row.month and row.year]


def _collect(month, year):
	"""Читає готові табелі місяця й розкладає рядки на записи Attendance / відпустки."""
	sheet_names = frappe.get_all(
		"Department Timesheet",
		filters={"month": month, "year": year, "status_tabel": READY_STATUS},
		pluck="name",
	)

	company_by_employee = {}
	entries = []
	histogram = {}
	conflicts = []
	seen = set()

	for sheet_name in sheet_names:
		sheet = frappe.get_doc("Department Timesheet", sheet_name)

		for entry in sheet.get("attendance_entries") or []:
			status = entry.get("day_status") or "Робочий день"
			histogram[status] = histogram.get(status, 0) + 1

			employee = entry.get("employee")
			date = entry.get("attendance_date")

			if not employee or not date or status in SKIP_STATUSES:
				continue

			key = (employee, str(date))
			if key in seen:
				conflicts.append(f"дубль {employee} {date} ({status}) у табелі {sheet_name}")
				continue
			seen.add(key)

			if employee not in company_by_employee:
				company_by_employee[employee] = frappe.db.get_value("Employee", employee, "company")

			entries.append(
				{
					"employee": employee,
					"date": str(date),
					"day_status": status,
					"absence_hours": frappe.utils.flt(entry.get("absence_hours")),
					"company": company_by_employee[employee],
				}
			)

	_classify(entries)
	return entries, histogram, conflicts


def _classify(entries):
	"""Проставляє attendance_status або leave_type кожному рядку."""
	sick_seen = {}

	for entry in sorted(entries, key=lambda e: (e["employee"], e["date"])):
		status = entry["day_status"]

		if status in LEAVE_TYPE_BY_STATUS:
			entry["leave_type"] = LEAVE_TYPE_BY_STATUS[status]
			continue

		if status == SICK_STATUS:
			key = (entry["employee"], entry["date"][:7])
			sick_seen[key] = sick_seen.get(key, 0) + 1
			entry["leave_type"] = SICK_PAID if sick_seen[key] <= SICK_PAID_DAYS_PER_MONTH else SICK_UNPAID
			continue

		if status in ABSENT_STATUSES:
			entry["attendance_status"] = "Absent"
		elif status == HOURLY_ABSENCE:
			entry["attendance_status"] = (
				"Absent" if entry["absence_hours"] >= HOURLY_ABSENCE_FULL_DAY else "Present"
			)
		elif status in PRESENT_STATUSES:
			entry["attendance_status"] = "Present"
		else:
			entry["attendance_status"] = "Present"


def _group_leaves(entries):
	"""Об'єднує послідовні дні одного типу відпустки в одну заявку."""
	leave_entries = sorted(
		[e for e in entries if e.get("leave_type")],
		key=lambda e: (e["employee"], e["leave_type"], e["date"]),
	)

	applications = []
	current = None

	for entry in leave_entries:
		is_continuation = (
			current
			and current["employee"] == entry["employee"]
			and current["leave_type"] == entry["leave_type"]
			and getdate(entry["date"]) == getdate(add_days(current["to_date"], 1))
		)

		if is_continuation:
			current["to_date"] = entry["date"]
			continue

		if current:
			applications.append(current)

		current = {
			"employee": entry["employee"],
			"leave_type": entry["leave_type"],
			"from_date": entry["date"],
			"to_date": entry["date"],
			"company": entry["company"],
		}

	if current:
		applications.append(current)

	return applications
