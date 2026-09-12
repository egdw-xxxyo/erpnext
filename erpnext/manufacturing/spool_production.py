"""Keep the spool line supplied with Work Orders so nobody sizes one by hand each morning.

A Work Order for a serialised item mints its Serial Nos and one Job Card per spool at
submit, and neither can be topped up afterwards: `Work Order.qty` is not `allow_on_submit`,
and `_create_job_cards_per_serial` only runs once. So a fixed daily Work Order has two bad
days — the one where the line runs out mid-shift and stops, and the one where it does not
and leaves unused serials behind.

This module removes both:

* `ensure_daily_work_orders` opens the day's Work Orders from `Spool Production Settings`.
  It is idempotent per item per day, so it can run hourly and heal a missed scheduler tick.
* `next_spool` hands the operator the next unwound spool. When none is left it creates an
  overflow Work Order on the spot, so running out is invisible to the bench.
* `close_stale_work_orders` stops yesterday's leftovers overnight, so the app cannot hand
  out a spool from a Work Order nobody is working on any more.

The serial is assigned here rather than typed at the bench: the operator is told which spool
they are winding, which is also what removes the mistyped-serial case from
`otdr_measurement_api.submit_measurement`.
"""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, today

# A card is only "free" while it is Open. Handing one out moves it to Work In Progress, so
# two operators at the same bench cannot be given the same spool.
FREE_JOB_CARD_STATUS = "Open"
CLAIMED_JOB_CARD_STATUS = "Work In Progress"
LIVE_WORK_ORDER_STATUSES = ("Not Started", "In Process")


def _settings():
	return frappe.get_cached_doc("Spool Production Settings")


def _enabled_plan(settings=None, workplace=None, item_code=None):
	settings = settings or _settings()
	rows = []
	for row in settings.plan:
		if not row.enabled:
			continue
		if workplace and row.workplace and row.workplace != workplace:
			continue
		if item_code and row.item_code != item_code:
			continue
		rows.append(row)
	return rows


def _workstations(workplace):
	"""The stations this bench covers, from `Workplace.allowed_operations`."""
	if not workplace:
		return []
	rows = frappe.get_all(
		"Workplace Operation",
		filters={"parent": workplace, "parenttype": "Workplace"},
		fields=["workstation"],
	)
	return [r.workstation for r in rows if r.workstation]


def _free_job_cards(item_code, workplace=None, limit=20):
	"""Open Job Cards holding a spool nobody has started winding yet."""
	filters = {
		"docstatus": 0,
		"status": FREE_JOB_CARD_STATUS,
		"production_item": item_code,
		"quality_inspection": ["is", "not set"],
		"serial_no": ["is", "set"],
	}
	workstations = _workstations(workplace)
	if workstations:
		filters["workstation"] = ["in", workstations]

	return frappe.get_all(
		"Job Card",
		filters=filters,
		fields=["name", "serial_no", "work_order", "workstation", "operation"],
		order_by="creation asc",
		limit=limit,
	)


def _create_work_order(item_code, qty, settings=None, reason="plan"):
	"""Submit a Work Order, which is what mints the serials and the per-spool Job Cards."""
	settings = settings or _settings()
	qty = cint(qty)
	if qty <= 0:
		return None

	bom_no = frappe.db.get_value("Item", item_code, "default_bom")
	if not bom_no:
		frappe.throw(_("Item {0} has no default BOM, cannot open a Work Order").format(item_code))

	wo = frappe.get_doc(
		{
			"doctype": "Work Order",
			"production_item": item_code,
			"bom_no": bom_no,
			"qty": qty,
			"company": settings.company or frappe.defaults.get_defaults().get("company"),
			"wip_warehouse": settings.wip_warehouse,
			"fg_warehouse": settings.fg_warehouse,
			"description": f"spool line ({reason})",
		}
	)
	# Operations are pulled by a whitelisted method the desk form calls on BOM select; without
	# it a programmatic Work Order submits with no operations and therefore no Job Cards.
	wo.get_items_and_operations_from_bom()
	wo.flags.ignore_permissions = True
	wo.insert()
	wo.submit()
	return wo


def ensure_daily_work_orders():
	"""Open today's Work Orders. Safe to run repeatedly — one per item per day."""
	settings = _settings()
	if not settings.enabled:
		return

	created = []
	skipped = []
	failed = []

	for row in _enabled_plan(settings):
		if row.daily_qty <= 0:
			continue

		already = frappe.db.exists(
			"Work Order",
			{
				"production_item": row.item_code,
				"docstatus": 1,
				"creation": [">=", today()],
			},
		)
		if already:
			skipped.append(f"{row.item_code}: {already}")
			continue

		try:
			wo = _create_work_order(row.item_code, row.daily_qty, settings)
			created.append(f"{row.item_code}: {wo.name} x{row.daily_qty}")
		except Exception as e:
			failed.append(f"{row.item_code}: {e}")
			frappe.log_error(
				title="Spool production: daily Work Order failed",
				message=f"{row.item_code}\n{frappe.get_traceback()}",
			)

	_record_run(settings, created, skipped, failed)


def _record_run(settings, created, skipped, failed):
	lines = []
	if created:
		lines.append("created: " + "; ".join(created))
	if skipped:
		lines.append("already open: " + "; ".join(skipped))
	if failed:
		lines.append("failed: " + "; ".join(failed))

	frappe.db.set_single_value(
		"Spool Production Settings",
		{"last_run_on": now_datetime(), "last_result": "\n".join(lines) or "nothing to do"},
	)
	frappe.db.commit()


