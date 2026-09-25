import frappe

from erpnext.manufacturing.eskd_import import ROLE_BOARD, ROLE_GROUND_STATION, ROLE_MODIFICATION_LIST


@frappe.whitelist()
def get_modification_lists():
	return frappe.get_all(
		"Specification",
		filters={"specification_kind": "Modification List", "disabled": 0},
		fields=["name", "display_code", "specification_name"],
		order_by="specification_code",
	)


@frappe.whitelist()
def get_matrix(modification_list: str | None = None):
	"""Modifications of one Відомість (rows) x the ground stations they use (columns)."""
	if not modification_list:
		return {"columns": [], "rows": [], "items": {}}

	modifications = frappe.get_all(
		"Specification Component",
		filters={
			"parenttype": "Specification",
			"role": ROLE_MODIFICATION_LIST,
			"specification": modification_list,
		},
		pluck="parent",
	)
	specs = frappe.get_all(
		"Specification",
		filters={"name": ("in", modifications or [""])},
		fields=["name", "ordinal", "display_code", "specification_name", "description"],
		order_by="ordinal",
	)
	components = _components_of([s.name for s in specs])

	rows = []
	for spec in specs:
		parts = components.get(spec.name, {})
		rows.append(
			{
				"modification": spec.name,
				"ordinal": spec.ordinal,
				"code": spec.display_code,
				"name": spec.specification_name,
				"description": spec.description,
				"board": parts.get(ROLE_BOARD),
				"ground_station": parts.get(ROLE_GROUND_STATION),
			}
		)

	ground_stations = sorted({r["ground_station"] for r in rows if r["ground_station"]})
	boards = {r["board"] for r in rows if r["board"]}
	codes = _display_codes(boards | set(ground_stations))
	for row in rows:
		row["board_code"] = codes.get(row["board"], row["board"])

	return {
		"columns": [{"name": gs, "code": codes.get(gs, gs)} for gs in ground_stations],
		"rows": rows,
		"items": _items_by_specification([r["modification"] for r in rows] + list(boards) + ground_stations),
	}


def _components_of(parents):
	if not parents:
		return {}
	by_parent = {}
	for row in frappe.get_all(
		"Specification Component",
		filters={"parenttype": "Specification", "parent": ("in", parents)},
		fields=["parent", "role", "specification"],
	):
		by_parent.setdefault(row.parent, {})[row.role] = row.specification
	return by_parent


def _display_codes(names):
	if not names:
		return {}
	return dict(
		frappe.get_all(
			"Specification",
			filters={"name": ("in", list(names))},
			fields=["name", "display_code"],
			as_list=True,
		)
	)


def _items_by_specification(specifications):
	if not specifications:
		return {}
	items = {}
	for item in frappe.get_list(
		"Item",
		filters={"specification": ("in", specifications), "disabled": 0},
		fields=["name", "item_name", "specification", "variant_of"],
		order_by="name",
	):
		items.setdefault(item.specification, []).append(
			{"name": item.name, "item_name": item.item_name, "variant_of": item.variant_of}
		)
	return items
