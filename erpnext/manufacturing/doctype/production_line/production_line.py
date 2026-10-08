"""Keep a continuously running line supplied with Work Orders.

A Work Order for a serialised item mints its Serial Nos and one Job Card per unit at submit,
and neither can be topped up afterwards: `Work Order.qty` is not `allow_on_submit`, and
`_create_job_cards_per_serial` only runs once. So a fixed daily Work Order has two bad days —
the one where the line runs out mid-shift and stops, and the one where it does not and leaves
unused serials behind.

Each `Production Line` removes both for the items on its plan:

* `ensure_daily_work_orders` opens the day's Work Orders. It is idempotent per item per day,
  so it can run hourly and heal a missed scheduler tick.
* `next_unit` hands the operator the next free Job Card. When none is left it creates an
  overflow Work Order on the spot, so running out is invisible to the bench.
* `finish_unit` closes the unit's Job Card and posts its Manufacture entry for exactly that
  serial, so a finished unit reaches the finished-goods warehouse without desk work.
* `close_stale_work_orders` closes the day: units nobody started lose their cards and
  serials, and each Daily Work Order shrinks to the units that were started.

Nothing here knows what the line makes. `Line Type` is what a client asks for — the spool
app calls `erpnext.manufacturing.spool_production`, which passes "Spool" — so a second kind
of line reuses this engine and only adds its own client endpoints.
"""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime, today

from erpnext.devices.session_user import acting_as

# A card is only "free" while it is Open. Handing one out moves it to Work In Progress, so
# two operators at the same bench cannot be given the same unit.
FREE_JOB_CARD_STATUS = "Open"
CLAIMED_JOB_CARD_STATUS = "Work In Progress"
LIVE_WORK_ORDER_STATUSES = ("Not Started", "In Process")


