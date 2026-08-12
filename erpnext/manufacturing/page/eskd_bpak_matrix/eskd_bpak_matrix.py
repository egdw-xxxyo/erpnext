import frappe
from frappe import _
from frappe.utils import cint


@frappe.whitelist()
def get_products():
	"""Products that already have a modification list."""
	products = frappe.get_all(
		"ESKD BpAK Combination",
		fields=["distinct product as name"],
		order_by="product",
	)
	return [p.name for p in products]


@frappe.whitelist()
def get_matrix(product):
	"""Board specifications (rows) x ground-station specifications (columns).

	A cell holds the modification that pairs that board with that ground station, so an
	empty cell is an intersection nobody has assigned a modification number to yet.
	"""
	if not product:
		return {"rows": [], "columns": [], "unassigned": []}

	combinations = frappe.get_all(
		"ESKD BpAK Combination",
		filters={"product": product},
		fields=[
			"name",
			"modification_number",
			"board_specification",
			"ground_station_specification",
			"bpak_code",
		],
		order_by="modification_number",
	)

	board_names = [c.board_specification for c in combinations if c.board_specification]
	boards = _specifications(board_names)
	columns = frappe.get_all(
		"Specification",
		filters={"specification_kind": "Ground Station", "disabled": 0},
		fields=["name", "specification_code", "specification_name", "ordinal"],
		order_by="organization_code, ordinal, specification_code",
	)

	rows = {}
	for combination in combinations:
		board = combination.board_specification
		if not board:
			continue
		row = rows.setdefault(
			board,
			{
				"board": board,
				"code": boards.get(board, {}).get("specification_code", board),
				"name": boards.get(board, {}).get("specification_name", board),
				"cells": {},
				"free": [],
			},
		)
		if combination.ground_station_specification:
			row["cells"][combination.ground_station_specification] = {
				"combination": combination.name,
				"modification_number": combination.modification_number,
				"bpak_code": combination.bpak_code,
			}
		else:
			row["free"].append(combination.modification_number)

	return {
		"product": product,
		"columns": columns,
		"rows": sorted(rows.values(), key=lambda r: r["code"]),
	}


def _specifications(names):
	if not names:
		return {}
	rows = frappe.get_all(
		"Specification",
		filters={"name": ("in", list(set(names)))},
		fields=["name", "specification_code", "specification_name"],
	)
	return {r.name: r for r in rows}


@frappe.whitelist()
def assign(product, board, ground_station):
	"""Pair a board with a ground station, consuming the row's lowest free modification."""
	frappe.has_permission("ESKD BpAK Combination", "write", throw=True)

	taken = frappe.db.exists(
		"ESKD BpAK Combination",
		{
			"product": product,
			"board_specification": board,
			"ground_station_specification": ground_station,
		},
	)
	if taken:
		return taken

	free = frappe.get_all(
		"ESKD BpAK Combination",
		filters={
			"product": product,
			"board_specification": board,
			"ground_station_specification": ("is", "not set"),
		},
		fields=["name", "modification_number"],
		order_by="modification_number",
		limit=1,
	)
	if not free:
		frappe.throw(
			_("No unassigned modification is left for this board — add one first."),
			title=_("Modification List Exhausted"),
		)

	doc = frappe.get_doc("ESKD BpAK Combination", free[0].name)
	doc.ground_station_specification = ground_station
	doc.save()
	return doc.name


@frappe.whitelist()
def unassign(combination):
	"""Release an intersection, returning its modification number to the free pool."""
	frappe.has_permission("ESKD BpAK Combination", "write", throw=True)
	doc = frappe.get_doc("ESKD BpAK Combination", combination)
	doc.ground_station_specification = None
	doc.save()
	return doc.name


@frappe.whitelist()
def add_modification(product, board):
	"""Append a modification number to a board's list."""
	frappe.has_permission("ESKD BpAK Combination", "create", throw=True)
	last = frappe.get_all(
		"ESKD BpAK Combination",
		filters={"product": product},
		fields=["modification_number"],
		order_by="modification_number desc",
		limit=1,
	)
	doc = frappe.get_doc(
		{
			"doctype": "ESKD BpAK Combination",
			"product": product,
			"modification_number": cint(last[0].modification_number if last else 0) + 1,
			"board_specification": board,
		}
	)
	doc.insert()
	return doc.name
