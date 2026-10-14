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
from frappe.utils import now_datetime

from erpnext.manufacturing import unit_route
from erpnext.stock.additional_attributes import ROW_DOCTYPE, apply_attributes_to_serials

ATTRIBUTE = "Упаковка"
VALUE = "Упаковано"
# The name of the Additional Attribute Value record: `<attribute>: <value>`.
VALUE_NAME = f"{ATTRIBUTE}: {VALUE}"


def _after_stock_steps(bom):
	return [row for row in unit_route.route(bom) if row["after_stock"]]


def landing_warehouse(bom):
	"""Where a unit lands when it enters stock, or `None` when the BOM names no staging warehouse.

	A BOM that marks the step entering stock and names a warehouse for it gets a staging
	warehouse; the packing that follows is not a BOM operation, it is a `Packing Job`. Anything
	else keeps the old behaviour.
	"""
	if not bom:
		return None
	step = unit_route.stock_step(bom)
	if not step or not step.unit_target_warehouse:
		return None
	return step.unit_target_warehouse


def pack_target(bom, production_line=None, workplace=None):
	"""The warehouse a packed unit goes to.

	The first step after stock that names one wins; otherwise the Packaging workplace of the
	line says (`Production Line Workplace.target_warehouse`); otherwise the line's finished
	goods warehouse.
	"""
	for row in _after_stock_steps(bom):
		if row.unit_target_warehouse:
			return row.unit_target_warehouse
	return line_pack_target(production_line, workplace)


def line_pack_target(production_line, workplace=None):
	if not production_line:
		return None
	rows = frappe.get_all(
		"Production Line Workplace",
		filters={
			"parent": production_line,
			"parenttype": "Production Line",
			"enabled": 1,
			"role": "Packaging",
			**({"workplace": workplace} if workplace else {}),
		},
		fields=["target_warehouse"],
		order_by="idx",
	)
	target = next((row.target_warehouse for row in rows if row.target_warehouse), None)
	return target or frappe.db.get_value("Production Line", production_line, "fg_warehouse")


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
def start_packing_job(
	serials, workplace=None, employee=None, units_per_box=None, box_no=None, box_total=None
):
	"""Open a `Packing Job` for the serials a packer has taken from staging.

	Claims them: a serial can be in one open job only. Closed by `pack_box(..., job=name)`.
	"""
	frappe.has_permission("Packing Job", "create", throw=True)
	serials = _serial_list(serials)
	if not serials:
		frappe.throw(_("No serial numbers given"))

	line = _check_packing_workplace(workplace)
	job = frappe.get_doc(
		{
			"doctype": "Packing Job",
			"production_line": line,
			"workplace": workplace,
			"employee": employee,
			"units_per_box": units_per_box,
			"box_no": box_no,
			"box_total": box_total,
			"serials": [{"serial_no": s} for s in serials],
		}
	)
	job.insert()
	return job.name


def _check_packing_workplace(workplace):
	"""The line a Packaging workplace belongs to; refuses a workplace that packs for none."""
	if not workplace:
		return None
	rows = frappe.get_all(
		"Production Line Workplace",
		filters={"workplace": workplace, "enabled": 1, "role": "Packaging", "parenttype": "Production Line"},
		pluck="parent",
	)
	if not rows:
		frappe.throw(_("Workplace {0} is not a packaging workplace of any production line").format(workplace))
	return rows[0]


@frappe.whitelist(methods=["POST"])
def pack_box(
	serials,
	units_per_box=None,
	box_no=None,
	box_total=None,
	target_warehouse=None,
	recipe=None,
	consume_warehouse=None,
	workplace=None,
	employee=None,
	job=None,
):
	"""`pack_units` for a caller that has to hold the right to make Stock Entries."""
	frappe.has_permission("Stock Entry", "create", throw=True)
	return pack_units(
		serials,
		units_per_box=units_per_box,
		box_no=box_no,
		box_total=box_total,
		target_warehouse=target_warehouse,
		recipe=recipe,
		consume_warehouse=consume_warehouse,
		workplace=workplace,
		employee=employee,
		job=job,
	)


