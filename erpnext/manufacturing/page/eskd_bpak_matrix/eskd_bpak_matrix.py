import frappe

from erpnext.manufacturing.eskd_import import (
	DOCUMENT_DOCTYPE,
	MODIFICATION_DOCTYPE,
	ROLE_BOARD,
	ROLE_GROUND_STATION,
	TYPE_MODIFICATION_LIST,
)


@frappe.whitelist()
def get_modification_lists():
	return frappe.get_list(
		DOCUMENT_DOCTYPE,
		filters={"document_type": TYPE_MODIFICATION_LIST},
		fields=["name", "document_code", "document_title"],
		order_by="document_code",
	)


@frappe.whitelist()
def get_matrix(modification_list: str | None = None):
	"""Modifications of one Відомість (rows) x the ground stations they use (columns)."""
	if not modification_list:
		return {"columns": [], "rows": [], "items": {}}

	modifications = frappe.get_list(
		MODIFICATION_DOCTYPE,
		filters={"technical_document": modification_list},
		fields=["name", "modification_number", "modification_code", "full_name", "status"],
		order_by="modification_number",
	)
	components = _components_of([m.name for m in modifications])

	rows = []
	for modification in modifications:
		parts = components.get(modification.name, {})
		rows.append(
			{
				"modification": modification.name,
				"number": modification.modification_number,
				"code": modification.modification_code,
				"name": modification.full_name,
				"status": modification.status,
				"board": parts.get(ROLE_BOARD),
				"ground_station": parts.get(ROLE_GROUND_STATION),
			}
		)

	ground_stations = sorted({r["ground_station"] for r in rows if r["ground_station"]})
	boards = {r["board"] for r in rows if r["board"]}
	codes = _display_codes(boards | set(ground_stations))
	for row in rows:
		row["board_code"] = codes.get(row["board"], row["board"])

	columns = sorted(
		({"name": gs, "code": codes.get(gs, gs)} for gs in ground_stations), key=lambda c: c["code"]
	)
	return {
		"columns": columns,
		"rows": rows,
		"items": _items_by_specification([*[r["modification"] for r in rows], *boards, *ground_stations]),
	}


def _components_of(parents):
	if not parents:
		return {}
	by_parent = {}
	for row in frappe.get_all(
		"Specification Component",
		filters={"parenttype": MODIFICATION_DOCTYPE, "parent": ("in", parents)},
		fields=["parent", "role", "specification"],
	):
		by_parent.setdefault(row.parent, {})[row.role] = row.specification
	return by_parent


def _display_codes(names):
	if not names:
		return {}
	return {
		row.name: row.display_code or row.modification_code
		for row in frappe.get_all(
			MODIFICATION_DOCTYPE,
			filters={"name": ("in", list(names))},
			fields=["name", "display_code", "modification_code"],
		)
	}


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
