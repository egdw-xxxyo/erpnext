import frappe


def execute():
	"""Replace standalone Device Script Log with child table Device Script Run on Device Script.

	Earlier deploy created a flat 'Device Script Log' DocType. We've switched to a child-table
	model: a single Device Script Run row per execution, attached to the Device Script as
	`runs`, capped at 200 rows per script (FIFO prune handled in code).

	This patch drops the standalone DocType + its table cleanly. The new child DocType
	(Device Script Run) is synced during the normal schema sync that follows.
	"""
	if frappe.db.exists("DocType", "Device Script Log"):
		try:
			frappe.delete_doc("DocType", "Device Script Log", ignore_missing=True, force=True)
		except Exception:
			frappe.db.sql("DELETE FROM `tabDocType` WHERE name = 'Device Script Log'")
		# DROP TABLE causes an implicit commit; flush first so the migrate transaction is clean.
		frappe.db.commit()
		frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabDevice Script Log`")
		frappe.db.commit()
