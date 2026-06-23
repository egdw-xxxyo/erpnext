import frappe

KEEP = "FPV-COMBO-15-0DA-21-13"
BPAK_CODE = "BPAK-COMBO-15-0DA-21-13"
GS_ITEM = "OPT-GS-01"


def execute():
    _delete_other_fpv_combos()
    _create_bpak_combo()
    frappe.db.commit()


def _delete_other_fpv_combos():
    for name in frappe.get_all("Item", filters=[["name", "like", "FPV-COMBO-%"], ["name", "!=", KEEP]], pluck="name"):
        if name == "FPV-COMBO":
            continue
        if frappe.db.exists("Product Bundle", name):
            frappe.delete_doc("Product Bundle", name, force=1, ignore_permissions=True, delete_permanently=True)
        frappe.delete_doc("Item", name, force=1, ignore_permissions=True, delete_permanently=True)


def _create_bpak_combo():
    src = frappe.get_doc("Item", KEEP)
    pb_src = frappe.get_doc("Product Bundle", KEEP)

    if not frappe.db.exists("Item", BPAK_CODE):
        item = frappe.get_doc({
            "doctype": "Item",
            "item_code": BPAK_CODE,
            "item_name": f"БпАК {src.item_name}",
            "item_group": src.item_group,
            "stock_uom": src.stock_uom,
            "is_stock_item": 0,
            "description": src.description,
        })
        item.insert(ignore_permissions=True)

    if not frappe.db.exists("Product Bundle", BPAK_CODE):
        items = [{"item_code": r.item_code, "qty": r.qty, "uom": r.uom} for r in pb_src.items]
        if not any(r["item_code"] == GS_ITEM for r in items) and frappe.db.exists("Item", GS_ITEM):
            items.append({"item_code": GS_ITEM, "qty": 1, "uom": "шт."})
        frappe.get_doc({
            "doctype": "Product Bundle",
            "new_item_code": BPAK_CODE,
            "description": src.description,
            "items": items,
        }).insert(ignore_permissions=True)
