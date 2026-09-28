"""One read-only picture of the production lines: setup, today's plan, Work Orders, units, benches.

A line's state is spread over the line itself, its Work Orders (found by item — they carry no
link back to the line), one Job Card per unit and operation, the units' Serial Nos and their
Quality Inspections. This page puts them side by side and says where a unit is stuck, so a
supervisor does not have to rebuild that from five list views.
"""

import frappe
from frappe import _
from frappe.utils import (
	add_days,
	cint,
	flt,
	formatdate,
	get_datetime,
	getdate,
	now_datetime,
	time_diff_in_seconds,
	today,
)

from erpnext.manufacturing.doctype.production_line.production_line import (
	FREE_JOB_CARD_STATUS,
	LIVE_WORK_ORDER_STATUSES,
	PACKING_OPERATION,
	_first_serial,
	_moment,
)

VIEW_ROLES = ("Manufacturing Manager", "Manufacturing User", "System Manager")
HISTORY_DAYS = 7
STALE_CLAIM_HOURS = 8
UNIT_STATES = ("free", "in_progress", "measured", "waiting_packing", "in_stock", "rejected")


@frappe.whitelist()
def get_overview():
	frappe.only_for(VIEW_ROLES)

	lines = _lines()
	workplaces = _workplaces({wp["workplace"] for line in lines for wp in line["workplaces"]})
	items = _items({row["item_code"] for line in lines for row in line["plan"]})
	work_orders = _work_orders(lines)
	cards = _cards([wo["name"] for wo in work_orders])
	inspections = _inspections({c.quality_inspection for c in cards if c.quality_inspection})
	serials = _serials([wo["name"] for wo in work_orders])
	reject_warehouses = {line["reject_warehouse"] for line in lines if line["reject_warehouse"]}

	units = _units(work_orders, cards, inspections, serials, reject_warehouses)
	for wo in work_orders:
		wo["units"] = _count(u["state"] for u in units if u["work_order"] == wo["name"])
	_attach_progress(lines, work_orders, units, workplaces)

	attention = _attention(units)
	errors = _error_logs()

	return {
		"generated_at": frappe.utils.now(),
		"today": today(),
		"history_days": HISTORY_DAYS,
		"lines": lines,
		"workplaces": list(workplaces.values()),
		"items": items,
		"work_orders": work_orders,
		"attention": attention,
		"error_logs": errors,
		"issues": _issues(lines, workplaces, items, work_orders, attention, errors),
	}


def _lines():
	rows = frappe.get_all(
		"Production Line",
		fields=[
			"name",
			"line_name",
			"line_type",
			"enabled",
			"company",
			"source_warehouse",
			"wip_warehouse",
			"fg_warehouse",
			"reject_warehouse",
			"manufacture_at_packing",
			"plan_time",
			"overflow_qty",
			"cleanup_enabled",
			"cleanup_time",
			"delete_unused_serials",
			"last_run_on",
			"last_result",
			"last_cleanup_on",
			"last_cleanup_result",
		],
		order_by="enabled desc, name asc",
	)
	workplace_rows = frappe.get_all(
		"Production Line Workplace",
		filters={"parenttype": "Production Line", "parentfield": "workplaces"},
		fields=["parent", "workplace", "enabled"],
		order_by="idx asc",
	)
	plan_rows = frappe.get_all(
		"Production Line Item",
		filters={"parenttype": "Production Line", "parentfield": "plan"},
		fields=["parent", "item_code", "workplace", "daily_qty", "enabled"],
		order_by="idx asc",
	)
	now = now_datetime()

	out = []
	for row in rows:
		plan_moment = _moment(row.plan_time) if row.plan_time else None
		out.append(
			{
				**row,
				"enabled": cint(row.enabled),
				"manufacture_at_packing": cint(row.manufacture_at_packing),
				"cleanup_enabled": cint(row.cleanup_enabled),
				"delete_unused_serials": cint(row.delete_unused_serials),
				"plan_time": str(row.plan_time) if row.plan_time else None,
				"cleanup_time": str(row.cleanup_time) if row.cleanup_time else None,
				"planned_today": bool(
					plan_moment and row.last_run_on and get_datetime(row.last_run_on) >= plan_moment
				),
				"plan_due": bool(plan_moment and now >= plan_moment),
				"workplaces": [
					{"workplace": w.workplace, "enabled": cint(w.enabled)}
					for w in workplace_rows
					if w.parent == row.name and w.workplace
				],
				"plan": [
					{
						"item_code": p.item_code,
						"workplace": p.workplace,
						"daily_qty": cint(p.daily_qty),
						"enabled": cint(p.enabled),
					}
					for p in plan_rows
					if p.parent == row.name and p.item_code
				],
			}
		)
	return out


