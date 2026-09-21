"""Fill `Production Line.workplaces` from the benches its plan rows already name.

Before the table existed a line's benches were only implied by its plan. Leaving it empty
would be read as "no filter" by `line_workplaces`, so the app would keep offering every
bench the operator is assigned to.
"""

import frappe


def execute():
	lines = frappe.get_all("Production Line", pluck="name")
	for name in lines:
		doc = frappe.get_doc("Production Line", name)
		if doc.workplaces:
			continue

		seen = []
		for row in doc.plan:
			if row.workplace and row.workplace not in seen:
				seen.append(row.workplace)
		if not seen:
			continue

		for workplace in seen:
			doc.append("workplaces", {"workplace": workplace, "enabled": 1})
		# Two old lines may share a bench, which the new validation refuses. Record what is
		# there rather than failing the migration over it — the next manual save reports it.
		doc.flags.ignore_validate = True
		doc.save(ignore_permissions=True)
