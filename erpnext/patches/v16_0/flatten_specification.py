import frappe

from erpnext.stock.doctype.specification_number_template.specification_number_template import (
	apply_override,
)

RETIRED_DOCTYPES = (
	"ESKD Document",
	"ESKD Document Type",
	"ESKD Product",
	"Specification Variant Attribute",
	"Specification Variant Settings",
	"Specification Variant Field",
)


def execute():
	"""Specification becomes a flat ЄСКД catalog with no Item template, product or variants.

	Catalog templates are dropped, the ESKD document register goes with its doctypes, and
	every remaining specification gets its Display Code.
	"""
	_drop_catalog_templates()
	_drop_workspace_links()
	for doctype in RETIRED_DOCTYPES:
		frappe.delete_doc_if_exists("DocType", doctype, force=True)
		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{doctype}`")
	_set_display_codes()


def _drop_catalog_templates():
	if not frappe.db.has_column("Specification", "has_variants"):
		return
	for name in frappe.db.sql_list("SELECT name FROM `tabSpecification` WHERE has_variants = 1"):
		frappe.delete_doc("Specification", name, force=True, ignore_permissions=True)


def _drop_workspace_links():
	rows = frappe.get_all(
		"Workspace Link",
		filters={"link_to": ("in", RETIRED_DOCTYPES), "link_type": "DocType"},
		pluck="name",
	)
	for row in rows:
		frappe.delete_doc("Workspace Link", row, force=True, ignore_permissions=True)


def _set_display_codes():
	for spec in frappe.get_all(
		"Specification", fields=["name", "specification_code", "specification_number_template"]
	):
		frappe.db.set_value(
			"Specification",
			spec.name,
			"display_code",
			apply_override(spec.specification_number_template, spec.specification_code),
			update_modified=False,
		)