def _workplaces(names):
	if not names:
		return {}
	rows = frappe.get_all(
		"Workplace",
		filters={"name": ["in", list(names)]},
		fields=["name", "workplace_name", "short_name", "is_active", "workplace_script", "otdr_configuration"],
	)
	operations = frappe.get_all(
		"Workplace Operation",
		filters={"parenttype": "Workplace", "parent": ["in", list(names)]},
		fields=["parent", "operation", "workstation"],
		order_by="idx asc",
	)
	employees = frappe.get_all(
		"Workplace Employee",
		filters={"parenttype": "Workplace", "parent": ["in", list(names)]},
		fields=["parent", {"COUNT": "*", "as": "n"}],
		group_by="parent",
	)
	printers = frappe.get_all(
		"Workplace Printer",
		filters={"parenttype": "Workplace", "parentfield": "printers", "parent": ["in", list(names)]},
		fields=["parent", "label_printer", "is_default"],
		order_by="idx asc",
	)
	employee_count = {e.parent: e.n for e in employees}

	out = {}
	for row in rows:
		out[row.name] = {
			"name": row.name,
			"label": row.workplace_name or row.name,
			"short_name": row.short_name,
			"is_active": cint(row.is_active),
			"workplace_script": row.workplace_script,
			"otdr_configuration": row.otdr_configuration,
			"employees": employee_count.get(row.name, 0),
			"operations": [
				{"operation": o.operation, "workstation": o.workstation}
				for o in operations
				if o.parent == row.name
			],
			"printers": [
				{"label_printer": p.label_printer, "is_default": cint(p.is_default)}
				for p in printers
				if p.parent == row.name
			],
			"in_progress": [],
			"measured": [],
		}
	return out


def _items(codes):
	if not codes:
		return {}
	rows = frappe.get_all(
		"Item",
		filters={"name": ["in", list(codes)]},
		fields=["name", "item_name", "default_bom", "has_serial_no", "disabled"],
	)
	boms = {
		b.name: b
		for b in frappe.get_all(
			"BOM",
			filters={"name": ["in", [r.default_bom for r in rows if r.default_bom] or [""]]},
			fields=["name", "is_active", "docstatus", "with_operations", "inspection_required"],
		)
	}
	bom_operations = frappe.get_all(
		"BOM Operation",
		filters={"parenttype": "BOM", "parent": ["in", list(boms) or [""]]},
		fields=["parent", "operation", "workstation"],
		order_by="idx asc",
	)

	out = {}
	for row in rows:
		bom = boms.get(row.default_bom) or frappe._dict()
		out[row.name] = {
			"item_code": row.name,
			"item_name": row.item_name,
			"default_bom": row.default_bom,
			"has_serial_no": cint(row.has_serial_no),
			"disabled": cint(row.disabled),
			"bom_active": cint(bom.is_active) and bom.docstatus == 1,
			"with_operations": cint(bom.with_operations),
			"inspection_required": cint(bom.inspection_required),
			"operations": [
				{"operation": o.operation, "workstation": o.workstation}
				for o in bom_operations
				if o.parent == row.default_bom
			],
		}
	return out


def _work_orders(lines):
	"""The lines' Work Orders: still live, or opened in the last days.

	Work Orders are matched by item, the same way the line itself finds them.
	"""
	line_by_item = {}
	for line in lines:
		for row in line["plan"]:
			line_by_item.setdefault(row["item_code"], line["name"])
	if not line_by_item:
		return []

	since = add_days(today(), -HISTORY_DAYS)
	rows = frappe.get_all(
		"Work Order",
		filters={"production_item": ["in", list(line_by_item)], "docstatus": 1},
		or_filters={"creation": [">=", since], "status": ["in", LIVE_WORK_ORDER_STATUSES]},
		fields=[
			"name",
			"production_item",
			"qty",
			"produced_qty",
			"status",
			"creation",
			"description",
			"bom_no",
		],
		order_by="creation desc",
		limit=500,
	)
	start_of_today = getdate(today())
	for row in rows:
		row["production_line"] = line_by_item.get(row.production_item)
		row["reason"] = "overflow" if "(overflow)" in (row.description or "") else "plan"
		row["is_today"] = getdate(row.creation) >= start_of_today
		row["is_live"] = row.status in LIVE_WORK_ORDER_STATUSES
		row.pop("description", None)
	return rows


