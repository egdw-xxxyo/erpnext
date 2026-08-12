import frappe
from frappe import _
from frappe.utils import cint

from erpnext.manufacturing.eskd_templates import ROLE_BOARD, ROLE_GROUND_STATION

BPAK_TEMPLATE = "Специфікація БпАК"


@frappe.whitelist()
def get_products():
	products = frappe.get_all("ESKD Product", filters={"disabled": 0}, pluck="name", order_by="name")
	return products


@frappe.whitelist()
def get_matrix(product=None):
	"""Drone specifications (rows) x ground-station specifications (columns).

	A cell holds the БпАК that pairs that drone with that ground station — an empty cell
	is a pairing nobody has created a modification for yet.
	"""
	rows = frappe.get_all(
		"Specification",
		filters={"specification_kind": "Board", "has_variants": 0, "disabled": 0},
		fields=["name", "specification_code", "specification_name"],
		order_by="specification_code",
	)
	columns = frappe.get_all(
		"Specification",
		filters={"specification_kind": "Ground Station", "has_variants": 0, "disabled": 0},
		fields=["name", "specification_code", "specification_name"],
		order_by="organization_code, ordinal, specification_code",
	)

	cells = {}
	for bpak in _bpak_specifications(product):
		board = bpak["components"].get(ROLE_BOARD)
		ground_station = bpak["components"].get(ROLE_GROUND_STATION)
		if board and ground_station:
			cells[(board, ground_station)] = {
				"specification": bpak["name"],
				"ordinal": bpak["ordinal"],
				"code": bpak["specification_code"],
			}

	return {
		"product": product,
		"columns": columns,
		"rows": [
			{
				"board": row.name,
				"code": row.specification_code,
				"name": row.specification_name,
				"cells": {column.name: cells.get((row.name, column.name)) for column in columns},
			}
			for row in rows
		],
	}


def _bpak_specifications(product=None):
	filters = {"specification_kind": "BpAK", "has_variants": 0}
	if product:
		filters["product"] = product
	bpaks = frappe.get_all(
		"Specification",
		filters=filters,
		fields=["name", "ordinal", "specification_code"],
	)
	if not bpaks:
		return []

	rows = frappe.get_all(
		"Specification Component",
		filters={"parent": ("in", [b.name for b in bpaks]), "parenttype": "Specification"},
		fields=["parent", "role", "specification"],
	)
	by_parent = {}
	for row in rows:
		by_parent.setdefault(row.parent, {})[row.role] = row.specification

	return [dict(b, components=by_parent.get(b.name, {})) for b in bpaks]


@frappe.whitelist()
def assign(board, ground_station, product=None):
	"""Create the БпАК that pairs this drone with this ground station."""
	frappe.has_permission("Specification", "create", throw=True)

	for bpak in _bpak_specifications(product):
		if (
			bpak["components"].get(ROLE_BOARD) == board
			and bpak["components"].get(ROLE_GROUND_STATION) == ground_station
		):
			return bpak["name"]

	if not frappe.db.exists("Specification", BPAK_TEMPLATE):
		frappe.throw(_("The БпАК specification template is missing — run the ЄСКД setup first."))

	ordinal = _next_ordinal(product)
	board_code = frappe.db.get_value("Specification", board, "specification_code")
	gs_code = frappe.db.get_value("Specification", ground_station, "specification_code")

	doc = frappe.new_doc("Specification")
	doc.variant_of = BPAK_TEMPLATE
	doc.specification_kind = "BpAK"
	doc.product = product
	doc.ordinal = ordinal
	doc.specification_name = f"{product or _('БпАК')} — модифікація {ordinal}"
	doc.specification_code = f"{board_code} / {gs_code}"
	doc.append("components", {"role": ROLE_BOARD, "specification": board})
	doc.append("components", {"role": ROLE_GROUND_STATION, "specification": ground_station})
	for row in frappe.get_all(
		"Specification Variant Attribute",
		filters={"parent": BPAK_TEMPLATE, "parenttype": "Specification"},
		fields=["attribute"],
	):
		value = frappe.db.get_value(
			"Specification Variant Attribute",
			{"parent": board, "attribute": row.attribute},
			"attribute_value",
		)
		if value:
			doc.append("attributes", {"attribute": row.attribute, "attribute_value": value})
	doc.insert()
	return doc.name


def _next_ordinal(product):
	last = frappe.get_all(
		"Specification",
		filters={"specification_kind": "BpAK", "product": product}
		if product
		else {"specification_kind": "BpAK"},
		fields=["ordinal"],
		order_by="ordinal desc",
		limit=1,
	)
	return cint(last[0].ordinal if last else 0) + 1


@frappe.whitelist()
def unassign(specification):
	"""Drop the БпАК for an intersection."""
	frappe.has_permission("Specification", "delete", throw=True)
	frappe.delete_doc("Specification", specification)
	return specification
