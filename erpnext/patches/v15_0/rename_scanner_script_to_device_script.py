import frappe


def execute():
	"""Rename Scanner Script -> Device Script (and child table) and tag existing rows as Scanner type.

	Must run in [pre_model_sync] so the DocType + table rename happens before schema sync
	tries to materialize Device Script columns (otherwise sync would create a brand-new
	empty Device Script DocType, leaving the Scanner Script table orphaned).
	"""

	# Rename child first so the parent's `versions` Table option remains resolvable.
	if frappe.db.exists("DocType", "Scanner Script Version") and not frappe.db.exists(
		"DocType", "Device Script Version"
	):
		frappe.rename_doc("DocType", "Scanner Script Version", "Device Script Version", force=True, merge=False)

	if frappe.db.exists("DocType", "Scanner Script") and not frappe.db.exists("DocType", "Device Script"):
		frappe.rename_doc("DocType", "Scanner Script", "Device Script", force=True, merge=False)

	# Re-point any child rows whose `parenttype` was the old name.
	if frappe.db.table_exists("Device Script Version"):
		frappe.db.sql(
			"UPDATE `tabDevice Script Version` SET parenttype='Device Script' WHERE parenttype='Scanner Script'"
		)

	# Update the `options` link on the parent's `versions` Table field if a stale Custom Field exists.
	frappe.db.sql(
		"""
		UPDATE `tabDocField`
		SET options='Device Script Version'
		WHERE options='Scanner Script Version' AND parent='Device Script'
		"""
	)

	# Reload the renamed DocType so its new field set (script_type, ...) is synced before backfill.
	# Device Script now lives in the Devices module (older installs: manufacturing).
	frappe.reload_doc("devices", "doctype", "device_script_version")
	frappe.reload_doc("devices", "doctype", "device_script")

	# Backfill script_type for any existing rows.
	if frappe.db.table_exists("Device Script"):
		frappe.db.sql(
			"UPDATE `tabDevice Script` SET script_type='Scanner' "
			"WHERE script_type IS NULL OR script_type=''"
		)

	frappe.db.commit()