def _cards(work_orders):
	if not work_orders:
		return []
	return frappe.get_all(
		"Job Card",
		filters={"work_order": ["in", work_orders], "docstatus": ["<", 2]},
		fields=[
			"name",
			"work_order",
			"serial_no",
			"status",
			"docstatus",
			"operation",
			"workstation",
			"quality_inspection",
			"actual_start_date",
			"creation",
			"modified",
			"modified_by",
			"auto_stock_entry",
		],
		order_by="creation asc",
	)


def _inspections(names):
	if not names:
		return {}
	return {
		q.name: q
		for q in frappe.get_all(
			"Quality Inspection",
			filters={"name": ["in", list(names)]},
			fields=["name", "status", "docstatus"],
		)
	}


def _serials(work_orders):
	if not work_orders:
		return {}
	return {
		s.name: s
		for s in frappe.get_all(
			"Serial No",
			filters={"work_order": ["in", work_orders]},
			fields=["name", "status", "warehouse"],
		)
	}


def _units(work_orders, cards, inspections, serials, reject_warehouses):
	"""One row per serial: which of its cards are where, and what that makes the unit."""
	wo_by_name = {wo["name"]: wo for wo in work_orders}
	by_serial = {}
	for card in cards:
		serial = _first_serial(card.serial_no)
		if serial:
			by_serial.setdefault((card.work_order, serial), []).append(card)

	units = []
	for (work_order, serial), unit_cards in by_serial.items():
		sn = serials.get(serial) or frappe._dict()
		qi_card = next((c for c in unit_cards if c.quality_inspection), None)
		qi = inspections.get(qi_card.quality_inspection) if qi_card else None
		rejected = bool(qi and qi.docstatus == 1 and qi.status == "Rejected")
		open_cards = [c for c in unit_cards if c.docstatus == 0]
		closed_cards = [c for c in unit_cards if c.docstatus == 1]
		claimed = next((c for c in open_cards if c.status != FREE_JOB_CARD_STATUS), None)

		if rejected:
			state = "rejected"
		elif sn.warehouse and sn.warehouse not in reject_warehouses:
			state = "in_stock"
		elif qi_card and qi_card.docstatus == 0:
			state = "measured"
		elif closed_cards and open_cards:
			state = "waiting_packing"
		elif claimed:
			state = "in_progress"
		elif closed_cards:
			state = "in_stock" if sn.warehouse else "waiting_packing"
		else:
			state = "free"

		active = qi_card if state == "measured" else claimed
		units.append(
			{
				"serial_no": serial,
				"work_order": work_order,
				"item_code": wo_by_name[work_order].production_item,
				"production_line": wo_by_name[work_order]["production_line"],
				"state": state,
				"warehouse": sn.warehouse,
				"quality_inspection": qi_card.quality_inspection if qi_card else None,
				"qi_status": qi.status if qi else None,
				"job_card": active.name if active else None,
				"operation": active.operation if active else None,
				"workstation": active.workstation if active else None,
				"since": active.actual_start_date or active.modified if active else None,
				"by": active.modified_by if active else None,
				"open_operations": [c.operation for c in open_cards],
				"is_today": wo_by_name[work_order]["is_today"],
			}
		)
	return units


def _count(states):
	out = dict.fromkeys(UNIT_STATES, 0)
	for state in states:
		out[state] += 1
	return out


