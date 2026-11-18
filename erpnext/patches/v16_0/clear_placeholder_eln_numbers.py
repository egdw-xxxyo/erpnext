import frappe


def execute():
	"""The ЕЛН number became optional until submit: drop the «Не вказано» placeholder that
	«Find Unregistered Sick Days» used to put in, so those rows show up as missing a number."""
	for placeholder in ("Not entered", "Не вказано"):
		frappe.db.set_value(
			"Sick Leave Certificate",
			{"eln_number": placeholder, "parenttype": "Sick Leave Case", "docstatus": 0},
			"eln_number",
			None,
			update_modified=False,
		)