class ProductionLine(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.manufacturing.doctype.production_line_item.production_line_item import (
			ProductionLineItem,
		)
		from erpnext.manufacturing.doctype.production_line_workplace.production_line_workplace import (
			ProductionLineWorkplace,
		)

		cleanup_enabled: DF.Check
		cleanup_time: DF.Time | None
		company: DF.Link | None
		enabled: DF.Check
		fg_warehouse: DF.Link | None
		last_cleanup_on: DF.Datetime | None
		last_cleanup_result: DF.SmallText | None
		last_result: DF.SmallText | None
		last_run_on: DF.Datetime | None
		line_name: DF.Data
		line_type: DF.Literal["Spool"]
		manufacture_at_packing: DF.Check
		overflow_qty: DF.Int
		plan: DF.Table[ProductionLineItem]
		plan_time: DF.Time
		reject_warehouse: DF.Link | None
		source_warehouse: DF.Link | None
		wip_warehouse: DF.Link | None
		workplaces: DF.Table[ProductionLineWorkplace]

	def validate(self):
		self._validate_workplaces()

		for row in self.plan:
			if row.daily_qty < 0:
				frappe.throw(_("Daily Qty cannot be negative (row {0})").format(row.idx))

		# Both times fall on the same calendar day: closing the day stops every Work Order
		# opened before it, so a close that came before the plan would stop the day's own
		# Work Orders the moment they were opened.
		if (
			self.cleanup_enabled
			and self.plan_time
			and self.cleanup_time
			and _moment(self.cleanup_time) <= _moment(self.plan_time)
		):
			frappe.throw(_("Close Day At must be later than Plan At"))

		if self.enabled:
			self._validate_items_not_on_other_lines()
			self._validate_workplaces_not_on_other_lines()

	def _validate_workplaces(self):
		"""The line's benches, and the plan rows that must stay inside them.

		The workplace list is what the clients offer, so a plan row naming a bench the line
		does not run at would be unreachable from the app.
		"""
		seen = set()
		for row in self.workplaces:
			if row.workplace in seen:
				frappe.throw(_("Workplace {0} is listed more than once").format(row.workplace))
			seen.add(row.workplace)

		allowed = {row.workplace for row in self.workplaces if row.enabled}
		if not allowed:
			return

		for row in self.plan:
			if not row.enabled:
				continue
			if not row.workplace:
				frappe.throw(_("Row {0}: Workplace is required").format(row.idx))
			if row.workplace not in allowed:
				frappe.throw(
					_("Row {0}: workplace {1} is not one of this line's workplaces").format(
						row.idx, row.workplace
					)
				)

	def _validate_workplaces_not_on_other_lines(self):
		"""A bench belongs to one enabled line per line type.

		The app asks for the workplaces of a line type and gets a flat list, and `next_unit`
		resolves the line from the item plus the bench — two enabled lines of the same type at
		one bench would make both ambiguous.
		"""
		for row in self.workplaces:
			if not row.enabled:
				continue
			other = frappe.db.sql(
				"""
				select line.name
				from `tabProduction Line` line
				join `tabProduction Line Workplace` wp on wp.parent = line.name
					and wp.parenttype = 'Production Line'
				where line.enabled = 1 and wp.enabled = 1 and line.name != %s
					and line.line_type = %s and wp.workplace = %s
				limit 1
				""",
				(self.name or "", self.line_type, row.workplace),
			)
			if other:
				frappe.throw(
					_("Workplace {0} already belongs to production line {1}").format(
						row.workplace, other[0][0]
					)
				)

	def _validate_items_not_on_other_lines(self):
		"""An item at a workplace belongs to one line.

		Work Orders carry no link back to their line, so the daily check and the overflow both
		find a line's Work Orders by item. Two lines planning the same item at the same bench
		would each count the other's Work Order as their own.
		"""
		for row in self.plan:
			if not row.enabled:
				continue
			other = frappe.db.sql(
				"""
				select line.name
				from `tabProduction Line` line
				join `tabProduction Line Item` item on item.parent = line.name
					and item.parenttype = 'Production Line'
				where line.enabled = 1 and item.enabled = 1 and line.name != %s
					and item.item_code = %s and ifnull(item.workplace, '') = %s
				limit 1
				""",
				(self.name or "", row.item_code, row.workplace or ""),
			)
			if other:
				frappe.throw(
					_("Row {0}: item {1} at workplace {2} is already planned on production line {3}").format(
						row.idx, row.item_code, row.workplace or "-", other[0][0]
					)
				)


def _enabled_lines(line_type=None):
	filters = {"enabled": 1}
	if line_type:
		filters["line_type"] = line_type
	return [
		frappe.get_cached_doc("Production Line", name)
		for name in frappe.get_all("Production Line", filters=filters, pluck="name")
	]


def _plan_rows(line, workplace=None, item_code=None):
	rows = []
	for row in line.plan:
		if not row.enabled:
			continue
		if workplace and row.workplace and row.workplace != workplace:
			continue
		if item_code and row.item_code != item_code:
			continue
		rows.append(row)
	return rows


def _line_for_item(item_code):
	"""The enabled line that plans this item, whatever its type — or None.

	`_line_for` needs the caller to know the line type. Code reached from a Job Card (a
	finished unit, a packed unit) only knows the item, and a missing line is not an error
	there: it means "no line rules apply", not "refuse the unit".
	"""
	for line in _enabled_lines():
		if _plan_rows(line, item_code=item_code):
			return line
	return None


def _line_for(line_type, item_code, workplace=None):
	for line in _enabled_lines(line_type):
		if _plan_rows(line, workplace=workplace, item_code=item_code):
			return line
	frappe.throw(_("No enabled production line of type {0} plans item {1}").format(_(line_type), item_code))


def line_workplaces(line_type=None, production_line=None):
	"""The benches the enabled lines run at — what a client's workplace picker may offer.

	Empty means no line restricts its benches, which the caller reads as "no filter" rather
	than "no bench": a line set up before the workplace table existed keeps working.
	"""
	lines = (
		[frappe.get_cached_doc("Production Line", production_line)]
		if production_line
		else _enabled_lines(line_type)
	)
	names = []
	for line in lines:
		for row in line.workplaces:
			if row.enabled and row.workplace and row.workplace not in names:
				names.append(row.workplace)
	return names


@frappe.whitelist()
def lines_for_workplace(workplace):
	"""The lines that run at this bench — read-only display on the Workplace form."""
	if not workplace:
		return []
	return frappe.db.sql(
		"""
		select line.name, line.line_name, line.line_type, line.enabled
		from `tabProduction Line` line
		join `tabProduction Line Workplace` wp on wp.parent = line.name
			and wp.parenttype = 'Production Line'
		where wp.workplace = %s and wp.enabled = 1
		order by line.name
		""",
		(workplace,),
		as_dict=True,
	)


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
	"""Open Job Cards holding a unit nobody has started on yet."""
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


def _unfinished_job_cards(item_code=None, workplace=None, limit=20):
	"""Units already measured but never closed — the bench walked away from them.

	`_free_job_cards` deliberately skips a card that carries a Quality Inspection, so once a
	measured unit leaves the operator's hand it can never be handed out again: it is not in
	stock, it still counts against the plan, and nothing in the app points at it. These are
	those cards, so `next_unit` can give one back instead of minting more work.
	"""
	filters = {
		"docstatus": 0,
		"quality_inspection": ["is", "set"],
		"serial_no": ["is", "set"],
	}
	if item_code:
		filters["production_item"] = item_code
	workstations = _workstations(workplace)
	if workstations:
		filters["workstation"] = ["in", workstations]

	cards = frappe.get_all(
		"Job Card",
		filters=filters,
		fields=[
			"name",
			"serial_no",
			"work_order",
			"workstation",
			"operation",
			"production_item",
			"quality_inspection",
			"creation",
		],
		order_by="creation asc",
		limit=limit,
	)
	# A card whose Work Order was stopped overnight cannot be submitted, so handing it back
	# would replace one loop with another. Those belong to whoever reopens the Work Order.
	return [
		card
		for card in cards
		if frappe.db.get_value("Work Order", card.work_order, "status") in LIVE_WORK_ORDER_STATUSES
	]


def _create_work_order(line, item_code, qty, reason="plan"):
	"""Submit a Work Order, which is what mints the serials and the per-unit Job Cards."""
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
			"company": line.company or frappe.defaults.get_defaults().get("company"),
			# `Work Order.set_warehouses` copies this only onto rows the BOM left blank, so a row
			# that names its own warehouse keeps it.
			"source_warehouse": line.source_warehouse,
			"wip_warehouse": line.wip_warehouse,
			"fg_warehouse": line.fg_warehouse,
			"description": f"{line.name} ({reason})",
			"production_line": line.name,
			"line_order_type": "Daily",
			"planned_qty": qty,
		}
	)
	# Operations are pulled by a whitelisted method the desk form calls on BOM select; without
	# it a programmatic Work Order submits with no operations and therefore no Job Cards.
	wo.get_items_and_operations_from_bom()
	wo.flags.ignore_permissions = True
	wo.insert()
	# Submit mints Serial Nos and Job Cards inside stock code that inserts them without
	# `ignore_permissions`, so an operator without a manufacturing role taking an overflow
	# spool got a PermissionError on Job Card. The operator's right to the bench is already
	# checked by the caller.
	with acting_as("Administrator"):
		wo.submit()
	_clear_planned_slots(wo.name)
	return wo


