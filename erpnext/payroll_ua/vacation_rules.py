"""Правила Закону «Про відпустки», за якими платяться відпускні.

Компанія надає відпустку частинами, як працівникові треба, а закон вимагає офіційну виплату:
одна з частин щорічної відпустки — не менше 14 календарних днів, платити за 3 дні до початку.
Тож «взято» і «оплачено офіційно» живуть окремо: дні копляться, а офіційний блок платиться
одним рухом і закриває найстаріші неоплачені дні (FIFO).
"""

from frappe.utils import add_days, add_months, date_diff, getdate

# Закон «Про відпустки», ст. 6: щорічна основна відпустка — не менше 24 календарних днів за рік.
ANNUAL_DAYS = 24
ACCRUAL_PER_MONTH = ANNUAL_DAYS // 12

# Ст. 12: одна з частин відпустки — не менше 14 календарних днів.
MIN_PART = 14

# Ст. 8: основна й додаткові відпустки разом — не більше 59 календарних днів за рік.
MAX_TOTAL = 59

# Ст. 115 КЗпП: відпускні платяться не пізніше ніж за 3 дні до початку відпустки.
PAY_BEFORE_DAYS = 3

OPENING_FIELD = "custom_vacation_paid_opening"


def entitled_days(date_of_joining, on_date) -> int:
	"""Скільки днів відпустки працівник заробив за весь час роботи: 2 дні за повний місяць."""
	if not date_of_joining:
		return 0

	joined, until = getdate(date_of_joining), getdate(on_date)
	months = 0

	while getdate(add_months(joined, months + 1)) <= add_days(until, 1):
		months += 1

	return months * ACCRUAL_PER_MONTH


def due_date(first_day):
	"""Останній день, коли відпускні ще вчасні."""
	return add_days(getdate(first_day), -PAY_BEFORE_DAYS)


def split_unpaid(days: list, paid: float) -> list:
	"""Неоплачені дні: від усіх днів відпустки по порядку віднімається вже оплачене, найстаріші першими."""
	skip = max(int(paid), 0)

	return list(days)[skip:]


def is_late(first_day, on_date) -> bool:
	return date_diff(due_date(first_day), on_date) < 0
