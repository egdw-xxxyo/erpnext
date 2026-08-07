"""Auto-creation of a variant BOM from its template item's default BOM.

Lives outside the stock `bom.py` on purpose: appending to stock modules is what
produced the v15 merge conflicts (see CLAUDE.md). Called from
`Item._create_variant_bom_if_applicable` on `after_insert`.
"""

import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.utils import get_link_to_form

from erpnext.stock.doctype.item.item import get_item_details


def create_variant_bom_from_template(variant_item_code):
	variant_doc = frappe.get_doc("Item", variant_item_code)
	if not variant_doc.variant_of:
		return

	default_bom = frappe.db.get_value("Item", variant_doc.variant_of, "default_bom")
	if not default_bom:
		return

	bom_docstatus = frappe.db.get_value("BOM", default_bom, "docstatus")
	if bom_docstatus != 1:
		return

	template_bom = frappe.get_doc("BOM", default_bom)
	template_rows = [row for row in template_bom.items if row.has_variants]
	if not template_rows:
		return

	attr_map = {d.attribute: d.attribute_value for d in variant_doc.attributes}
	linked_items = {}

	for attr_name, attr_value in attr_map.items():
		linked_item = frappe.db.get_value(
			"Item Attribute Value",
			{"parent": attr_name, "attribute_value": attr_value},
			"linked_item",
		)
		if linked_item:
			item_variant_of = frappe.db.get_value("Item", linked_item, "variant_of")
			if item_variant_of:
				linked_items[item_variant_of] = linked_item

	if not linked_items:
		return

	doc = get_mapped_doc(
		"BOM",
		default_bom,
		{
			"BOM": {"doctype": "BOM", "validation": {"docstatus": ["=", 1]}},
			"BOM Item": {
				"doctype": "BOM Item",
				"field_no_map": ["bom_no"],
			},
		},
	)

	doc.item = variant_item_code
	item_data = get_item_details(variant_item_code)
	doc.update(
		{
			"item_name": item_data.item_name,
			"description": item_data.description,
			"uom": item_data.stock_uom,
			"allow_alternative_item": item_data.allow_alternative_item,
		}
	)

	# Restore has_variants from template (get_mapped_doc may not copy it)
	template_has_variants = {row.item_code: row.has_variants for row in template_bom.items}
	for row in doc.items:
		if row.item_code in template_has_variants:
			row.has_variants = template_has_variants[row.item_code]

	for row in doc.items:
		if row.has_variants and row.item_code in linked_items:
			replacement = linked_items[row.item_code]
			row.original_item = row.item_code
			row.item_code = replacement
			row.has_variants = 0
			replacement_data = get_item_details(replacement)
			row.item_name = replacement_data.item_name
			row.description = replacement_data.description
			row.stock_uom = replacement_data.stock_uom
			row.uom = replacement_data.stock_uom

	doc.insert(ignore_permissions=True)
	frappe.msgprint(
		_("Variant BOM {0} created as Draft from template BOM {1}").format(
			get_link_to_form("BOM", doc.name), default_bom
		),
		alert=True,
	)
	return doc
