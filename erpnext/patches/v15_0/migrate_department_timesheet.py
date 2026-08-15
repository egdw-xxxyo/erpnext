"""Разово переносить усі готові табелі (Department Timesheet) у штатний облік HRMS.

Табель більше не ведуть — облік днів іде через Attendance і Leave Application. Патч
проганяє наявну міграцію по кожному місяцю, за який є табель зі статусом
«Передано в бухгалтерію». Сам перенос ідемпотентний: Attendance і заявки на ті самі дні
пропускаються, тож повторний прогін нічого не дублює.

Сайти без табеля (він жив лише в базі, як desk-DocType) патч просто пропускає.
"""

import frappe

from erpnext.patches.migrate_department_timesheet_to_attendance import execute as migrate_period
from erpnext.patches.migrate_department_timesheet_to_attendance import periods


def execute():
	if not frappe.db.table_exists("Department Timesheet"):
		return

	for month, year in periods():
		migrate_period(month=month, year=year, dry_run=False)
