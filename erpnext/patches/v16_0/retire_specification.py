import frappe

RETIRED_DOCTYPES = (
	"Specification",
	"ESKD Document",
	"ESKD Document Type",
	"ESKD Product",
	"Specification Variant Attribute",
	"Specification Variant Settings",
	"Specification Variant Field",
)


def execute():
	"""ЄСКД specifications live in Technical Documentation now.

	A catalog prefix (УКРП.563562.003-ХХС) is a Technical Document of type «Специфікація» and
	every designation under it a Product Modification; so is every БпАК modification. The Specification catalog, its variant machinery and the ESKD
	document register are dropped; `eskd_import.run` reloads the catalog from the workbook.
	Item.specification now links Product Modification, so values pointing at the old catalog
	are cleared.
	"""
	_drop_workspace_links()
	for doctype in RETIRED_DOCTYPES:
		frappe.delete_doc_if_exists("DocType", doctype, force=True)
		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{doctype}`")
	frappe.db.delete("Specification Component", {"parenttype": "Specification"})
	_clear_item_links()


def _drop_workspace_links():
	rows = frappe.get_all(
		"Workspace Link",
		filters={"link_to": ("in", RETIRED_DOCTYPES), "link_type": "DocType"},
		pluck="name",
	)
	for row in rows:
		frappe.delete_doc("Workspace Link", row, force=True, ignore_permissions=True)


def _clear_item_links():
	if not (
		frappe.db.has_column("Item", "specification") and frappe.db.has_column("Item", "specification_code")
	):
		return
	frappe.db.sql(
		"""
		UPDATE `tabItem` i
		LEFT JOIN `tabProduct Modification` d ON d.name = i.specification
		SET i.specification = NULL, i.specification_code = NULL
		WHERE i.specification IS NOT NULL AND d.name IS NULL
		"""
	)
