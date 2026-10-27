"""Physical custody of customer property, independent of the stock ledger."""

import json

import frappe
from frappe import _

STATES = {
	"receive": ({"Awaiting Receipt"}, "Received"),
	"transfer": (
		{"Received", "In Repair", "Waiting for Parts", "Waiting for Customer", "Ready for Dispatch"},
		None,
	),
	"dispatch": ({"Ready for Dispatch"}, "Dispatched"),
	"dispose": ({"Ready for Dispatch"}, "Disposed"),
}


def default_warehouse(company):
	name = frappe.db.get_single_value("Repair Settings", "repair_warehouse")
	if not name:
		return None
	values = frappe.db.get_value("Warehouse", name, ["company", "is_group", "disabled"], as_dict=True)
	return (
		name if values and values.company == company and not values.is_group and not values.disabled else None
	)


def logistics_request(order):
	request = frappe.get_doc("Issue", order.issue)
	request.check_permission("write")
	return request


def sync_units(order):
	for row in order.items:
		frappe.db.set_value(
			"Repair Unit",
			row.repair_unit,
			{"warehouse": row.warehouse, "status": row.status},
			update_modified=False,
		)


def create_movement(order, names, action, warehouse=None, waybill=None, approval=None, serials=None):
	from erpnext.support.service_repair import _rows

	rows = _rows(order, names)
	frappe.has_permission("Repair Movement", "create", throw=True)
	frappe.has_permission("Repair Movement", "submit", throw=True)
	request = logistics_request(order) if action != "transfer" else None
	serials = frappe.parse_json(serials) if isinstance(serials, str) else (serials or {})
	if not isinstance(serials, dict) or set(serials) - {row.repair_unit for row in rows}:
		frappe.throw(_("Specify serial numbers only for the selected repair units."))
	movement = frappe.get_doc(
		{
			"doctype": "Repair Movement",
			"repair_order": order.name,
			"company": order.company,
			"action": action,
			"warehouse": warehouse or (default_warehouse(order.company) if action == "receive" else None),
			"items": [
				{
					"repair_unit": row.repair_unit,
					"factory_serial": serials.get(row.repair_unit, row.factory_serial),
				}
				for row in rows
			],
		}
	)
	# The shipment is recorded on the support request, never on the technician's order.
	movement.insert()
	if action in {"dispatch", "dispose"}:
		if action == "dispatch" and (not waybill or not request.custom_repair_return_address):
			frappe.throw(_("Enter the outbound waybill and return address before dispatch."))
		if action == "dispose":
			file_name = frappe.db.get_value("File", {"file_url": approval}, "name") if approval else None
			if not file_name:
				frappe.throw(_("Attach the customer's disposal approval first."))
			frappe.get_doc("File", file_name).check_permission("read")
		for row in rows:
			request.append(
				"custom_repair_shipments",
				{
					"repair_unit": row.repair_unit,
					"movement": movement.name,
					"waybill": waybill if action == "dispatch" else None,
					"approval": approval if action == "dispose" else None,
				},
			)
		request.flags.repair_action = True
		request.save()
	movement.submit()
	return movement.name


def validate_movement(doc):
	from erpnext.support.service_repair import _order, _rows, _warehouse

	if doc.action == "transfer":
		frappe.throw(_("Customer repair units cannot be transferred between warehouses."))
	order = _order(doc.repair_order)
	if doc.action not in STATES or doc.company != order.company:
		frappe.throw(_("Invalid repair action."))
	if doc.action != "transfer":
		logistics_request(order)
	names = [row.repair_unit for row in doc.items]
	rows = _rows(order, names)
	allowed, _next = STATES[doc.action]
	if any(row.status not in allowed for row in rows):
		frappe.throw(_("The selected units are not at the required repair stage."))
	if doc.action in {"receive", "transfer"}:
		_warehouse(doc.warehouse, order.company, check_permission=False)
	elif doc.warehouse:
		frappe.throw(_("An outbound repair movement cannot have a destination warehouse."))
	if doc.action != "receive" and any(not row.warehouse for row in rows):
		frappe.throw(_("Receive the unit before repair; confirm delivery only after dispatch."))
	if doc.action == "dispose" and any(row.outcome != "Not Repairable" for row in rows):
		frappe.throw(_("Disposal requires a Not Repairable result and the customer's approval file."))
	if doc.action in {"dispatch", "dispose"} and doc._action == "submit":
		request = logistics_request(order)
		shipments = {
			row.repair_unit: row
			for row in request.get("custom_repair_shipments", [])
			if row.movement == doc.name and not row.cancelled
		}
		if any(name not in shipments for name in names):
			frappe.throw(_("Register dispatch and disposal from the service request."))
		if doc.action == "dispatch" and (
			not request.custom_repair_return_address or any(not shipments[name].waybill for name in names)
		):
			frappe.throw(_("Enter the outbound waybill and return address before dispatch."))
		if doc.action == "dispose" and any(not shipments[name].approval for name in names):
			frappe.throw(_("Attach the customer's disposal approval first."))
	for detail, row in zip(doc.items, rows, strict=True):
		unit = frappe.get_doc("Repair Unit", row.repair_unit)
		if unit.company != order.company or unit.warehouse != row.warehouse:
			frappe.throw(_("The repair unit does not match the order's current custody."))
		if doc.action != "receive" and detail.factory_serial != unit.factory_serial:
			frappe.throw(_("Confirm the factory serial number during receipt."))


