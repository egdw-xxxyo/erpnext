import frappe


@frappe.whitelist()
def get_data(size="15", line="FO"):
    gs_items = frappe.db.sql(
        """
        SELECT name, item_name, custom_шифр
        FROM `tabItem`
        WHERE item_code LIKE 'OPT-GS-%%'
          AND IFNULL(custom_шифр, '') LIKE %s
        ORDER BY custom_шифр
        """,
        ("УКРП.563562.003-%С",),
        as_dict=True,
    )

    fpv_items = frappe.db.sql(
        """
        SELECT name, item_name, custom_шифр
        FROM `tabItem`
        WHERE item_code LIKE %s
          AND name != 'FPV-COMBO'
        ORDER BY name
        """,
        (f"FPV-COMBO-{size}-%",),
        as_dict=True,
    )

    fpv_components = {}
    for f in fpv_items:
        rows = frappe.db.get_all(
            "Product Bundle Item",
            filters={"parent": f["name"]},
            fields=["item_code"],
        )
        fpv_components[f["name"]] = frozenset(r["item_code"] for r in rows)

    bpak_bundles = frappe.db.sql(
        """
        SELECT parent, item_code
        FROM `tabProduct Bundle Item`
        WHERE parent LIKE 'BPAK-COMBO-%'
        """,
        as_dict=True,
    )
    bpak_by_parent = {}
    for r in bpak_bundles:
        bpak_by_parent.setdefault(r["parent"], set()).add(r["item_code"])

    rows = []
    for idx, f in enumerate(fpv_items, start=1):
        comps = fpv_components[f["name"]]
        cells = {}
        for gs in gs_items:
            target = comps | {gs["name"]}
            match_item = None
            for bpak_code, bpak_items in bpak_by_parent.items():
                if bpak_items == target:
                    match_item = bpak_code
                    break
            if match_item:
                shifr = frappe.db.get_value("Item", match_item, "custom_шифр") or match_item
                cells[gs["custom_шифр"]] = {"shifr": shifr, "item": match_item}
            else:
                cells[gs["custom_шифр"]] = None
        rows.append({
            "mod_num": idx,
            "fpv_item": f["name"],
            "name": f["item_name"] or f["name"],
            "fpv_shifr": f["custom_шифр"],
            "cells": cells,
        })

    title = f"Відомість модифікацій БпАК Укропчик {size} {line}"
    return {
        "title": title,
        "gs_columns": [{"shifr": g["custom_шифр"], "item": g["name"]} for g in gs_items],
        "rows": rows,
    }
