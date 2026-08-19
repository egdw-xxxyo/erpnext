"""Разово переносить усі готові табелі (Department Timesheet) у штатний облік HRMS.

Табель більше не ведуть — облік днів іде через Attendance і Leave Application. Патч
проганяє наявну міграцію по кожному місяцю, за який є табель зі статусом
«Передано в бухгалтерію». Сам перенос ідемпотентний: Attendance і заявки на ті самі дні
пропускаються, тож повторний прогін нічого не дублює.

Сайти без табеля (він жив лише в базі, як desk-DocType, і на dev уже видалений) патч
просто пропускає — перевіряються і схема, і таблиця: після видалення DocType таблиця
`tabDepartment Timesheet` лишається, а метадані вже ні, тож `get_all` по ній падає.
"""

from erpnext.patches.migrate_department_timesheet_to_attendance import execute as migrate_period
from erpnext.patches.migrate_department_timesheet_to_attendance import periods


def execute():
	for month, year in periods():
		migrate_period(month=month, year=year, dry_run=False)
