import frappe


def execute():
	"""Merge formula field into value with '=' prefix convention."""
	if not frappe.db.has_column("Item Specification Parameter", "formula"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabItem Specification Parameter`
		SET value = CONCAT('=', formula)
		WHERE formula IS NOT NULL AND formula != ''
	"""
	)
	frappe.db.commit()