def _clear_planned_slots(work_order):
	"""Drop the capacity-planning slots ERPNext booked for this Work Order's Job Cards.

	With capacity planning on, every per-serial card gets its own slot, laid end to end on
	the workstation. The line does not follow that schedule — an operator takes whichever
	unit is next — and `JobCard.get_overlap_for` counts those slots, so the first real time
	log on any card collides with another card's imaginary one and the card cannot be closed.
	"""
	cards = frappe.get_all("Job Card", filters={"work_order": work_order, "docstatus": 0}, pluck="name")
	if cards:
		frappe.db.delete("Job Card Scheduled Time", {"parent": ["in", cards]})


def _moment(time_value, day=None):
	"""A line's time-of-day on `day` (today by default), as a datetime."""
	return get_datetime(f"{day or today()} {time_value}")


def _due(time_value, last_done_on, now):
	"""Whether a once-a-day job at `time_value` should run at `now`.

	Due once the time has come round today and it has not already run since that moment.
	A missed tick therefore heals on the next one, and a restart does not repeat the job.
	"""
	if not time_value:
		return False
	moment = _moment(time_value, now.date())
	return now >= moment and (not last_done_on or get_datetime(last_done_on) < moment)


def run_schedule():
	"""Scheduler tick: open or close the day on every line whose time has come."""
	now = now_datetime()
	for line in _enabled_lines():
		if _due(line.plan_time, line.last_run_on, now):
			ensure_daily_work_orders(line=line.name)
		if line.cleanup_enabled and _due(line.cleanup_time, line.last_cleanup_on, now):
			close_stale_work_orders(line=line.name)


def ensure_daily_work_orders(line=None):
	"""Open today's Work Orders. Safe to run repeatedly — one per item per day.

	Runs for one line when named, otherwise for every enabled line regardless of its plan
	time — the unconditional form is for a manager starting the day by hand.
	"""
	lines_to_run = [frappe.get_doc("Production Line", line)] if line else _enabled_lines()
	for line in lines_to_run:
		created, skipped, failed = [], [], []

		for row in _plan_rows(line):
			if row.daily_qty <= 0:
				continue

			already = frappe.db.exists(
				"Work Order",
				{"production_item": row.item_code, "docstatus": 1, "creation": [">=", today()]},
			)
			if already:
				skipped.append(f"{row.item_code}: {already}")
				continue

			try:
				wo = _create_work_order(line, row.item_code, row.daily_qty)
				created.append(f"{row.item_code}: {wo.name} x{row.daily_qty}")
			except Exception as e:
				frappe.db.rollback()
				failed.append(f"{row.item_code}: {e}")
				frappe.log_error(
					title=f"Production line {line.name}: daily Work Order failed",
					message=f"{row.item_code}\n{frappe.get_traceback()}",
				)

		lines = []
		if created:
			lines.append("created: " + "; ".join(created))
		if skipped:
			lines.append("already open: " + "; ".join(skipped))
		if failed:
			lines.append("failed: " + "; ".join(failed))

		stamp = {"last_result": "\n".join(lines) or "nothing to do"}
		# A failed item keeps the day unplanned, so the next tick tries again instead of the
		# line waiting until tomorrow.
		if not failed:
			stamp["last_run_on"] = now_datetime()
		frappe.db.set_value("Production Line", line.name, stamp, update_modified=False)
		frappe.db.commit()


def get_plan(line_type, workplace=None):
	"""What this bench is supposed to make today, and how much of it is left."""
	items = []
	for line in _enabled_lines(line_type):
		for row in _plan_rows(line, workplace=workplace):
			free = _free_job_cards(row.item_code, workplace=row.workplace or workplace, limit=100)
			items.append(
				{
					"production_line": line.name,
					"item_code": row.item_code,
					"item_name": frappe.db.get_value("Item", row.item_code, "item_name"),
					"workplace": row.workplace,
					"daily_qty": row.daily_qty,
					"overflow_qty": line.overflow_qty,
					"remaining": len(free),
				}
			)

	return {"enabled": bool(items), "items": items}


def next_unit(line_type, workplace=None, item_code=None):
	"""Hand the operator the next unit, opening an overflow Work Order if needed."""
	if not item_code:
		frappe.throw(_("Item is required"))

	line = _line_for(line_type, item_code, workplace=workplace)

	# An unfinished measured unit is handed back before any new one. Whoever is at the bench
	# has to close it, otherwise it stays out of stock forever and the plan never drains.
	stranded = _unfinished_job_cards(item_code, workplace=workplace, limit=20)
	stranded = _close_abandoned_rejects(stranded)
	if stranded:
		card = stranded[0]
		return {
			"production_line": line.name,
			"serial_no": (card.serial_no or "").splitlines()[0].strip(),
			"job_card": card.name,
			"work_order": card.work_order,
			"workstation": card.workstation,
			"operation": card.operation,
			"item_code": item_code,
			"overflow_work_order": None,
			"resumed": True,
			"remaining": len(_free_job_cards(item_code, workplace=workplace, limit=100)),
		}

	free = _free_job_cards(item_code, workplace=workplace, limit=1)
	overflow = None

	if not free:
		overflow = _create_work_order(line, item_code, line.overflow_qty or 1, reason="overflow")
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
	# The claim time becomes the start of the time log `finish_unit` writes.
	frappe.db.set_value(
		"Job Card",
		card.name,
		{"status": CLAIMED_JOB_CARD_STATUS, "actual_start_date": now_datetime()},
	)
	frappe.db.commit()

	return {
		"production_line": line.name,
		"serial_no": serial_no,
		"job_card": card.name,
		"work_order": card.work_order,
		"workstation": card.workstation,
		"operation": card.operation,
		"item_code": item_code,
		"overflow_work_order": overflow.name if overflow else None,
		"resumed": False,
		"remaining": len(_free_job_cards(item_code, workplace=workplace, limit=100)),
	}


