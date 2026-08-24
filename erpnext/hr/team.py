"""Кого керівник бачить у своїх документах — та сама вибірка, що й у табелі.

Табель («Attendance Sheet» у HRMS) показує керівникові його прямих підлеглих
(`reports_to`) плюс тих, кого HR дописав у картку керівника вручну — так у табель
потрапляє людина без власного керівника. Роль тут не дає нічого: HR-менеджер без
підлеглих бачить порожній список так само, як будь-хто інший.

Затвердження премій рахує ті самі гроші за тими самими людьми, тож вибірка мусить
бути спільною — інакше керівник ставить премію тому, чий табель він навіть не веде.
"""

import frappe

# Дописані вручну люди живуть у дитячій таблиці картки Employee (доктайп HRMS).
EXTRA_EMPLOYEE_DOCTYPE = "Attendance Sheet Extra Employee"
EXTRA_EMPLOYEE_FIELD = "attendance_sheet_extra_employees"


def session_employee() -> str | None:
	"""Працівник, до якого прив'язаний поточний користувач."""
	return frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"}, "name")


def extra_employees(manager: str) -> list[str]:
	"""Кого HR дописав у картку цього керівника; сам керівник відкидається."""
	if not frappe.db.exists("DocType", EXTRA_EMPLOYEE_DOCTYPE):
		return []

	rows = frappe.get_all(
		EXTRA_EMPLOYEE_DOCTYPE,
		filters={
			"parenttype": "Employee",
			"parentfield": EXTRA_EMPLOYEE_FIELD,
			"parent": manager,
		},
		pluck="employee",
		ignore_permissions=True,
	)

	return [employee for employee in rows if employee != manager]


def managed_employees(company: str | None = None) -> list[str]:
	"""Підлеглі поточного користувача — один рівень `reports_to` плюс дописані вручну.

	Порядок такий самий, як у табелі: спершу дописані, далі підлеглі за ієрархією.
	"""
	own = session_employee()

	if not own:
		return []

	added = extra_employees(own)
	scope = {"status": "Active", "reports_to": own}

	if company:
		scope["company"] = company

	reports = frappe.get_all(
		"Employee",
		filters=scope,
		pluck="name",
		order_by="employee_name",
		ignore_permissions=True,
	)

	return added + [name for name in reports if name not in added]


def sees_everyone() -> bool:
	"""Адміністратор — єдиний виняток: без нього не було б кому налаштувати ієрархію."""
	return frappe.session.user == "Administrator"


def visible_employees(company: str | None = None) -> list[str] | None:
	"""Кого показувати в документі: `None` — обмеження немає (адміністратор)."""
	return None if sees_everyone() else managed_employees(company)
