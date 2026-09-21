"""Data for the Production Flow page.

The page draws a BOM's operations as swim lanes. A `Production Line` narrows it down to what
one line actually runs: only the items on its plan can be picked, and the benches, printers,
operations and workstations of the line are shown next to the diagram — so the drawing can be
read as "this line, at these benches" rather than as an abstract BOM.
"""

import frappe


@frappe.whitelist()
def get_bom_flow(bom_name):
	bom = frappe.get_doc("BOM", bom_name)
	if not bom.with_operations:
		return {"operations": [], "items": [], "swim_lanes": []}

	operations = []
	for op in bom.operations:
		operations.append(
			{
				"idx": op.idx,
				"operation": op.operation,
				"workstation": op.workstation,
				"time_in_mins": op.time_in_mins,
				"description": op.description,
			}
		)

	items = []
	for item in bom.items:
		items.append(
			{
				"idx": item.idx,
				"item_code": item.item_code,
				"item_name": item.item_name,
				"qty": item.qty,
				"uom": item.uom,
			}
		)

	workstations = {}
	for op in operations:
		ws = op["workstation"]
		if ws not in workstations:
			ws_doc = frappe.get_value("Workstation", ws, ["name", "description"], as_dict=True)
			workstations[ws] = {
				"name": ws,
				"description": ws_doc.get("description") if ws_doc else "",
				"operations": [],
			}
		workstations[ws]["operations"].append(op)

	return {
		"bom_name": bom.name,
		"item": bom.item,
		"item_name": bom.item_name,
		"operations": operations,
		"items": items,
		"workstations": list(workstations.values()),
	}


@frappe.whitelist()
def get_bom_list(item=None, production_line=None):
	"""Submitted BOMs with operations, optionally only those a production line plans.

	A line with an empty plan restricts nothing — the page would otherwise go blank on a line
	that is set up but not planned yet, which reads as a broken page rather than an empty plan.
	"""
	filters = {"docstatus": 1, "with_operations": 1}
	if item:
		filters["item"] = item

	if production_line:
		planned = _planned_items(production_line)
		if planned:
			if item and item not in planned:
				return []
			if not item:
				filters["item"] = ["in", planned]

	return frappe.get_all(
		"BOM",
		filters=filters,
		fields=["name", "item", "item_name"],
		order_by="creation desc",
		limit=50,
	)


def _planned_items(production_line):
	"""The items the line's enabled plan rows name."""
	return frappe.get_all(
		"Production Line Item",
		filters={"parent": production_line, "parenttype": "Production Line", "enabled": 1},
		pluck="item_code",
		distinct=True,
	)


@frappe.whitelist()
def get_production_line(production_line):
	"""The line as the page shows it: its benches, their printers, operations and workstations.

	Operations come from `Workplace.allowed_operations`, which is also what decides the Job
	Cards the line may hand out at that bench — so the same rows explain both the diagram and
	what an operator is offered.
	"""
	line = frappe.get_doc("Production Line", production_line)

	workplaces = []
	for row in line.workplaces:
		if not row.workplace:
			continue
		doc = frappe.get_cached_doc("Workplace", row.workplace)
		workplaces.append(
			{
				"name": doc.name,
				"workplace_name": doc.workplace_name or doc.name,
				"short_name": doc.short_name,
				"is_active": doc.is_active,
				"enabled": row.enabled,
				"otdr_configuration": doc.otdr_configuration,
				"workplace_script": doc.workplace_script,
				"employees": len(doc.allowed_employees),
				"printers": [
					{
						"label_printer": p.label_printer,
						"printer_model": p.printer_model,
						"is_default": p.is_default,
					}
					for p in doc.printers
				],
				"operations": [
					{"operation": o.operation, "workstation": o.workstation} for o in doc.allowed_operations
				],
			}
		)

	plan = []
	for row in line.plan:
		plan.append(
			{
				"item_code": row.item_code,
				"item_name": frappe.db.get_value("Item", row.item_code, "item_name"),
				"workplace": row.workplace,
				"daily_qty": row.daily_qty,
				"enabled": row.enabled,
				"default_bom": frappe.db.get_value("Item", row.item_code, "default_bom"),
			}
		)

	# Flat sets the page uses to mark the diagram: a workstation of ours, an operation of ours.
	workstations = []
	operations = []
	for wp in workplaces:
		if not wp["enabled"]:
			continue
		for op in wp["operations"]:
			if op["workstation"] and op["workstation"] not in workstations:
				workstations.append(op["workstation"])
			if op["operation"] and op["operation"] not in operations:
				operations.append(op["operation"])

	return {
		"name": line.name,
		"line_name": line.line_name,
		"line_type": line.line_type,
		"enabled": line.enabled,
		"plan_time": line.plan_time,
		"overflow_qty": line.overflow_qty,
		"source_warehouse": line.source_warehouse,
		"wip_warehouse": line.wip_warehouse,
		"fg_warehouse": line.fg_warehouse,
		"workplaces": workplaces,
		"plan": plan,
		"workstations": workstations,
		"operations": operations,
		"planned_items": _planned_items(line.name),
	}