def pack_units(
	serials,
	units_per_box=None,
	box_no=None,
	box_total=None,
	target_warehouse=None,
	recipe=None,
	consume_warehouse=None,
	workplace=None,
	employee=None,
	job=None,
):
	"""Close one box: move its serials out of staging, issue its consumables, note the box.

	Not whitelisted and not permission-checked: the scanner script calls it on behalf of a
	packer who has no right to make Stock Entries of their own.

	All or nothing, one transaction: a serial that is not waiting in staging stops the whole
	box with a message naming it, because a half-packed box is worse than a refused one. A
	serial that is already packed is reported and skipped, so a retried scan is harmless.

	A shortage of consumables does not stop the packer: the issue is kept as a draft.
	"""
	job_doc = _open_job(job) if job else None
	serials = [row.serial_no for row in job_doc.serials] if job_doc else _serial_list(serials)
	if not serials:
		frappe.throw(_("No serial numbers given"))
	if job_doc:
		workplace = workplace or job_doc.workplace
		employee = employee or job_doc.employee

	line = _check_packing_workplace(workplace)

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
	result = {"packed": 0, "already_packed": skipped, "stock_entry": None, "consumption": None, "job": None}
	if not waiting:
		if job_doc:
			_finish_job(job_doc, None, None, status="Cancelled")
			result["job"] = job_doc.name
		return result

	line = line or _line_of(by_name[waiting[0]])
	workplace = workplace or _only_packaging_workplace(line)

	target = target_warehouse or _target_for(by_name[waiting[0]], workplace, line)
	if not target:
		frappe.throw(_("No warehouse to pack into: give one or set it on the packing step of the BOM"))

	entry = _transfer(waiting, by_name, target)
	apply_attributes_to_serials(
		waiting,
		[
			frappe._dict(
				attribute=ATTRIBUTE, value=VALUE_NAME, notes=_note(box_no, box_total, units_per_box, entry)
			)
		],
	)

	if recipe:
		consumed = _consume(recipe, len(waiting), entry, consume_warehouse)
		result["consumption"] = consumed.name if consumed else None

	job_doc = _record_job(
		job_doc,
		waiting,
		entry,
		result["consumption"],
		workplace=workplace,
		employee=employee,
		line=line,
		recipe=recipe,
		units_per_box=units_per_box,
		box_no=box_no,
		box_total=box_total,
	)
	result.update(packed=len(waiting), stock_entry=entry, job=job_doc.name)
	return result


def _line_of(serial):
	if not serial.work_order:
		return None
	return frappe.db.get_value("Work Order", serial.work_order, "production_line")


def _only_packaging_workplace(line):
	"""The line's packaging workplace when it has exactly one — the job says where it was done."""
	if not line:
		return None
	rows = frappe.get_all(
		"Production Line Workplace",
		filters={"parent": line, "parenttype": "Production Line", "enabled": 1, "role": "Packaging"},
		pluck="workplace",
	)
	return rows[0] if len(rows) == 1 else None


def _target_for(serial, workplace=None, line=None):
	work_order = (
		frappe.db.get_value("Work Order", serial.work_order, ["bom_no", "production_line"], as_dict=True)
		if serial.work_order
		else None
	)
	bom = work_order.bom_no if work_order else None
	line = line or (work_order.production_line if work_order else None)
	return pack_target(bom, line, workplace)


def _open_job(name):
	job = frappe.get_doc("Packing Job", name)
	if job.status != "In Progress":
		frappe.throw(_("Packing Job {0} is {1}, not in progress").format(name, _(job.status)))
	return job


def _record_job(job, serials, entry, consumption, **fields):
	"""Close the job the packer opened, or write one that is born done for a caller that never opened any."""
	if not job:
		job = frappe.get_doc(
			{
				"doctype": "Packing Job",
				"production_line": fields["line"],
				"workplace": fields["workplace"],
				"employee": fields["employee"],
				"recipe": fields["recipe"],
				"units_per_box": fields["units_per_box"],
				"box_no": fields["box_no"],
				"box_total": fields["box_total"],
				"serials": [{"serial_no": s} for s in serials],
			}
		)
	else:
		# Serials of the job that were already packed elsewhere are not part of this box.
		job.serials = [row for row in job.serials if row.serial_no in serials]
		job.recipe = job.recipe or fields["recipe"]
	return _finish_job(job, entry, consumption)


def _finish_job(job, entry, consumption, status="Done"):
	job.status = status
	job.finished_on = now_datetime()
	job.stock_entry = entry
	job.consumption_entry = consumption
	job.flags.ignore_permissions = True
	if job.is_new():
		job.insert()
	else:
		job.save()
	return job


def _note(box_no, box_total, units_per_box, entry):
	parts = []
	if box_no:
		parts.append(
			_("Box {0} of {1}").format(box_no, box_total) if box_total else _("Box {0}").format(box_no)
		)
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

	try:
		return consumption.consume(
			recipe,
			{"units": units},
			"Stock Entry",
			entry,
			warehouse=warehouse,
			on_shortage="draft",
		)
	except frappe.ValidationError:
		# A recipe that cannot be issued (no warehouse named, an inactive recipe) must not undo a
		# box that is already packed and labelled: say so and leave a trace.
		frappe.log_error(
			title=f"Packing: consumables of {recipe} not issued for {entry}", message=frappe.get_traceback()
		)
		frappe.msgprint(
			_("The consumables of {0} could not be issued, see the Error Log").format(recipe),
			indicator="red",
			alert=True,
		)
		return None


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

	for job in frappe.get_all(
		"Packing Job", filters={"stock_entry": doc.name, "status": "Done"}, pluck="name"
	):
		frappe.db.set_value("Packing Job", job, "status", "Cancelled")
