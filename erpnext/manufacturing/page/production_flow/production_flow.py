import frappe


@frappe.whitelist()
def get_bom_flow(bom_name):
	bom = frappe.get_doc("BOM", bom_name)
	if not bom.with_operations:
		return {"operations": [], "items": [], "swim_lanes": []}

	operations = []
	for op in bom.operations:
		operations.append({
			"idx": op.idx,
			"operation": op.operation,
			"workstation": op.workstation,
			"time_in_mins": op.time_in_mins,
			"description": op.description,
		})

	items = []
	for item in bom.items:
		items.append({
			"idx": item.idx,
			"item_code": item.item_code,
			"item_name": item.item_name,
			"qty": item.qty,
			"uom": item.uom,
		})

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
def get_bom_list(item=None):
	filters = {"docstatus": 1, "with_operations": 1}
	if item:
		filters["item"] = item
	return frappe.get_all(
		"BOM",
		filters=filters,
		fields=["name", "item", "item_name"],
		order_by="creation desc",
		limit=50,
	)