@frappe.whitelist(methods=["GET"])
def get_production_plan(workplace=None, **kwargs):
	"""What this bench is supposed to wind today, and how much of it is left."""
	settings = _settings()
	if not settings.enabled:
		return {"enabled": False, "items": []}

	items = []
	for row in _enabled_plan(settings, workplace=workplace):
		free = _free_job_cards(row.item_code, workplace=row.workplace or workplace, limit=100)
		items.append(
			{
				"item_code": row.item_code,
				"item_name": frappe.db.get_value("Item", row.item_code, "item_name"),
				"workplace": row.workplace,
				"daily_qty": row.daily_qty,
				"remaining": len(free),
			}
		)

	return {"enabled": True, "overflow_qty": settings.overflow_qty, "items": items}


@frappe.whitelist(methods=["POST"])
def next_spool(workplace=None, item_code=None, **kwargs):
	"""Hand the operator the next spool to wind, opening an overflow Work Order if needed.

	Returns the serial the app then shows on screen and sends back with the measurement, so
	the spool is identified without anybody reading a number off a label.
	"""
	if not item_code:
		frappe.throw(_("Item is required"))

	settings = _settings()
	if not settings.enabled:
		frappe.throw(_("Spool production is not enabled"))

	free = _free_job_cards(item_code, workplace=workplace, limit=1)
	overflow = None

	if not free:
		overflow = _create_work_order(item_code, settings.overflow_qty or 1, settings, reason="overflow")
		free = _free_job_cards(item_code, workplace=workplace, limit=1)
		if not free:
			# The Work Order submitted but produced no usable card — a BOM without operations,
			# or an item that is not serialised. Say so rather than looping.
			frappe.throw(
				_("Work Order {0} produced no Job Card for {1}. Check the BOM operations.").format(
					overflow.name if overflow else "?", item_code
				)
			)

	card = free[0]
	serial_no = (card.serial_no or "").splitlines()[0].strip()
	frappe.db.set_value("Job Card", card.name, "status", CLAIMED_JOB_CARD_STATUS)
	frappe.db.commit()

	return {
		"serial_no": serial_no,
		"job_card": card.name,
		"work_order": card.work_order,
		"workstation": card.workstation,
		"operation": card.operation,
		"item_code": item_code,
		"overflow_work_order": overflow.name if overflow else None,
		"remaining": len(_free_job_cards(item_code, workplace=workplace, limit=100)),
	}


@frappe.whitelist(methods=["POST"])
def release_spool(job_card=None, **kwargs):
	"""Put an unwound spool back in the pool — the operator picked it up and walked away."""
	if not job_card:
		frappe.throw(_("Job Card is required"))

	card = frappe.db.get_value(
		"Job Card", job_card, ["status", "docstatus", "quality_inspection"], as_dict=True
	)
	if not card or card.docstatus != 0 or card.quality_inspection:
		return {"released": False}

	frappe.db.set_value("Job Card", job_card, "status", FREE_JOB_CARD_STATUS)
	frappe.db.commit()
	return {"released": True}


def close_stale_work_orders():
	"""Stop Work Orders left over from earlier days so no stale spool is handed out.

	Serial Nos are kept unless explicitly asked for: a gap in the numbering is cheap, and
	a nightly job that deletes records is the kind of thing that eventually deletes a real
	one.
	"""
	settings = _settings()
	if not settings.enabled or not settings.cleanup_enabled:
		return

	items = [row.item_code for row in _enabled_plan(settings)]
	if not items:
		return

	work_orders = frappe.get_all(
		"Work Order",
		filters={
			"production_item": ["in", items],
			"docstatus": 1,
			"status": ["in", LIVE_WORK_ORDER_STATUSES],
			"creation": ["<", today()],
		},
		fields=["name"],
	)

	stopped = []
	held = []
	for row in work_orders:
		# Only cards nobody ever took. A card in Work In Progress was handed to an operator,
		# and deleting it would strand its spool: the serial exists but no card can be issued
		# for it again, so it could never be measured.
		untouched = frappe.get_all(
			"Job Card",
			filters={
				"work_order": row.name,
				"docstatus": 0,
				"status": FREE_JOB_CARD_STATUS,
				"quality_inspection": ["is", "not set"],
			},
			pluck="name",
		)
		for name in untouched:
			frappe.delete_doc("Job Card", name, force=1, ignore_permissions=True)

		in_progress = frappe.db.count(
			"Job Card",
			{
				"work_order": row.name,
				"docstatus": 0,
				"status": CLAIMED_JOB_CARD_STATUS,
				"quality_inspection": ["is", "not set"],
			},
		)
		if in_progress:
			# Someone is still on it, or walked away from it. Either way stopping the Work
			# Order would block them from closing the card, so leave it and report.
			held.append(f"{row.name} ({in_progress} in progress)")
			continue

		if settings.delete_unused_serials:
			_delete_unused_serials(row.name)

		wo = frappe.get_doc("Work Order", row.name)
		wo.flags.ignore_permissions = True
		wo.update_status("Stopped")
		stopped.append(f"{row.name} ({len(untouched)} cards)")

	lines = []
	if stopped:
		lines.append("stopped: " + "; ".join(stopped))
	if held:
		lines.append("left open: " + "; ".join(held))
	if lines:
		frappe.db.set_single_value(
			"Spool Production Settings",
			{"last_run_on": now_datetime(), "last_result": "\n".join(lines)},
		)
	frappe.db.commit()


def _delete_unused_serials(work_order):
	"""Serials this Work Order minted that never carried stock."""
	serials = frappe.get_all(
		"Serial No",
		filters={"work_order": work_order, "status": ["!=", "Active"], "warehouse": ["is", "not set"]},
		pluck="name",
	)
	for name in serials:
		if frappe.db.exists("Stock Ledger Entry", {"serial_no": name}):
			continue
		frappe.delete_doc("Serial No", name, force=1, ignore_permissions=True)
