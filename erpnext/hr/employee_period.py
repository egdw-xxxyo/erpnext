"""Межі роботи працівника: до прийняття й після звільнення днів не буває.

Табель за такі дні — не помилка оформлення, а гроші: кожен зайвий день іде в зарплату. Тож
день поза періодом роботи не можна ані відмітити, ані лишити відміченим — при звільненні
майбутні дні прибираються самі.
"""

import frappe
from frappe import _
from frappe.utils import formatdate, getdate


def validate_attendance_period(doc, method=None):
	"""Attendance.validate: дата має бути в межах роботи людини в компанії."""
	if not doc.employee or not doc.attendance_date:
		return

	employee = frappe.db.get_value(
		"Employee", doc.employee, ["employee_name", "date_of_joining", "relieving_date"], as_dict=True
	)

	if not employee:
		return

	date = getdate(doc.attendance_date)
	name = employee.employee_name or doc.employee

	if employee.date_of_joining and date < getdate(employee.date_of_joining):
		frappe.throw(
			_("{0} was hired on {1} — there is no attendance before that date.").format(
				name, formatdate(employee.date_of_joining)
			),
			title=_("Outside the Employment"),
		)

	if employee.relieving_date and date > getdate(employee.relieving_date):
		frappe.throw(
			_("{0} was dismissed on {1} — there is no attendance after that date.").format(
				name, formatdate(employee.relieving_date)
			),
			title=_("Outside the Employment"),
		)


def clear_attendance_after_relieving(doc, method=None):
	"""Employee.on_update: прибирає табель за днями після звільнення.

	Дату звільнення часто ставлять заднім числом, коли дні до кінця місяця вже відмічені.
	Лишити їх не можна: зарплата рахується за табелем, і людина отримала б за дні, коли вже
	не працювала.
	"""
	if not doc.get("relieving_date"):
		return

	rows = frappe.get_all(
		"Attendance",
		filters={
			"employee": doc.name,
			"docstatus": ("<", 2),
			"attendance_date": (">", getdate(doc.relieving_date)),
		},
		fields=["name", "attendance_date", "docstatus"],
		order_by="attendance_date",
	)

	if not rows:
		return

	removed = []

	for row in rows:
		try:
			# Скасувати, а не просто видалити: поданий табель міг уже потрапити в розрахунок.
			attendance = frappe.get_doc("Attendance", row.name)
			attendance.flags.ignore_permissions = True
			if attendance.docstatus == 1:
				attendance.cancel()
			frappe.delete_doc("Attendance", row.name, force=True, ignore_permissions=True)
			removed.append(formatdate(row.attendance_date))
		except Exception:
			frappe.log_error(
				title=f"Не вдалося прибрати табель після звільнення: {row.name}",
				message=frappe.get_traceback(),
			)

	if removed:
		frappe.msgprint(
			_("The attendance after the dismissal was removed: {0}").format(", ".join(removed)),
			indicator="orange",
			alert=True,
		)
