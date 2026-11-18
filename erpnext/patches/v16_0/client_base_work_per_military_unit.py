import frappe


def execute():
	"""Client base work moved from Contact to Military Unit: carry open sessions over to the units."""
	if not frappe.db.has_column("Contact", "cb_working"):
		return
	rows = frappe.db.sql(
		"""
		SELECT dl.link_name AS unit, c.cb_working_by AS user, MIN(c.cb_work_started) AS started
		FROM `tabContact` c
		JOIN `tabDynamic Link` dl
			ON dl.parent = c.name AND dl.parenttype = 'Contact' AND dl.link_doctype = 'Military Unit'
		WHERE c.cb_working = 1 AND IFNULL(c.cb_working_by, '') != ''
		GROUP BY dl.link_name, c.cb_working_by
		""",
		as_dict=True,
	)
	for r in rows:
		if frappe.db.get_value("Military Unit", r.unit, "cb_working"):
			continue
		frappe.db.set_value(
			"Military Unit",
			r.unit,
			{"cb_working": 1, "cb_done": 0, "cb_working_by": r.user, "cb_work_started": r.started},
			update_modified=False,
		)
	frappe.db.sql(
		"""
		UPDATE `tabContact`
		SET cb_working = 0, cb_done = 0, cb_working_by = NULL, cb_work_started = NULL
		WHERE cb_working = 1
		"""
	)
	for field in ("cb_working", "cb_done", "cb_working_by", "cb_work_started"):
		name = frappe.db.get_value("Custom Field", {"dt": "Contact", "fieldname": field})
		if name:
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
