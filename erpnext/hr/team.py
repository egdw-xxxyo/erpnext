"""Кого керівник бачить у своїх документах — та сама вибірка, що й у табелі.

Джерело правди тут одне — сторінка «Табель» HRMS (`get_editable_employees`): кому керівник
заповнює табель, тому він і ставить премію. Дублювати цю логіку не можна — розійшовшись,
вона дає керівникові премію того, чий табель веде хтось інший, і навпаки.

Роль не дає нічого, і адміністратор тут не виняток: у табелі він бачить лише своїх людей,
тож і в документах — тих самих. Звільнений залишається у вибірці, поки період її документа
зачіпає його роботу.
"""


def sheet_employees(company: str | None = None) -> dict:
	"""Рядки табеля поточного користувача: `{employee: {дати прийому й звільнення}}`."""
	from hrms.hr.page.attendance_sheet.attendance_sheet import get_editable_employees

	return get_editable_employees(company)


def managed_employees(company: str | None = None, start=None, end=None) -> list[str]:
	"""Підлеглі поточного користувача — рівно ті, кому він заповнює табель.

	`start`/`end` — період документа: з ним у вибірці лишаються тільки ті, хто в цьому
	періоді працював (звільнений минулого місяця в поточну відомість не потрапляє).
	"""
	from hrms.hr.page.attendance_sheet.attendance_sheet import employed_within

	employees = sheet_employees(company)

	if start and end:
		employees = {
			employee: details
			for employee, details in employees.items()
			if employed_within(details, start, end)
		}

	return list(employees)


def visible_employees(company: str | None = None, start=None, end=None) -> list[str]:
	"""Кого показувати в документі — той самий список, що й у табелі."""
	return managed_employees(company, start, end)