def _close_abandoned_rejects(cards):
	"""Close yesterday's rejected units instead of handing them back to the bench.

	A unit rejected at the bench needs no decision from the operator — `finish_unit` closes it
	and posts it to the reject warehouse whatever they press. Handing it back days later only
	shows them a serial they have never seen, in front of a dialog that says the spool is
	scrap; meanwhile the unit sits out of stock. A reject from today is left alone: the spool
	is still in the operator's hand and may yet be rewound and measured again.
	"""
	live = []
	for card in cards:
		if getdate(card.get("creation")) < getdate(today()) and _is_rejected(card.quality_inspection):
			try:
				finish_unit(card.name)
				continue
			except Exception:
				frappe.log_error(
					title="Production Line: could not close abandoned reject",
					message=frappe.get_traceback(),
				)
		live.append(card)
	return live


def release_unit(job_card):
	"""Put an untouched unit back in the pool — the operator took it and walked away."""
	if not job_card:
		frappe.throw(_("Job Card is required"))

	card = frappe.db.get_value(
		"Job Card", job_card, ["status", "docstatus", "quality_inspection"], as_dict=True
	)
	if not card:
		return {"released": False, "reason": "missing"}
	if card.docstatus != 0:
		return {"released": False, "reason": "closed"}
	if card.quality_inspection:
		# A measured unit cannot go back in the pool: the free-card query skips anything with
		# an inspection, so releasing it here would strand it. It has to be finished.
		return {"released": False, "reason": "measured", "quality_inspection": card.quality_inspection}

	frappe.db.set_value("Job Card", job_card, "status", FREE_JOB_CARD_STATUS)
	frappe.db.commit()
	return {"released": True}


def _inspection_required(card):
	"""Mirrors `JobCard.validate_inspection`: both the BOM and the operation must ask for it."""
	return bool(
		frappe.db.get_value("BOM", card.bom_no, "inspection_required")
		and frappe.db.get_value("Work Order Operation", card.operation_id, "quality_inspection_required")
	)


def finish_unit(job_card):
	"""Close a unit's Job Card and put the unit into stock.

	A rejected unit is not closed — `JobCard.validate_inspection` would refuse anyway — and
	stays on its card for whoever decides what happens to it. The caller is told, so it can
	clear the bench either way. All writes share the request's transaction: if the
	Manufacture entry fails, the Job Card submit is rolled back with it.
	"""
	if not job_card:
		frappe.throw(_("Job Card is required"))

	card = frappe.get_doc("Job Card", job_card)
	serial_no = (card.serial_no or "").splitlines()[0].strip() if card.serial_no else None
	result = {"job_card": card.name, "serial_no": serial_no, "work_order": card.work_order}

	verdict = None
	if card.quality_inspection:
		qi_status, qi_docstatus = frappe.db.get_value(
			"Quality Inspection", card.quality_inspection, ["status", "docstatus"]
		)
		if qi_docstatus != 1:
			frappe.throw(_("Quality Inspection {0} is not submitted").format(card.quality_inspection))
		if qi_status == "Rejected":
			# A rejected unit is still a unit: the materials went into it and it physically
			# exists, so it is manufactured like any other and lands in the line's reject
			# warehouse instead of finished goods. Its card closes either way — leaving it in
			# draft is what made a rejected unit immortal, since the free-card query skips a
			# card with an inspection and `next_unit` had nothing else to offer the bench.
			if card.docstatus == 0:
				_complete_job_card(card, rejected=True)
			line = _line_for_item(card.production_item)
			reject_warehouse = line.reject_warehouse if line else None
			stock_entry = card.auto_stock_entry
			if reject_warehouse and (
				not stock_entry or frappe.db.get_value("Stock Entry", stock_entry, "docstatus") != 1
			):
				# A rejected unit is finished here and nowhere else: it is not packed, so the
				# packing card would stay open forever, and `Stock Entry.check_if_operations_
				# completed` refuses a Manufacture entry while any operation of the Work Order
				# is still open. Closing the unit's remaining cards is what makes the rejected
				# unit a one-stop affair at the bench rather than a second flow for the
				# scanner at packing.
				_close_remaining_cards(serial_no, skip=card.name)
				stock_entry = _post_manufacture(
					card, serial_no, target_warehouse=reject_warehouse, rejected=True
				)
			frappe.db.commit()
			return {
				**result,
				"finished": False,
				"closed": True,
				"verdict": "Fail",
				"stock_entry": stock_entry if reject_warehouse else None,
				"warehouse": reject_warehouse,
			}
		verdict = "Pass"
	elif _inspection_required(card):
		frappe.throw(_("{0} has not passed quality inspection yet").format(serial_no or card.name))

	if card.docstatus == 0:
		_complete_job_card(card)

	# A line that finishes into stock at packing leaves the unit out of stock here on purpose:
	# `Stock Entry.check_if_operations_completed` refuses a Manufacture entry while any
	# operation of the Work Order is still open, and packing is one of those operations.
	line = _line_for_item(card.production_item)
	deferred = bool(line and line.manufacture_at_packing)

	stock_entry = card.auto_stock_entry
	if deferred:
		stock_entry = None
	elif not stock_entry or frappe.db.get_value("Stock Entry", stock_entry, "docstatus") != 1:
		stock_entry = _post_manufacture(card, serial_no)

	frappe.db.commit()
	return {
		**result,
		"finished": True,
		"verdict": verdict,
		"stock_entry": stock_entry,
		"manufacture_deferred": deferred,
		"warehouse": frappe.db.get_value("Serial No", serial_no, "warehouse") if serial_no else None,
	}


