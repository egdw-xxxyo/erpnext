import frappe

BATT = [("12 (6S3P)","12"),("13 (6S4P)","13"),("14 (6S5P)","14"),("21 (8S4P)","21"),("22 (8S5P)","22"),("23 (8S6P)","23"),("24 (8S7P)","24")]
SPOOL = [("11 (125 0.25, 5 км)","11"),("12 (125 0.25, 10 км)","12"),("13 (125 0.25, 15 км)","13"),("21 (125 0.2, 20 км)","21"),("22 (125 0.2, 25 км)","22"),("31 (150 0.25, 15 км)","31"),("32 (150 0.25, 20 км)","32"),("33 (150 0.25, 25 км)","33"),("41 (150 0.2, 30 км)","41"),("42 (150 0.2, 40 км)","42")]


def execute():
    _cleanup_demo()
    _ensure_attr("Батарея код", BATT)
    _ensure_attr("Котушка код", SPOOL)
    _update_spec()
    _ensure_template()
    frappe.db.commit()


def _cleanup_demo():
    if frappe.db.exists("Product Bundle", "BPAK-COMBO-U15-FO-15-DA"):
        frappe.delete_doc("Product Bundle", "BPAK-COMBO-U15-FO-15-DA", force=1, ignore_permissions=True)
    if frappe.db.exists("Item", "BPAK-COMBO-U15-FO-15-DA"):
        frappe.delete_doc("Item", "BPAK-COMBO-U15-FO-15-DA", force=1, ignore_permissions=True)


def _ensure_attr(name, values):
    if frappe.db.exists("Item Attribute", name):
        d = frappe.get_doc("Item Attribute", name)
        ex = {r.attribute_value for r in d.item_attribute_values}
        added = False
        for v, a in values:
            if v not in ex:
                d.append("item_attribute_values", {"attribute_value": v, "abbr": a})
                added = True
        if added:
            d.save(ignore_permissions=True)
    else:
        frappe.get_doc({
            "doctype": "Item Attribute",
            "attribute_name": name,
            "item_attribute_values": [{"attribute_value": v, "abbr": a} for v, a in values],
        }).insert(ignore_permissions=True)


def _update_spec():
    if not frappe.db.exists("Specification Number Template", "FPV Drone Spec"):
        return
    spec = frappe.get_doc("Specification Number Template", "FPV Drone Spec")
    spec.set("components", [])
    spec.append("components", {"component_type": "Literal", "value": "УКРП.200121."})
    spec.append("components", {"component_type": "Item Attribute Short Name", "attribute_link": "Розмір рами"})
    spec.append("components", {"component_type": "Item Attribute Short Name", "attribute_link": "Тип камери"})
    spec.append("components", {"component_type": "Item Attribute Abbr", "attribute_link": "Батарея код"})
    spec.append("components", {"component_type": "Literal", "value": "00"})
    spec.append("components", {"component_type": "Item Attribute Abbr", "attribute_link": "Котушка код"})
    spec.append("components", {"component_type": "Literal", "value": "С"})
    spec.save(ignore_permissions=True)


def _ensure_template():
    if frappe.db.exists("Item", "BPAK-COMBO"):
        return
    frappe.get_doc({
        "doctype": "Item",
        "item_code": "BPAK-COMBO",
        "item_name": "БпАК Комплект FPV",
        "item_group": "Готова продукція",
        "stock_uom": "шт.",
        "is_stock_item": 0,
        "has_variants": 1,
        "variant_based_on": "Item Attribute",
        "specification_number_template": "FPV Drone Spec",
        "attributes": [
            {"attribute": "Розмір рами"},
            {"attribute": "Тип камери"},
            {"attribute": "Батарея код"},
            {"attribute": "Котушка код"},
        ],
    }).insert(ignore_permissions=True)
