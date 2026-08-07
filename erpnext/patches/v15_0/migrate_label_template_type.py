import frappe


def execute():
	if not frappe.db.has_column("Label Template", "template_type"):
		return

	rows = frappe.db.sql(
		"""
		SELECT name, reference_doctype, data_fields, barcode_type
		FROM `tabLabel Template`
		""",
		as_dict=True,
	)

	for row in rows:
		if row.barcode_type:
			new_type = "Barcode"
		elif row.reference_doctype:
			new_type = "From DocType"
		elif row.data_fields:
			new_type = "Raw Data"
		else:
			new_type = "Other"

		frappe.db.set_value("Label Template", row.name, "template_type", new_type, update_modified=False)
