import frappe


def execute():
	"""Retire ESKD BpAK Combination — a БпАК is now a Specification with components.

	Also repoints the ЄСКД workspace card, which linked the removed doctype.
	"""
	frappe.delete_doc_if_exists("DocType", "ESKD BpAK Combination")
	frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabESKD BpAK Combination`")

	rows = frappe.get_all(
		"Workspace Link",
		filters={"link_to": "ESKD BpAK Combination", "link_type": "DocType"},
		pluck="name",
	)
	for row in rows:
		frappe.delete_doc("Workspace Link", row, force=True, ignore_permissions=True)

	_add_role_link()


def _add_role_link():
	"""Give the card a link to the new component-role list."""
	if not frappe.db.exists("Workspace", "Stock"):
		return
	workspace = frappe.get_doc("Workspace", "Stock")
	if any(link.link_to == "Specification Component Role" for link in workspace.links):
		return
	if not any(link.type == "Card Break" and link.label == "ESKD Documentation" for link in workspace.links):
		return
	workspace.append(
		"links",
		{
			"type": "Link",
			"label": "Specification Component Role",
			"link_type": "DocType",
			"link_to": "Specification Component Role",
			"link_count": 0,
			"hidden": 0,
			"onboard": 0,
		},
	)
	workspace.save(ignore_permissions=True)
