"""Move `Workplace Script.workplace` into the new `workplaces` child table.

The single Link became a table so one script can serve several benches. The old column
is still on the table after the model sync, so read it directly.
"""

import frappe


def execute():
	if not frappe.db.has_column("Workplace Script", "workplace"):
		return

	rows = frappe.db.sql(
		"""
		select name, workplace from `tabWorkplace Script`
		where ifnull(workplace, '') != ''
		""",
		as_dict=True,
	)
	for row in rows:
		if frappe.db.exists(
			"Workplace Script Workplace",
			{"parenttype": "Workplace Script", "parentfield": "workplaces", "parent": row.name},
		):
			continue
		if not frappe.db.exists("Workplace", row.workplace):
			continue
		child = frappe.get_doc(
			{
				"doctype": "Workplace Script Workplace",
				"parenttype": "Workplace Script",
				"parentfield": "workplaces",
				"parent": row.name,
				"workplace": row.workplace,
				"idx": 1,
			}
		)
		child.insert(ignore_permissions=True)

	frappe.db.set_value("Workplace Script", None, "workplace", None, update_modified=False)
