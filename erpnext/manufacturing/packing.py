"""Packing a unit that is already in stock.

A unit that goes through a BOM with a step marked `enters_stock` lands in the warehouse that
step names (`BOM Operation.unit_target_warehouse`) — the staging warehouse, where it is stock
but not yet sellable. Packing moves it on to the warehouse the next step names. The
warehouse is the truth: stock reports, reservations and serial pickers already know where a
unit is. The «Упаковка» attribute on the Serial No is only a note on top of that (which box,
how many in it) and no decision is ever taken from it.

`block_unpacked_delivery` is the one place that stops a unit in staging from leaving.
"""

import json

import frappe
from frappe import _

from erpnext.manufacturing import unit_route
from erpnext.stock.additional_attributes import ROW_DOCTYPE, apply_attributes_to_serials

ATTRIBUTE = "Упаковка"
VALUE = "Упаковано"


def _after_stock_steps(bom):
	return [row for row in unit_route.route(bom) if row["after_stock"]]


def landing_warehouse(bom):
	"""Where a unit lands when it enters stock, or `None` when the BOM has no packing route.

	Only a BOM that marks the step, names a warehouse for it and has a step after it gets a
	staging warehouse. Anything else keeps the old behaviour.
	"""
	if not bom:
		return None
	step = unit_route.stock_step(bom)
	if not step or not step.unit_target_warehouse or not _after_stock_steps(bom):
		return None
	return step.unit_target_warehouse


def pack_target(bom):
	"""The warehouse the first step after stock puts the unit in."""
	for row in _after_stock_steps(bom):
		if row.unit_target_warehouse:
			return row.unit_target_warehouse
	return None


def staging_warehouses():
	"""Every warehouse a unit waits in for packing, across the BOMs that have a route."""
	marked = frappe.get_all(
		"BOM Operation",
		filters={"parenttype": "BOM", "enters_stock": 1, "unit_target_warehouse": ["is", "set"]},
		fields=["parent", "unit_target_warehouse"],
	)
	return {row.unit_target_warehouse for row in marked if landing_warehouse(row.parent)}


def _serial_list(serials):
	if isinstance(serials, str):
		try:
			serials = json.loads(serials)
		except ValueError:
			serials = serials.splitlines()
	return list(dict.fromkeys(s.strip() for s in serials or [] if s and s.strip()))


def _already_packed(serials):
	rows = frappe.get_all(
		ROW_DOCTYPE,
		filters={"parenttype": "Serial No", "parent": ["in", serials], "attribute": ATTRIBUTE},
		fields=["parent"],
	)
	return {row.parent for row in rows}


@frappe.whitelist(methods=["POST"])
def pack_box(
	serials,
	units_per_box=None,
	box_no=None,
	box_total=None,
	target_warehouse=None,
	recipe=None,
	consume_warehouse=None,
):
	"""Close one box: move its serials out of staging, issue its consumables, note the box.

	All or nothing, one transaction: a serial that is not waiting in staging stops the whole
	box with a message naming it, because a half-packed box is worse than a refused one. A
	serial that is already packed is reported and skipped, so a retried scan is harmless.

	A shortage of consumables does not stop the packer: the issue is kept as a draft.
	"""
	frappe.has_permission("Stock Entry", "create", throw=True)

	serials = _serial_list(serials)
	if not serials:
		frappe.throw(_("No serial numbers given"))

	rows = frappe.get_all(
		"Serial No",
		filters={"name": ["in", serials]},
		fields=["name", "item_code", "warehouse", "work_order"],
	)
	by_name = {row.name: row for row in rows}
	unknown = [s for s in serials if s not in by_name]
	if unknown:
		frappe.throw(_("Unknown serial numbers: {0}").format(", ".join(unknown)))

	staging = staging_warehouses()
	packed_before = _already_packed(serials)
	skipped = [s for s in serials if s in packed_before and by_name[s].warehouse not in staging]
	waiting = [s for s in serials if s not in skipped]
	wrong = [s for s in waiting if by_name[s].warehouse not in staging]
	if wrong:
		frappe.throw(
			_("Not waiting for packing: {0}").format(
				", ".join(f"{s} ({by_name[s].warehouse or _('no warehouse')})" for s in wrong)
			)
		)
	result = {"packed": 0, "already_packed": skipped, "stock_entry": None, "consumption": None}
	if not waiting:
		return result

	target = target_warehouse or _target_for(by_name[waiting[0]])
	if not target:
		frappe.throw(_("No warehouse to pack into: give one or set it on the packing step of the BOM"))

	entry = _transfer(waiting, by_name, target)
	apply_attributes_to_serials(
		waiting,
		[frappe._dict(attribute=ATTRIBUTE, value=VALUE, notes=_note(box_no, box_total, units_per_box, entry))],
	)

	if recipe:
		consumed = _consume(recipe, len(waiting), entry, consume_warehouse)
		result["consumption"] = consumed.name if consumed else None

	result.update(packed=len(waiting), stock_entry=entry)
	return result