def _complete_job_card(card, rejected=False):
	"""One time log from the claim to now for the whole card, then submit.

	`rejected` closes a card whose inspection failed. `JobCard.on_submit` refuses that while
	Stock Settings says `Stop` for a rejected inspection — a rule written for a card that is
	about to move stock, which this one never does: `finish_unit` posts no Manufacture entry
	for a rejected unit. The two checks that gate are worth keeping (the inspection exists,
	and it is submitted) have already run in `finish_unit`, so the instance-level override is
	the whole of what is skipped.
	"""
	from erpnext.manufacturing.doctype.job_card.job_card import OverlapError

	if rejected:
		card.validate_inspection = lambda: None
		card.flags.skip_auto_stock_entry = True

	now = now_datetime()
	start = get_datetime(card.actual_start_date) if card.actual_start_date else now
	if start > now:
		start = now
	if rejected and not card.actual_start_date:
		# Nobody ever started this one — it is being closed because the unit was rejected
		# upstream — so it gets a zero-length log instead of an invented shift.
		start = now

	card.append("time_logs", {"from_time": start, "to_time": now, "completed_qty": card.for_quantity})
	card.flags.ignore_permissions = True
	try:
		card.save()
	except OverlapError:
		# Every card of a Work Order is created on the BOM's workstation, while operators
		# actually work on several machines at once — so two real jobs can overlap on paper.
		# The inspection, not the timesheet, is what gates the unit; keep the finish time and
		# drop the duration rather than strand a finished unit.
		card.reload()
		card.append("time_logs", {"from_time": now, "to_time": now, "completed_qty": card.for_quantity})
		card.flags.ignore_permissions = True
		card.save()
	card.submit()


def _is_rejected(quality_inspection):
	"""True when this inspection exists, is submitted and failed."""
	if not quality_inspection:
		return False
	row = frappe.db.get_value("Quality Inspection", quality_inspection, ["status", "docstatus"], as_dict=True)
	return bool(row and row.docstatus == 1 and row.status == "Rejected")


def _rejected_inspection(serial_no):
	"""The rejected Quality Inspection of this unit, if it has one."""
	rows = frappe.get_all(
		"Job Card",
		filters={"serial_no": serial_no, "quality_inspection": ["is", "set"]},
		fields=["quality_inspection"],
		order_by="creation desc",
		limit=1,
	)
	if not rows:
		return None
	qi = rows[0].quality_inspection
	status, docstatus = frappe.db.get_value("Quality Inspection", qi, ["status", "docstatus"])
	return qi if docstatus == 1 and status == "Rejected" else None


def _close_remaining_cards(serial_no, skip=None):
	"""Close every other open Job Card of this serial — the unit is going no further.

	Only reached for a rejected unit. The operations it skips (packing, and anything else the
	BOM lists after the bench) were never performed, so each card is closed with a zero-length
	time log rather than pretending someone worked it.
	"""
	names = frappe.get_all(
		"Job Card",
		filters={"serial_no": serial_no, "docstatus": 0},
		pluck="name",
		order_by="creation asc",
	)
	closed = []
	for name in names:
		if name == skip:
			continue
		other = frappe.get_doc("Job Card", name)
		_complete_job_card(other, rejected=True)
		closed.append(name)
	return closed


def _post_manufacture(card, serial_no, target_warehouse=None, rejected=False):
	"""Manufacture exactly this unit's serial, carrying its inspection onto the entry.

	`target_warehouse` overrides the Work Order's finished-goods warehouse, which is what a
	packing step uses to land the unit straight in the warehouse the box is destined for
	instead of moving it there afterwards, and what a rejected unit uses to land in the
	reject warehouse.

	`rejected` posts a unit whose inspection failed. `StockController.validate_qi_rejection`
	refuses that while Stock Settings says `Stop`, a rule meant to keep bad units out of
	finished goods — which is exactly what `target_warehouse` is doing here by other means.
	The inspection is still carried onto the row, so the entry says what was wrong with it.
	"""
	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

	wo = frappe.get_doc("Work Order", card.work_order)
	qty = flt(card.for_quantity) or 1

	# Materials normally go to WIP in the morning for the whole Work Order. If that was
	# skipped, move just this unit's share rather than refuse to finish it.
	if not wo.skip_transfer:
		short = flt(wo.produced_qty) + qty - flt(wo.material_transferred_for_manufacturing)
		if short > 0:
			transfer = frappe.get_doc(
				make_stock_entry(wo.name, "Material Transfer for Manufacture", qty=short)
			)
			transfer.flags.ignore_permissions = True
			transfer.insert()
			transfer.submit()

	se = frappe.get_doc(
		make_stock_entry(
			wo.name,
			"Manufacture",
			qty=qty,
			serial_nos=json.dumps([serial_no]) if serial_no else None,
		)
	)
	# Stock Entry demands an inspection on the finished row when the item requires one;
	# `make_stock_entry` leaves it empty.
	for row in se.items:
		if row.is_finished_item and row.item_code == wo.production_item:
			if card.quality_inspection:
				row.quality_inspection = card.quality_inspection
			if target_warehouse:
				row.t_warehouse = target_warehouse
				_move_draft_bundle(row.serial_and_batch_bundle, target_warehouse)
	if rejected:
		se.validate_inspection = lambda: None
	se.flags.ignore_permissions = True
	se.insert()
	se.submit()

	# `auto_stock_entry` is what `JobCard.on_cancel` cancels, so undoing the card undoes this.
	card.db_set("auto_stock_entry", se.name)
	return se.name


