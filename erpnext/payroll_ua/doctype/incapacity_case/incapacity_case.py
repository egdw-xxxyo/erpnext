"""Випадок непрацездатності — одна хвороба працівника від першого до останнього дня.

Усередині нього — «Випадки лікарняного»: по одному на кожен ЕЛН. Кожен рахується й
виплачується окремо; тут лише спільний період, номер і тип.
"""

import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import date_diff


class IncapacityCase(Document):
	def refresh_summary(self):
		rows = frappe.get_all(
			"Sick Leave Case",
			filters={"incapacity_case": self.name, "docstatus": ("<", 2)},
			fields=["start_date", "end_date", "docstatus"],
		)

		if not rows:
			return

		start = min(row.start_date for row in rows)
		end = max(row.end_date for row in rows)
		self.db_set(
			{
				"start_date": start,
				"end_date": end,
				"calendar_days": date_diff(end, start) + 1,
			},
			update_modified=False,
		)

	@frappe.whitelist()
	def close_case(self):
		self.check_permission("write")

		if frappe.db.exists("Sick Leave Case", {"incapacity_case": self.name, "docstatus": 0}):
			frappe.throw(
				_("Submit or delete the draft sick leave cases before closing the incapacity case."),
				title=_("Draft Sick Leave Cases"),
			)

		self.db_set("status", "Closed")

	@frappe.whitelist()
	def reopen_case(self):
		self.check_permission("write")
		self.db_set("status", "Open")


def get_dashboard_data(data):
	data.fieldname = "incapacity_case"
	data.transactions = [{"label": frappe._("Sick Leave Cases"), "items": ["Sick Leave Case"]}]

	return data


def refresh(name):
	if name and frappe.db.exists("Incapacity Case", name):
		frappe.get_doc("Incapacity Case", name).refresh_summary()