def _target_for(serial):
	bom = frappe.db.get_value("Work Order", serial.work_order, "bom_no") if serial.work_order else None
	return pack_target(bom)


def _note(box_no, box_total, units_per_box, entry):
	parts = []
	if box_no:
		parts.append(_("Box {0} of {1}").format(box_no, box_total) if box_total else _("Box {0}").format(box_no))
	if units_per_box:
		parts.append(_("{0} pcs").format(units_per_box))
	parts.append(entry)
	return ", ".join(parts)


def _transfer(serials, by_name, target):
	groups = {}
	for serial in serials:
		row = by_name[serial]
		groups.setdefault((row.item_code, row.warehouse), []).append(serial)

	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = "Material Transfer"
	entry.purpose = "Material Transfer"
	entry.company = frappe.get_cached_value("Warehouse", target, "company")
	for (item_code, source), group in groups.items():
		entry.append(
			"items",
			{
				"item_code": item_code,
				"qty": len(group),
				"s_warehouse": source,
				"t_warehouse": target,
				"use_serial_batch_fields": 1,
				"serial_no": "\n".join(group),
			},
		)
	entry.flags.ignore_permissions = True
	entry.insert()
	entry.submit()
	return entry.name


def _consume(recipe, units, entry, warehouse):
	from erpnext.manufacturing import consumption

	return consumption.consume(
		recipe,
		{"units": units},
		"Stock Entry",
		entry,
		warehouse=warehouse,
		on_shortage="draft",
	)


def delivered_serials(doc):
	"""Serial numbers a delivery document ships, from its bundles and its legacy text field."""
	serials = set()
	bundles = [row.serial_and_batch_bundle for row in doc.get("items") or [] if row.serial_and_batch_bundle]
	if bundles:
		serials.update(
			row.serial_no
			for row in frappe.get_all(
				"Serial and Batch Entry",
				filters={"parent": ["in", bundles], "serial_no": ["is", "set"]},
				fields=["serial_no"],
			)
		)
	for row in doc.get("items") or []:
		serials.update(s.strip() for s in (row.get("serial_no") or "").splitlines() if s.strip())
	return serials


def block_unpacked_delivery(doc, method=None):
	"""`doc_events` hook on Delivery Note: a unit still in staging is not ready to be sold."""
	serials = delivered_serials(doc)
	if not serials:
		return

	staging = staging_warehouses()
	if not staging:
		return

	waiting = frappe.get_all(
		"Serial No",
		filters={"name": ["in", list(serials)], "warehouse": ["in", list(staging)]},
		pluck="name",
	)
	if waiting:
		frappe.throw(
			_("Not packed yet, cannot be delivered: {0}").format(", ".join(sorted(waiting))),
			title=_("Units waiting for packing"),
		)


def unpack_on_cancel(doc, method=None):
	"""`doc_events` hook on Stock Entry: cancelling a packing transfer removes its note.

	The warehouse already went back with the transfer; the attribute is a note on top of it
	and has to follow, or the serial would say "packed" while standing in staging.
	"""
	rows = frappe.get_all(
		ROW_DOCTYPE,
		filters={
			"parenttype": "Serial No",
			"attribute": ATTRIBUTE,
			"notes": ["like", f"%{doc.name}"],
		},
		pluck="name",
	)
	for name in rows:
		frappe.delete_doc(ROW_DOCTYPE, name, ignore_permissions=True, force=True)