def _attach_progress(lines, work_orders, units, workplaces):
	"""Today's numbers per plan row, and the units each bench holds right now."""
	for line in lines:
		for row in line["plan"]:
			wos = [
				wo
				for wo in work_orders
				if wo["is_today"] and wo["production_item"] == row["item_code"]
			]
			row["work_orders"] = [wo["name"] for wo in wos]
			row["overflow_work_orders"] = len([wo for wo in wos if wo["reason"] == "overflow"])
			row["qty_today"] = sum(flt(wo["qty"]) for wo in wos)
			row["units"] = _count(
				u["state"] for u in units if u["is_today"] and u["item_code"] == row["item_code"]
			)
		line["units"] = _count(
			u["state"] for u in units if u["is_today"] and u["production_line"] == line["name"]
		)
		line["live_work_orders"] = len(
			[wo for wo in work_orders if wo["production_line"] == line["name"] and wo["is_live"]]
		)

	workstation_bench = {}
	for wp in workplaces.values():
		for op in wp["operations"]:
			if op["workstation"]:
				workstation_bench.setdefault(op["workstation"], wp["name"])
	users = {u["by"] for u in units if u["by"]}
	names = dict(
		frappe.get_all(
			"User", filters={"name": ["in", list(users) or [""]]}, fields=["name", "full_name"], as_list=True
		)
	)
	for unit in units:
		unit["by_name"] = names.get(unit["by"]) or unit["by"]
		bench = workstation_bench.get(unit["workstation"])
		unit["workplace"] = bench
		if bench and unit["state"] in ("in_progress", "measured"):
			workplaces[bench][unit["state"]].append(unit["serial_no"])


def _attention(units):
	"""Units somebody has to look at: in someone's hands, measured but not closed, rejected today."""
	now = now_datetime()
	out = []
	for unit in units:
		if unit["state"] not in ("in_progress", "measured", "rejected"):
			continue
		if unit["state"] == "rejected" and not unit["is_today"]:
			continue
		age = int(time_diff_in_seconds(now, unit["since"])) if unit["since"] else None
		out.append({**unit, "age": age})
	order = {"measured": 0, "in_progress": 1, "rejected": 2}
	out.sort(key=lambda u: (order[u["state"]], -(u["age"] or 0)))
	return out


def _error_logs():
	return frappe.get_all(
		"Error Log",
		filters={
			"creation": [">=", add_days(now_datetime(), -HISTORY_DAYS)],
			"method": ["like", "Production %"],
		},
		fields=["name", "method", "creation"],
		order_by="creation desc",
		limit=20,
	)


