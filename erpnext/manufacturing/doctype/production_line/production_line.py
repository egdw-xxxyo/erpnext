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
* `close_stale_work_orders` stops earlier days' leftovers overnight, so the app cannot hand
  out a unit from a Work Order nobody is working on any more.

Nothing here knows what the line makes. `Line Type` is what a client asks for — the spool
app calls `erpnext.manufacturing.spool_production`, which passes "Spool" — so a second kind
of line reuses this engine and only adds its own client endpoints.
"""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_datetime, now_datetime, today

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
		delete_unused_serials: DF.Check
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
	user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		wo.submit()
	finally:
		frappe.set_user(user)
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
		"remaining": len(_free_job_cards(item_code, workplace=workplace, limit=100)),
	}


def release_unit(job_card):
	"""Put an untouched unit back in the pool — the operator took it and walked away."""
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
			return {**result, "finished": False, "verdict": "Fail"}
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


def _complete_job_card(card):
	"""One time log from the claim to now for the whole card, then submit."""
	from erpnext.manufacturing.doctype.job_card.job_card import OverlapError

	now = now_datetime()
	start = get_datetime(card.actual_start_date) if card.actual_start_date else now
	if start > now:
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


def _post_manufacture(card, serial_no, target_warehouse=None):
	"""Manufacture exactly this unit's serial, carrying its inspection onto the entry.

	`target_warehouse` overrides the Work Order's finished-goods warehouse, which is what a
	packing step uses to land the unit straight in the warehouse the box is destined for
	instead of moving it there afterwards.
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
	se.flags.ignore_permissions = True
	se.insert()
	se.submit()

	# `auto_stock_entry` is what `JobCard.on_cancel` cancels, so undoing the card undoes this.
	card.db_set("auto_stock_entry", se.name)
	return se.name


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
	runs, so every serial reports its own outcome.
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

	try:
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
		# from — it carries the Quality Inspection onto the finished row.
		bench_card = _card_for(serial_no, docstatus=1)
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
		result["error"] = str(e)

	return result


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


def close_stale_work_orders(line=None):
	"""Close the day: stop the Work Orders opened before now so no stale unit is handed out.

	Serial Nos are kept unless the line asks otherwise: a gap in the numbering is cheap, and
	a nightly job that deletes records is the kind of thing that eventually deletes a real one.
	"""
	cutoff = now_datetime()
	lines_to_run = [frappe.get_doc("Production Line", line)] if line else _enabled_lines()
	for line in lines_to_run:
		if not line.cleanup_enabled:
			continue

		items = [row.item_code for row in _plan_rows(line)]
		if not items:
			frappe.db.set_value(
				"Production Line",
				line.name,
				{"last_cleanup_on": cutoff, "last_cleanup_result": "nothing to do"},
				update_modified=False,
			)
			continue

		work_orders = frappe.get_all(
			"Work Order",
			filters={
				"production_item": ["in", items],
				"docstatus": 1,
				"status": ["in", LIVE_WORK_ORDER_STATUSES],
				"creation": ["<", cutoff],
			},
			pluck="name",
		)

		stopped, held = [], []
		for name in work_orders:
			# Only cards nobody ever took. A card in Work In Progress was handed to an operator,
			# and deleting it would strand its unit: the serial exists but no card can be issued
			# for it again.
			untouched = frappe.get_all(
				"Job Card",
				filters={
					"work_order": name,
					"docstatus": 0,
					"status": FREE_JOB_CARD_STATUS,
					"quality_inspection": ["is", "not set"],
				},
				pluck="name",
			)
			for card in untouched:
				frappe.delete_doc("Job Card", card, force=1, ignore_permissions=True)

			in_progress = frappe.db.count(
				"Job Card",
				{
					"work_order": name,
					"docstatus": 0,
					"status": CLAIMED_JOB_CARD_STATUS,
					"quality_inspection": ["is", "not set"],
				},
			)
			if in_progress:
				# Someone is still on it, or walked away from it. Either way stopping the Work
				# Order would block them from closing the card, so leave it and report.
				held.append(f"{name} ({in_progress} in progress)")
				continue

			if line.delete_unused_serials:
				_delete_unused_serials(name)

			wo = frappe.get_doc("Work Order", name)
			wo.flags.ignore_permissions = True
			wo.update_status("Stopped")
			stopped.append(f"{name} ({len(untouched)} cards)")

		lines = []
		if stopped:
			lines.append("stopped: " + "; ".join(stopped))
		if held:
			lines.append("left open: " + "; ".join(held))
		frappe.db.set_value(
			"Production Line",
			line.name,
			{"last_cleanup_on": cutoff, "last_cleanup_result": "\n".join(lines) or "nothing to do"},
			update_modified=False,
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