def _move_draft_bundle(bundle, warehouse):
	"""Point the finished row's draft Serial and Batch Bundle at the warehouse the row now targets.

	`make_stock_entry` builds the bundle for the Work Order's finished-goods warehouse before
	the row is redirected, and the stock ledger refuses a bundle whose warehouse differs from
	its row's ("does not belong to Item or Warehouse").
	"""
	if not bundle:
		return
	frappe.db.set_value("Serial and Batch Bundle", bundle, "warehouse", warehouse)
	frappe.db.set_value("Serial and Batch Entry", {"parent": bundle}, "warehouse", warehouse)


PACKING_OPERATION = "Упаковка"


def _card_for(serial_no, operation=None, docstatus=None):
	"""One Job Card of this serial, optionally of one operation and docstatus."""
	filters = {"serial_no": serial_no}
	if operation:
		filters["operation"] = operation
	if docstatus is not None:
		filters["docstatus"] = docstatus
	name = frappe.db.get_value("Job Card", filters, "name", order_by="creation desc")
	return frappe.get_doc("Job Card", name) if name else None


def _bench_card(serial_no, packing_operation=PACKING_OPERATION):
	"""The closed card a unit is manufactured from: the one carrying its inspection.

	Falls back to the newest closed card of any other operation, for a unit whose item needs
	no inspection.
	"""
	for filters in (
		{"serial_no": serial_no, "docstatus": 1, "quality_inspection": ["is", "set"]},
		{"serial_no": serial_no, "docstatus": 1, "operation": ["!=", packing_operation]},
	):
		name = frappe.db.get_value("Job Card", filters, "name", order_by="creation desc")
		if name:
			return frappe.get_doc("Job Card", name)
	return None


def finish_packed_unit(serial_no, target_warehouse=None, employee=None, operation=None):
	"""Close the packing Job Card of a unit and put the unit into stock.

	This is the other half of `manufacture_at_packing`: the bench closed its own card and
	left the unit out of stock, and packing is what finishes it. Order matters and is the
	whole point — the packing card has to be submitted *before* the Manufacture entry, or
	`Stock Entry.check_if_operations_completed` sees an open operation and refuses.

	Idempotent per serial: a unit already carrying a submitted Manufacture entry is reported
	as `already_in_stock` and nothing is posted twice. A unit whose Work Order predates the
	packing operation simply has no card — `card: False`, and it is still manufactured.

	Never raises for one bad unit: the box is already built and labelled by the time this
	runs, so every serial reports its own outcome. A unit that fails is rolled back to where
	it started — a packing card left submitted without its Manufacture entry (or with the
	Work Order never told) is a unit nothing can finish afterwards.
	"""
	result = {
		"serial_no": serial_no,
		"card": None,
		"card_closed": False,
		"stock_entry": None,
		"already_in_stock": False,
		"error": None,
	}
	if not serial_no:
		result["error"] = _("Serial No is required")
		return result

	_lock_work_order_of(serial_no)

	save_point = "finish_packed_unit"
	frappe.db.savepoint(save_point)
	try:
		# A rejected unit was finished at the bench, cards and stock included. If one reaches
		# the packing station anyway, say so instead of posting it into the packed warehouse.
		bench_verdict = _rejected_inspection(serial_no)
		if bench_verdict:
			result["rejected"] = True
			result["error"] = _("{0} failed quality inspection {1} and is not packed").format(
				serial_no, bench_verdict
			)
			return result

		packing_card = _card_for(serial_no, operation=operation or PACKING_OPERATION, docstatus=0)
		if packing_card:
			result["card"] = packing_card.name
			now = now_datetime()
			start = get_datetime(packing_card.actual_start_date) if packing_card.actual_start_date else now
			if start > now:
				start = now
			row = {"from_time": start, "to_time": now, "completed_qty": packing_card.for_quantity or 1}
			if employee:
				row["employee"] = employee
			packing_card.append("time_logs", row)
			packing_card.flags.ignore_permissions = True
			packing_card.save()
			packing_card.submit()
			result["card_closed"] = True

		# The inspection lives on the bench's card, so that is the one the entry is posted
		# from — it carries the Quality Inspection onto the finished row. The packing card
		# was just submitted and is now the newest closed card, so it is skipped explicitly.
		bench_card = _bench_card(serial_no, packing_operation=operation or PACKING_OPERATION)
		if not bench_card:
			result["error"] = _("{0} has no closed Job Card to finish").format(serial_no)
			return result

		existing = bench_card.auto_stock_entry
		if existing and frappe.db.get_value("Stock Entry", existing, "docstatus") == 1:
			result["stock_entry"] = existing
			result["already_in_stock"] = True
			return result

		result["stock_entry"] = _post_manufacture(bench_card, serial_no, target_warehouse=target_warehouse)
	except Exception as e:
		frappe.db.rollback(save_point=save_point)
		result.update(card_closed=False, stock_entry=None, error=_error_text(e))
		frappe.log_error(
			title=f"Production Line: could not finish packed unit {serial_no}",
			message=frappe.get_traceback(),
		)

	return result


def _lock_work_order_of(serial_no):
	"""Serialise packers of one Work Order and give the unit a fresh database snapshot.

	Boxes of the same Work Order are packed at several benches at once, and every submitted
	packing card saves the Work Order. Under REPEATABLE READ the request's snapshot is older
	than a neighbour's commit, so `wo.save()` read stale data and raised `TimestampMismatchError`
	for the whole box. Committing ends that snapshot; the row lock makes the next packer wait
	for this unit instead of racing it.
	"""
	work_order = frappe.db.get_value("Serial No", serial_no, "work_order") if serial_no else None
	if not work_order:
		return
	frappe.db.commit()
	frappe.db.get_value("Work Order", work_order, "name", for_update=True)