def _issues(lines, workplaces, items, work_orders, attention, errors):
	issues = []

	def add(level, area, message, doctype=None, name=None):
		issues.append({"level": level, "area": area, "message": message, "doctype": doctype, "name": name})

	area_line, area_plan, area_bench, area_wo, area_unit = (
		_("Production Line"),
		_("Plan"),
		_("Workplace"),
		_("Work Order"),
		_("Unit"),
	)

	for line in lines:
		if not line["enabled"]:
			continue
		name = line["name"]
		enabled_benches = [w for w in line["workplaces"] if w["enabled"]]
		enabled_plan = [p for p in line["plan"] if p["enabled"]]
		if not enabled_benches:
			add("warning", area_line, _("Line {0} has no workplaces").format(name), "Production Line", name)
		if not enabled_plan:
			add("warning", area_line, _("Line {0} has nothing planned").format(name), "Production Line", name)
		for field, label in (
			("wip_warehouse", _("Work-in-progress warehouse")),
			("fg_warehouse", _("Finished goods warehouse")),
		):
			if not line[field]:
				add(
					"warning",
					area_line,
					_("Line {0}: {1} is not set, the item's BOM decides").format(name, label),
					"Production Line",
					name,
				)
		if not line["reject_warehouse"]:
			add(
				"warning",
				area_line,
				_("Line {0} has no reject warehouse, rejected units are closed but not put into stock").format(
					name
				),
				"Production Line",
				name,
			)
		if enabled_plan and line["plan_due"] and not line["planned_today"]:
			add(
				"error",
				area_line,
				_("Line {0}: today's Work Orders were not opened, plan time {1} has passed").format(
					name, (line["plan_time"] or "")[:5]
				),
				"Production Line",
				name,
			)
		if "failed:" in (line["last_result"] or ""):
			add(
				"error",
				area_line,
				_("Line {0}: last plan run failed: {1}").format(name, line["last_result"]),
				"Production Line",
				name,
			)
		if not line["cleanup_enabled"]:
			add(
				"info",
				area_line,
				_("Line {0} does not close the day, old Work Orders stay open").format(name),
				"Production Line",
				name,
			)
		elif "left open" in (line["last_cleanup_result"] or ""):
			add(
				"info",
				area_line,
				_("Line {0}: closing the day left Work Orders open: {1}").format(
					name, line["last_cleanup_result"]
				),
				"Production Line",
				name,
			)

		for bench in enabled_benches:
			wp = workplaces.get(bench["workplace"])
			if not wp:
				continue
			if not wp["is_active"]:
				add(
					"error",
					area_bench,
					_("Line {0} runs at inactive workplace {1}").format(name, wp["name"]),
					"Workplace",
					wp["name"],
				)
			if not wp["operations"]:
				add(
					"warning",
					area_bench,
					_("Workplace {0} has no allowed operations, it is offered any unit of the item").format(
						wp["name"]
					),
					"Workplace",
					wp["name"],
				)
			if not wp["employees"]:
				add(
					"info",
					area_bench,
					_("Workplace {0} has no employees, only managers can work there").format(wp["name"]),
					"Workplace",
					wp["name"],
				)

		for row in enabled_plan:
			item = items.get(row["item_code"])
			if not item:
				continue
			code = item["item_code"]
			if item["disabled"]:
				add("error", area_plan, _("Planned item {0} is disabled").format(code), "Item", code)
			if not item["default_bom"]:
				add(
					"error",
					area_plan,
					_("Item {0} has no default BOM, no Work Order can be opened").format(code),
					"Item",
					code,
				)
			elif not item["bom_active"]:
				add(
					"error",
					area_plan,
					_("Default BOM {0} of item {1} is not active and submitted").format(
						item["default_bom"], code
					),
					"BOM",
					item["default_bom"],
				)
			elif not item["with_operations"] or not item["operations"]:
				add(
					"error",
					area_plan,
					_("BOM {0} has no operations, its Work Orders get no Job Cards").format(item["default_bom"]),
					"BOM",
					item["default_bom"],
				)
			if not item["has_serial_no"]:
				add(
					"error",
					area_plan,
					_("Item {0} has no serial numbers, the line cannot hand out units").format(code),
					"Item",
					code,
				)
			if line["manufacture_at_packing"] and item["operations"]:
				if PACKING_OPERATION not in [o["operation"] for o in item["operations"]]:
					add(
						"warning",
						area_plan,
						_(
							"Line {0} finishes units at packing, but BOM {1} has no operation {2}"
						).format(name, item["default_bom"], PACKING_OPERATION),
						"BOM",
						item["default_bom"],
					)
			wp = workplaces.get(row["workplace"])
			if wp and wp["operations"] and item["operations"]:
				bench_ws = {o["workstation"] for o in wp["operations"] if o["workstation"]}
				bom_ws = {o["workstation"] for o in item["operations"] if o["workstation"]}
				if bench_ws and not bench_ws & bom_ws:
					add(
						"error",
						area_plan,
						_(
							"Workplace {0} covers none of the workstations of BOM {1}, it will never get a unit of {2}"
						).format(wp["name"], item["default_bom"], code),
						"Workplace",
						wp["name"],
					)
			if not row["daily_qty"]:
				add(
					"info",
					area_plan,
					_("Line {0}: item {1} has daily quantity 0, only overflow Work Orders are opened").format(
						name, code
					),
					"Production Line",
					name,
				)

	for wo in work_orders:
		if wo["is_live"] and not wo["is_today"] and wo["units"]["free"]:
			add(
				"warning",
				area_wo,
				_("Work Order {0} from {1} is still open with {2} untouched units").format(
					wo["name"], formatdate(wo["creation"]), wo["units"]["free"]
				),
				"Work Order",
				wo["name"],
			)

	for unit in attention:
		if unit["state"] == "measured" and not unit["is_today"]:
			add(
				"warning",
				area_unit,
				_("{0} was measured but never finished, it is not in stock").format(unit["serial_no"]),
				"Job Card",
				unit["job_card"],
			)
		elif unit["state"] == "in_progress" and (unit["age"] or 0) > STALE_CLAIM_HOURS * 3600:
			add(
				"warning",
				area_unit,
				_("{0} was taken at {1} more than {2} hours ago and is still in progress").format(
					unit["serial_no"], unit["workplace"] or unit["workstation"] or "-", STALE_CLAIM_HOURS
				),
				"Job Card",
				unit["job_card"],
			)

	grouped = {}
	for log in errors:
		grouped.setdefault(log.method, []).append(log)
	for method, logs in grouped.items():
		add(
			"error",
			_("Error Log"),
			_("{0} ({1} times in {2} days)").format(method, len(logs), HISTORY_DAYS),
			"Error Log",
			logs[0].name,
		)

	order = {"error": 0, "warning": 1, "info": 2}
	issues.sort(key=lambda i: order[i["level"]])
	return issues
