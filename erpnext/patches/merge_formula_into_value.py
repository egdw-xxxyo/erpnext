import frappe


def execute():
	"""Merge formula field into value with '=' prefix convention."""
	# On a fresh site this runs before the model sync creates the child table, and
	# has_column raises TableMissingError instead of returning False.
	if not frappe.db.table_exists("Item Specification Parameter"):
		return

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
