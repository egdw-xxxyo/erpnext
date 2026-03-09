"""Patch script to append create_variant_bom_from_template to stock bom.py

This script patches the STOCK bom.py inside the Docker container.
It must NOT be used to copy our local bom.py (which has incompatible changes
like track_semi_finished_goods, ItemDetailsCtx etc.).
"""
import os
import stat
import subprocess
import sys

BOM_PY = "/home/frappe/frappe-bench/apps/erpnext/erpnext/manufacturing/doctype/bom/bom.py"
MARKER = "def create_variant_bom_from_template"
# Fields/imports that exist in our local bom.py but NOT in stock v15.96.1
INCOMPATIBLE_MARKERS = ["track_semi_finished_goods", "ItemDetailsCtx"]

FUNCTION_CODE = '''

def create_variant_bom_from_template(variant_item_code):
	import frappe
	from frappe import _
	from frappe.model.mapper import get_mapped_doc
	from frappe.utils import get_link_to_form
	from erpnext.stock.doctype.item.item import get_item_details

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
'''

with open(BOM_PY, "r") as f:
    content = f.read()

# Fix track_semi_finished_goods references (not in stock v15.96.1)
import re
changed = False

# Fix broken assignment from previous patch: self.get("track_semi_finished_goods") = 0
if 'self.get("track_semi_finished_goods") = ' in content or "self.get('track_semi_finished_goods') = " in content:
    content = re.sub(
        r'(\s+)self\.get\(["\']track_semi_finished_goods["\']\)\s*=\s*.+',
        r'\1pass  # track_semi_finished_goods not available',
        content,
    )
    changed = True

# Fix original: self.track_semi_finished_goods = X → pass
if "self.track_semi_finished_goods = " in content:
    content = re.sub(
        r'(\s+)self\.track_semi_finished_goods\s*=\s*.+',
        r'\1pass  # track_semi_finished_goods not available',
        content,
    )
    changed = True

# Fix reads: self.track_semi_finished_goods → self.get("track_semi_finished_goods")
if re.search(r'self\.track_semi_finished_goods(?!\s*=)', content):
    content = content.replace(
        "self.track_semi_finished_goods",
        'self.get("track_semi_finished_goods")',
    )
    changed = True

if changed:
    try:
        os.chmod(BOM_PY, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH)
    except OSError:
        pass
    with open(BOM_PY, "w") as f:
        f.write(content)
    print("[bom_variant_patch] Fixed track_semi_finished_goods references")

# Fix is_sub_assembly_item reads on BOM Item rows (field may not exist in DocType JSON)
# Replace d.is_sub_assembly_item with d.get("is_sub_assembly_item", 0) for reads,
# but keep assignments like row.is_sub_assembly_item = ... as-is (Frappe allows dynamic attrs)
_isa_read = re.findall(r'(?<!=\s)(?<!")\bd\.is_sub_assembly_item\b', content)
if "d.is_sub_assembly_item" in content:
    content = re.sub(
        r'("is_sub_assembly_item":\s*)d\.is_sub_assembly_item',
        r'\1d.get("is_sub_assembly_item", 0)',
        content,
    )
    content = re.sub(
        r'(\s)bom_item\.is_sub_assembly_item(?!\s*=)',
        r'\1bom_item.get("is_sub_assembly_item", 0)',
        content,
    )
    try:
        os.chmod(BOM_PY, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH)
    except OSError:
        pass
    with open(BOM_PY, "w") as f:
        f.write(content)
    print("[bom_variant_patch] Fixed is_sub_assembly_item references")

# Fix ItemDetailsCtx import if present (not in stock ERPNext)
if "ItemDetailsCtx" in content:
    content = content.replace(
        "from erpnext.stock.get_item_details import ItemDetailsCtx, get_conversion_factor, get_price_list_rate",
        "from erpnext.stock.get_item_details import get_conversion_factor, get_price_list_rate",
    )
    content = content.replace("ctx = ItemDetailsCtx(", "ctx = frappe._dict(")
    try:
        os.chmod(BOM_PY, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH)
    except OSError:
        pass
    with open(BOM_PY, "w") as f:
        f.write(content)
    print("[bom_variant_patch] Fixed ItemDetailsCtx references")

if MARKER in content:
    # Remove old version of our function only (not anything after it)
    marker_pos = content.index(MARKER)
    line_start = content.rfind('\n', 0, marker_pos)
    if line_start == -1:
        line_start = 0
    # Find the end of our function: next top-level 'def ' or EOF
    func_end = len(content)
    search_start = marker_pos + len(MARKER)
    while True:
        next_def = content.find('\ndef ', search_start)
        if next_def == -1:
            break
        # Check it's truly top-level (not indented)
        next_line_start = next_def + 1
        if not content[next_line_start:next_line_start+4].startswith('    ') and \
           not content[next_line_start:next_line_start+1].startswith('\t'):
            func_end = next_def
            break
        search_start = next_def + 4
    before = content[:line_start]
    after = content[func_end:]
    content = before.rstrip() + "\n" + FUNCTION_CODE.rstrip() + "\n" + after.lstrip('\n')
    try:
        os.chmod(BOM_PY, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH)
    except OSError:
        pass
    with open(BOM_PY, "w") as f:
        f.write(content)
    print(f"[bom_variant_patch] Updated function in {BOM_PY}")
else:
    with open(BOM_PY, "a") as f:
        f.write(FUNCTION_CODE)
    print(f"[bom_variant_patch] Appended create_variant_bom_from_template to {BOM_PY}")
