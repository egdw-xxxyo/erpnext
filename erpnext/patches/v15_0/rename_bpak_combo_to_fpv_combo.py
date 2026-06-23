import frappe


def execute():
    _rename_template()
    _rename_variants()
    _rename_bundles()
    _drop_gs_from_bundles()
    frappe.db.commit()


def _rename_template():
    if frappe.db.exists("Item", "BPAK-COMBO") and not frappe.db.exists("Item", "FPV-COMBO"):
        frappe.rename_doc("Item", "BPAK-COMBO", "FPV-COMBO", force=True)
        frappe.db.set_value("Item", "FPV-COMBO", "item_name", "FPV Комплект")


def _rename_variants():
    for old in frappe.get_all("Item", filters={"name": ("like", "BPAK-COMBO-%")}, pluck="name"):
        new = old.replace("BPAK-COMBO-", "FPV-COMBO-", 1)
        if frappe.db.exists("Item", new):
            continue
        frappe.rename_doc("Item", old, new, force=True)
        frappe.db.set_value("Item", new, "variant_of", "FPV-COMBO")


def _rename_bundles():
    for old in frappe.get_all("Product Bundle", filters={"name": ("like", "BPAK-COMBO-%")}, pluck="name"):
        new = old.replace("BPAK-COMBO-", "FPV-COMBO-", 1)
        if frappe.db.exists("Product Bundle", new):
            continue
        frappe.rename_doc("Product Bundle", old, new, force=True)
        frappe.db.set_value("Product Bundle", new, "new_item_code", new)


def _drop_gs_from_bundles():
    for pb_name in frappe.get_all("Product Bundle", filters={"name": ("like", "FPV-COMBO-%")}, pluck="name"):
        pb = frappe.get_doc("Product Bundle", pb_name)
        kept = [r for r in pb.items if r.item_code != "OPT-GS-01"]
        if len(kept) != len(pb.items):
            pb.set("items", kept)
            pb.save(ignore_permissions=True)
