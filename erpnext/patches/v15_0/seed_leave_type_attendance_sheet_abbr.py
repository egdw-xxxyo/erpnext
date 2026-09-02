import frappe
from frappe import _

from erpnext.payroll_ua.setup import setup_attendance_sheet


def execute():
	"""Gives the existing leave types the two abbreviations the sheet was built around.

	Only empty fields are filled, so a site that already labelled its types keeps them.
	The abbreviation is data rather than a label, so it is stored in the site language:
	a patch runs untranslated unless it is told which one that is.
	"""
	setup_attendance_sheet()

	lang = frappe.db.get_default("lang") or "en"
	table = frappe.qb.DocType("Leave Type")

	for is_lwp, abbr in (
		(1, _("Unpaid", lang=lang, context="Leave Type Abbreviation")),
		(0, _("Paid", lang=lang, context="Leave Type Abbreviation")),
	):
		frappe.qb.update(table).set(table.attendance_sheet_abbr, abbr).where(
			(table.is_lwp == is_lwp)
			& (table.attendance_sheet_abbr.isnull() | (table.attendance_sheet_abbr == ""))
		).run()