def _error_text(e):
	"""An exception as one line for a scanner display. `frappe.PermissionError` raised by
	`Document.check_permission` carries no message at all, and an empty error reads as success."""
	return str(e).strip() or _("{0} (no message)").format(type(e).__name__)


def finish_packed_units(serials, target_warehouse=None, employee=None, operation=None):
	"""`finish_packed_unit` for a whole box, summarised for a scanner display."""
	rows = [
		finish_packed_unit(sn, target_warehouse=target_warehouse, employee=employee, operation=operation)
		for sn in (serials or [])
	]
	errors = [f"{r['serial_no']}: {r['error']}" for r in rows if r.get("error")]
	return {
		"manufactured": len([r for r in rows if r.get("stock_entry") and not r.get("already_in_stock")]),
		"already_in_stock": len([r for r in rows if r.get("already_in_stock")]),
		"cards_closed": len([r for r in rows if r.get("card_closed")]),
		"stock_entries": [r["stock_entry"] for r in rows if r.get("stock_entry")],
		"error": "; ".join(errors) if errors else None,
		"rows": rows,
	}


def close_stale_work_orders(line=None, force=False):
	"""Close the day: keep only the units somebody started, so no stale unit is handed out.

	A line's Work Orders are Daily: every card and serial of a unit nobody touched is deleted,
	and Qty shrinks to the units that were started. Those finish at their own pace, and the
	last one into stock completes the Work Order. A Work Order nobody touched at all is closed,
	since its Qty cannot shrink to zero.
	"""
	cutoff = now_datetime()
	lines_to_run = [frappe.get_doc("Production Line", line)] if line else _enabled_lines()
	for line in lines_to_run:
		if not line.cleanup_enabled and not force:
			continue

		work_orders = frappe.get_all(
			"Work Order",
			filters={
				"production_line": line.name,
				"line_order_type": "Daily",
				"docstatus": 1,
				"status": ["in", LIVE_WORK_ORDER_STATUSES],
				"creation": ["<", cutoff],
			},
			pluck="name",
			order_by="creation",
		)

		shrunk, closed, kept = [], [], []
		for name in work_orders:
			cards = frappe.get_all(
				"Job Card",
				filters={"work_order": name, "docstatus": ["<", 2]},
				fields=["name", "docstatus", "status", "quality_inspection", "serial_no"],
			)
			# A unit is started once any of its cards was handed out, measured or closed. Its
			# remaining cards are the rest of that unit's route — packing after winding — and
			# deleting them strands a physical unit: nothing can ever finish it into stock.
			started = {
				_first_serial(c.serial_no)
				for c in cards
				if c.docstatus == 1 or c.status != FREE_JOB_CARD_STATUS or c.quality_inspection
			}
			started.discard(None)

			untouched = [c for c in cards if _first_serial(c.serial_no) not in started]
			for card in untouched:
				frappe.delete_doc("Job Card", card.name, force=1, ignore_permissions=True)
			_delete_serials({_first_serial(c.serial_no) for c in untouched} - {None})

			wo = frappe.get_doc("Work Order", name)
			wo.flags.ignore_permissions = True
			# A unit finished before an older cleanup deleted its cards is no longer among them,
			# but it is still in `produced_qty`.
			keep = max(len(started), cint(flt(wo.produced_qty) + flt(wo.process_loss_qty)))
			if not keep:
				wo.update_status("Closed")
				wo.on_close_or_cancel()
				closed.append(f"{name} ({len(untouched)} cards)")
			elif keep < wo.qty:
				old_qty = wo.qty
				_shrink_work_order(wo, keep)
				shrunk.append(f"{name} {cint(old_qty)}→{keep} ({len(untouched)} cards)")
			else:
				kept.append(f"{name} ({keep} started)")
			frappe.db.commit()

		lines = []
		if shrunk:
			lines.append("shrunk: " + "; ".join(shrunk))
		if closed:
			lines.append("closed: " + "; ".join(closed))
		if kept:
			lines.append("all started: " + "; ".join(kept))
		frappe.db.set_value(
			"Production Line",
			line.name,
			{"last_cleanup_on": cutoff, "last_cleanup_result": "\n".join(lines) or "nothing to do"},
			update_modified=False,
		)
		frappe.db.commit()


def _shrink_work_order(wo, qty):
	"""Cut a submitted Work Order down to `qty` units, materials included.

	`qty` is not allow_on_submit, so the form cannot do this. Materials are moved to WIP per
	unit as it is finished, so nothing transferred for the dropped units is left behind.
	"""
	ratio = flt(qty) / flt(wo.qty)
	frappe.db.set_value("Work Order", wo.name, "qty", qty, update_modified=False)
	for row in wo.required_items:
		frappe.db.set_value(
			"Work Order Item",
			row.name,
			"required_qty",
			flt(row.required_qty * ratio, row.precision("required_qty")),
			update_modified=False,
		)
	wo.reload()
	wo.flags.ignore_permissions = True
	wo.update_status()
	wo.update_planned_qty()


@frappe.whitelist()
def close_day(line):
	"""Close a line's day now instead of waiting for Close Day At."""
	frappe.only_for(("System Manager", "Manufacturing Manager"))
	close_stale_work_orders(line=line, force=True)
	return frappe.db.get_value("Production Line", line, "last_cleanup_result")


