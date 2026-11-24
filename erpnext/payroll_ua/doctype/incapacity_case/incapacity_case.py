"""Випадок непрацездатності — одна хвороба працівника від першого до останнього дня.

Усередині нього — «Випадки лікарняного»: по одному на кожен ЕЛН. Кожен рахується й
виплачується окремо; тут лише спільний період, номер і тип.
"""

import frappe
from frappe.model.document import Document
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
		status = "Closed" if all(row.docstatus == 1 for row in rows) else "Open"
		self.db_set(
			{
				"start_date": start,
				"end_date": end,
				"calendar_days": date_diff(end, start) + 1,
				"status": status,
			},
			update_modified=False,
		)


def get_dashboard_data(data):
	data.fieldname = "incapacity_case"
	data.transactions = [{"label": frappe._("Sick Leave Cases"), "items": ["Sick Leave Case"]}]

	return data


def refresh(name):
	if name and frappe.db.exists("Incapacity Case", name):
		frappe.get_doc("Incapacity Case", name).refresh_summary()
