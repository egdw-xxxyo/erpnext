import frappe


def execute():
	"""The Import Center page became `import-file`: drop the old page record and its sidebar link,
	the sync and `add_data_links` create the new ones."""
	frappe.db.delete("Workspace Sidebar Item", {"link_type": "Page", "link_to": "data-import-center"})
	frappe.db.delete("Has Role", {"parenttype": "Page", "parent": "data-import-center"})
	frappe.db.delete("Page", {"name": "data-import-center"})
