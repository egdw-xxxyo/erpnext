import frappe


def execute():
	"""Takes the half day off every leave application.

	The attendance sheet has no half days, but the leave application kept the flag on
	applications filed before it, and upstream's attendance reads `half_day_date` on its
	own: a day marked over such an application would come back as Half Day, a status the
	sheet does not draw.
	"""
	table = frappe.qb.DocType("Leave Application")

	frappe.qb.update(table).set(table.half_day, 0).set(table.half_day_date, None).where(
		(table.half_day == 1) | table.half_day_date.isnotnull()
	).run()