def restore_route_cards(work_order):
	"""Give every started unit of a Work Order back the cards the nightly cleanup deleted.

	Until the cleanup learned to keep a started unit's route, it deleted the packing card of
	every spool wound that day — the unit was measured and closed at the bench, but nothing
	could pack it or finish it into stock. A unit is started once any of its cards was handed
	out, measured or closed; a unit nobody touched is left as the cleanup left it. Resumes the
	Work Order when it was stopped, since a stopped one refuses to close the new cards.

	bench --site <site> execute erpnext.manufacturing.doctype.production_line.production_line.restore_route_cards --kwargs '{"work_order": "MFG-WO-..."}'
	"""
	from erpnext.manufacturing.doctype.work_order.work_order import create_job_card

	wo = frappe.get_doc("Work Order", work_order)
	if wo.docstatus != 1 or wo.status == "Closed":
		frappe.throw(_("Work Order {0} is not open").format(work_order))

	cards = frappe.get_all(
		"Job Card",
		filters={"work_order": work_order, "docstatus": ["<", 2]},
		fields=["docstatus", "status", "quality_inspection", "serial_no", "operation_id"],
	)
	started = sorted(
		{
			_first_serial(c.serial_no)
			for c in cards
			if c.docstatus == 1 or c.status != FREE_JOB_CARD_STATUS or c.quality_inspection
		}
		- {None}
	)
	have = {(c.operation_id, _first_serial(c.serial_no)) for c in cards}
	missing = [(row, serial) for row in wo.operations for serial in started if (row.name, serial) not in have]
	if not missing:
		return {"work_order": work_order, "restored": []}

	if wo.status == "Stopped":
		wo.flags.ignore_permissions = True
		wo.update_status("Resumed")

	restored = []
	for row, serial in missing:
		row.job_card_qty = 1
		row.serial_no = serial
		card = create_job_card(wo, row, auto_create=True)
		restored.append(f"{serial}: {row.operation} → {card.name}")
	frappe.db.commit()
	return {"work_order": work_order, "status": wo.status, "restored": restored}


def _first_serial(serial_no):
	"""A per-unit card holds one serial; the field is still a newline-separated list."""
	lines = (serial_no or "").strip().splitlines()
	return lines[0].strip() if lines else None


def _delete_serials(serials):
	"""Serials of units nobody started — only while they never carried stock."""
	if not serials:
		return
	serials = frappe.get_all(
		"Serial No",
		filters={"name": ["in", list(serials)], "status": ["!=", "Active"], "warehouse": ["is", "not set"]},
		pluck="name",
	)
	for name in serials:
		if frappe.db.exists("Stock Ledger Entry", {"serial_no": name}):
			continue
		frappe.delete_doc("Serial No", name, force=1, ignore_permissions=True)


def _stranded_packed_units(line, work_order=None):
	"""Units packed but never put into stock: the packing card is submitted, the unit is not.

	Left behind while `JobCard.update_work_order_data` saved the Work Order without
	`ignore_permissions`: a packing operator without write access on Work Order got the card
	marked submitted, and `finish_packed_unit` swallowed the empty `PermissionError` before
	the Work Order was told or the Manufacture entry was posted.
	"""
	filters = {"production_line": line, "docstatus": 1}
	if work_order:
		filters["name"] = work_order
	work_orders = frappe.get_all("Work Order", filters=filters, pluck="name")
	if not work_orders:
		return []

	return frappe.db.sql(
		"""SELECT pc.name AS packing_card, pc.serial_no, pc.work_order
			 FROM `tabJob Card` pc
			 JOIN `tabSerial No` sn ON sn.name = pc.serial_no
			WHERE pc.work_order IN %(work_orders)s
			  AND pc.operation = %(packing)s
			  AND pc.docstatus = 1
			  AND IFNULL(sn.warehouse, '') = ''
			  AND NOT EXISTS (
				SELECT 1 FROM `tabJob Card` bc
				  JOIN `tabStock Entry` se ON se.name = bc.auto_stock_entry AND se.docstatus = 1
				 WHERE bc.serial_no = pc.serial_no
			  )
			ORDER BY pc.work_order, pc.serial_no""",
		{"work_orders": tuple(work_orders), "packing": PACKING_OPERATION},
		as_dict=True,
	)


@frappe.whitelist()
def repair_packed_units(line, work_order=None, dry_run=1):
	"""Finish into stock the units whose packing card closed without a Manufacture entry.

	Per unit: tell the Work Order the packing operation is done (the part that failed), then
	post the Manufacture entry from the bench card, exactly as `finish_packed_unit` would have.
	Idempotent — a repaired unit is in stock and drops out of the search. `dry_run` only lists.
	"""
	frappe.only_for(("System Manager", "Manufacturing Manager"))
	rows = _stranded_packed_units(line, work_order=work_order)
	if cint(dry_run):
		return {"found": len(rows), "units": rows}

	done, failed = [], []
	for row in rows:
		save_point = "repair_packed_unit"
		frappe.db.savepoint(save_point)
		try:
			if _rejected_inspection(row.serial_no):
				failed.append(f"{row.serial_no}: {_('failed quality inspection')}")
				continue
			packing_card = frappe.get_doc("Job Card", row.packing_card)
			packing_card.update_work_order()
			packing_card.set_transferred_qty()
			bench_card = _bench_card(row.serial_no)
			if not bench_card:
				failed.append(f"{row.serial_no}: {_('no closed Job Card to finish')}")
				continue
			done.append(f"{row.serial_no}: {_post_manufacture(bench_card, row.serial_no)}")
			frappe.db.commit()
		except Exception as e:
			frappe.db.rollback(save_point=save_point)
			failed.append(f"{row.serial_no}: {_error_text(e)}")

	return {"found": len(rows), "repaired": done, "failed": failed}
