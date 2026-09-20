"""The «комплект» of a modification: what ships when its designation is sold.

A modification names the designations it is built from — a board takes a coil and a
battery — and each of those is made as an Item. The kit is a non-stock Item plus a Product
Bundle listing those Items, so an order carries one line and the warehouse ships the parts.
"""

import frappe
from frappe import _

MODIFICATION_DOCTYPE = "Product Modification"
KIT_ITEM_GROUP = "Комплекти"


def _items_of(modification):
	return frappe.get_all("Item", filters={"specification": modification, "disabled": 0}, pluck="name")


def _kit_item_group():
	if frappe.db.exists("Item Group", KIT_ITEM_GROUP):
		return KIT_ITEM_GROUP
	parent = frappe.db.get_value(
		"Item Group", {"is_group": 1, "parent_item_group": ("in", ("", None))}, "name"
	)
	frappe.get_doc(
		{
			"doctype": "Item Group",
			"item_group_name": KIT_ITEM_GROUP,
			"parent_item_group": parent,
			"is_group": 0,
		}
	).insert(ignore_permissions=True)
	return KIT_ITEM_GROUP


@frappe.whitelist()
def get_kit(modification: str):
	"""What a kit for this modification would hold, and whether it already exists."""
	doc = frappe.get_doc(MODIFICATION_DOCTYPE, modification)
	parts = []
	for row in doc.components:
		parts.append(
			{
				"role": row.role,
				"modification": row.specification,
				"code": row.specification_code,
				"items": _items_of(row.specification),
			}
		)
	own = _items_of(modification)
	bundle = frappe.db.get_value("Product Bundle", {"new_item_code": ("in", own or [""])}, "name")
	return {"own_items": own, "parts": parts, "bundle": bundle}


@frappe.whitelist()
def create_kit(modification: str):
	"""Create the kit Item and its Product Bundle from the modification's components."""
	frappe.has_permission("Product Bundle", "create", throw=True)
	doc = frappe.get_doc(MODIFICATION_DOCTYPE, modification)
	if not doc.components:
		frappe.throw(_("{0} has no component modifications to build a kit from").format(modification))

	lines, missing = [], []
	for row in doc.components:
		items = _items_of(row.specification)
		if not items:
			missing.append(f"{row.role}: {row.specification_code}")
			continue
		if len(items) > 1:
			frappe.throw(
				_("{0} is made as several Items ({1}) — link only one of them to it").format(
					row.specification_code, ", ".join(items)
				)
			)
		lines.append(items[0])

	if missing:
		frappe.throw(
			_("No Item is linked to these designations yet: {0}").format(frappe.bold(", ".join(missing))),
			title=_("Kit Incomplete"),
		)

	code = doc.display_code or doc.modification_code
	item_code = f"КОМПЛЕКТ {code}"[:140]
	if not frappe.db.exists("Item", item_code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": f"Комплект {doc.full_name}"[:140],
				"item_group": _kit_item_group(),
				"stock_uom": frappe.db.get_value("UOM", {"uom_name": "Nos"}, "name")
				or frappe.db.get_value("UOM", {}, "name"),
				"is_stock_item": 0,
				"specification": modification,
				"description": f"{code} — {doc.full_name}",
			}
		).insert(ignore_permissions=True)

	existing = frappe.db.get_value("Product Bundle", {"new_item_code": item_code}, "name")
	if existing:
		return existing

	own = [name for name in _items_of(modification) if name != item_code]
	bundle = frappe.get_doc(
		{
			"doctype": "Product Bundle",
			"new_item_code": item_code,
			"description": f"{code} — {doc.full_name}",
			"items": [{"item_code": item, "qty": 1} for item in own + lines],
		}
	)
	bundle.insert(ignore_permissions=True)
	return bundle.name