def snapshot_movement(doc):
	from erpnext.support.service_repair import _order, _rows

	order = _order(doc.repair_order)
	rows = _rows(order, [row.repair_unit for row in doc.items])
	for detail, row in zip(doc.items, rows, strict=True):
		detail.previous_state = json.dumps(
			{
				"row": {
					key: row.get(key) for key in ("status", "warehouse", "last_action", "factory_serial")
				},
				"factory_serial": frappe.db.get_value("Repair Unit", row.repair_unit, "factory_serial"),
			}
		)


def submit_movement(doc):
	from erpnext.support.service_repair import _order, _rows, _save

	order = _order(doc.repair_order)
	rows = _rows(order, [row.repair_unit for row in doc.items])
	for detail, row in zip(doc.items, rows, strict=True):
		row.warehouse = doc.warehouse if doc.action in {"receive", "transfer"} else None
		row.status = STATES[doc.action][1] or row.status
		row.last_action = doc.name
		if doc.action == "receive":
			row.factory_serial = detail.factory_serial
			frappe.db.set_value("Repair Unit", row.repair_unit, "factory_serial", detail.factory_serial)
	_save(order)


def validate_cancellation(doc):
	from erpnext.support.service_repair import _order, _rows

	saved = frappe.get_doc("Repair Movement", doc.name, for_update=True)
	if any(doc.get(key) != saved.get(key) for key in ("repair_order", "action", "company", "warehouse")) or [
		r.repair_unit for r in doc.items
	] != [r.repair_unit for r in saved.items]:
		frappe.throw(_("Use repair actions to change repair units."))
	order = _order(saved.repair_order)
	if saved.action != "transfer":
		logistics_request(order)
	rows = _rows(order, [row.repair_unit for row in saved.items])
	states = {}
	for detail, row in zip(saved.items, rows, strict=True):
		if row.last_action != saved.name:
			frappe.throw(
				_(
					"A later repair action exists. Cancel movements in reverse order before changing this movement."
				)
			)
		before = frappe.parse_json(detail.previous_state)
		if not before or not before.get("row"):
			frappe.throw(_("This repair movement has no cancellation snapshot."))
		states[row.repair_unit] = before
	doc.flags.repair_cancellation_states = states


def cancel_movement(doc):
	from erpnext.support.service_repair import _order, _rows, _save

	order = _order(doc.repair_order)
	if doc.action != "transfer":
		request = logistics_request(order)
	rows = _rows(order, [row.repair_unit for row in doc.items])
	for row in rows:
		if row.last_action != doc.name:
			frappe.throw(
				_(
					"A later repair action exists. Cancel movements in reverse order before changing this movement."
				)
			)
		before = doc.flags.repair_cancellation_states[row.repair_unit]
		if not before or not before.get("row"):
			frappe.throw(_("This repair movement has no cancellation snapshot."))
		row.update(before["row"])
		frappe.db.set_value("Repair Unit", row.repair_unit, "factory_serial", before.get("factory_serial"))
	if doc.action in {"dispatch", "dispose"}:
		for row in request.get("custom_repair_shipments", []):
			if row.movement == doc.name:
				row.cancelled = 1
		request.flags.repair_action = True
		request.save()
	_save(order)


def sync_existing_units():
	"""Keep existing repair episodes and stock documents intact during the transition."""
	if not frappe.db.exists("DocType", "Repair Unit"):
		return
	for name in frappe.get_all("Repair Order", pluck="name", order_by="modified asc"):
		order = frappe.get_doc("Repair Order", name)
		sync_units(order)
		request = frappe.get_doc("Issue", order.issue)
		for row in order.items:
			unit = frappe.get_doc("Repair Unit", row.repair_unit)
			frappe.db.set_value(
				"Repair Order Item",
				row.name,
				{"item_code": unit.item_code, "factory_serial": unit.factory_serial},
				update_modified=False,
			)
			frappe.db.set_value(
				"Repair Unit",
				unit.name,
				{"customer": request.customer, "sender_contact": request.contact},
				update_modified=False,
			)
