import frappe


@frappe.whitelist()
def get_specifications():
	return frappe.get_all(
		"BpAK Specification",
		fields=["name", "specification_name", "drone_size"],
		order_by="specification_code",
	)


@frappe.whitelist()
def get_data(specification=None):
	if not specification:
		return {"title": "", "gs_columns": [], "rows": []}

	spec = frappe.db.get_value(
		"BpAK Specification",
		specification,
		["specification_code", "specification_name", "drone_size"],
		as_dict=True,
	)
	if not spec:
		return {"title": "", "gs_columns": [], "rows": []}

	mods = frappe.db.sql(
		"""
		SELECT m.name, m.modification_number, m.fpv_combo, m.ground_station, m.bpak_combo,
		       fpv.item_name AS fpv_name, fpv.custom_шифр AS fpv_shifr,
		       gs.custom_шифр AS gs_shifr, gs.item_name AS gs_name,
		       bpak.custom_шифр AS bpak_shifr
		FROM `tabBpAK Modification` m
		LEFT JOIN `tabItem` fpv ON fpv.name = m.fpv_combo
		LEFT JOIN `tabItem` gs ON gs.name = m.ground_station
		LEFT JOIN `tabItem` bpak ON bpak.name = m.bpak_combo
		WHERE m.specification = %s
		ORDER BY m.modification_number
		""",
		(specification,),
		as_dict=True,
	)

	gs_seen = {}
	for m in mods:
		if m["ground_station"] not in gs_seen:
			gs_seen[m["ground_station"]] = {
				"item": m["ground_station"],
				"shifr": m["gs_shifr"] or m["ground_station"],
				"name": m["gs_name"],
			}
	gs_columns = sorted(gs_seen.values(), key=lambda g: g["shifr"])

	rows = []
	for m in mods:
		cells = {g["item"]: None for g in gs_columns}
		cells[m["ground_station"]] = {
			"item": m["bpak_combo"],
			"shifr": m["bpak_shifr"] or m["bpak_combo"],
		}
		rows.append({
			"mod_num": m["modification_number"],
			"fpv_item": m["fpv_combo"],
			"fpv_name": m["fpv_name"] or m["fpv_combo"],
			"fpv_shifr": m["fpv_shifr"],
			"cells": cells,
		})

	title = f"Відомість модифікацій БпАК {spec['specification_name']} {spec['specification_code']}"
	return {
		"title": title,
		"gs_columns": gs_columns,
		"rows": rows,
	}
