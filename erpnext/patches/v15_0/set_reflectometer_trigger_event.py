import frappe


def execute():
	"""Default all existing Reflectometer Device Scripts to trigger_event='SOR Uploaded'."""
	if not frappe.db.has_column("Device Script", "trigger_event"):
		return
	frappe.db.sql(
		"""UPDATE `tabDevice Script`
		   SET trigger_event = 'SOR Uploaded'
		   WHERE script_type = 'Reflectometer'
		     AND (trigger_event IS NULL OR trigger_event = '')"""
	)
	frappe.db.commit()
