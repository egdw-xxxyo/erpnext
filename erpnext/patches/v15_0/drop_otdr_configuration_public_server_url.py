import frappe


def execute():
	if frappe.db.has_column("OTDR Configuration", "public_server_url"):
		frappe.db.sql("ALTER TABLE `tabOTDR Configuration` DROP COLUMN `public_server_url`")
