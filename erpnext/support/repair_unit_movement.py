"""Custody and spare-part movements for individual repair cards."""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from erpnext.support import repair_units as repairs
from erpnext.support.repair_custody import STATES

DELIVERY_TYPES = {"Nova Poshta", "Ukrposhta", "Taxi", "Self Pickup", "Other"}
POSTAL_TYPES = {"Nova Poshta", "Ukrposhta"}


def validate_delivery(delivery_type, waybill, details):
	if delivery_type not in DELIVERY_TYPES:
		frappe.throw(_("Choose a delivery type for receipt or dispatch."))
	if delivery_type in POSTAL_TYPES:
		if not (waybill or "").strip():
			frappe.throw(_("Enter a waybill for postal delivery."))
	elif not (details or "").strip():
		frappe.throw(_("Enter delivery details for taxi, self pickup or other delivery."))


def validate_approval(approved, attachment):
	if not cint(approved):
		frappe.throw(_("Confirm that the customer agreed to disposal."))
	if attachment:
		name = frappe.db.get_value("File", {"file_url": attachment}, "name")
		if not name:
			frappe.throw(_("Attach a saved disposal approval file."))
		frappe.get_doc("File", name).check_permission("read")


def selected(issue, names):
	from erpnext.support.service_repair import _lock

	_lock("Issue", issue)
	names = frappe.parse_json(names) if isinstance(names, str) else names
	if not isinstance(names, list) or not names or len(names) != len(set(names)):
		frappe.throw(_("Select one or more distinct repair units."))
	docs = {name: repairs.unit_doc(name) for name in sorted(names)}
	if any(doc.issue != issue for doc in docs.values()):
		frappe.throw(_("Selected units do not belong to this service request."))
	return [docs[name] for name in names]


@frappe.whitelist()
def register(
	issue: str,
	units: str | list,
	action: str,
	warehouse: str | None = None,
	serials: str | dict | None = None,
	waybill: str | None = None,
	approval: str | None = None,
	delivery_type: str | None = None,
	delivery_details: str | None = None,
	disposal_approved: int | str = 0,
):
	docs = selected(issue, units)
	request = repairs.issue_doc(issue) if action != "transfer" else None
	serials = frappe.parse_json(serials) if isinstance(serials, str) else (serials or {})
	if not isinstance(serials, dict) or set(serials) - {doc.name for doc in docs}:
		frappe.throw(_("Specify serial numbers only for the selected repair units."))
	if action in {"receive", "dispatch"}:
		validate_delivery(delivery_type, waybill, delivery_details)
	if action == "dispose":
		validate_approval(disposal_approved, approval)
	entry = frappe.get_doc(
		{
			"doctype": "Repair Movement",
			"issue": issue,
			"company": docs[0].company,
			"action": action,
			"delivery_type": delivery_type if action in {"receive", "dispatch"} else None,
			"waybill": waybill if delivery_type in POSTAL_TYPES else None,
			"delivery_details": delivery_details if delivery_type not in POSTAL_TYPES else None,
			"disposal_approved": cint(disposal_approved) if action == "dispose" else 0,
			"approval": approval if action == "dispose" else None,
			"warehouse": warehouse
			or (repairs.warehouse_for(docs[0].company) if action == "receive" else None),
			"items": [
				{"repair_unit": doc.name, "factory_serial": serials.get(doc.name, doc.factory_serial)}
				for doc in docs
			],
		}
	)
	entry.insert()
	if action in {"dispatch", "dispose"}:
		with repairs.internal_action():
			for doc in docs:
				request.append(
					"custom_repair_shipments",
					{
						"repair_unit": doc.name,
						"movement": entry.name,
						"waybill": entry.waybill,
						"delivery_type": entry.delivery_type,
						"delivery_details": entry.delivery_details,
						"disposal_approved": entry.disposal_approved,
						"approval": entry.approval,
					},
				)
			request.save()
	entry.submit()
	return entry.name


def validate(doc):
	if doc.action == "transfer":
		frappe.throw(_("Customer repair units cannot be transferred between warehouses."))
	units = selected(doc.issue, [row.repair_unit for row in doc.items])
	if doc.action not in STATES or any(unit.company != doc.company for unit in units):
		frappe.throw(_("Invalid repair action."))
	if doc.action in {"receive", "dispatch"}:
		validate_delivery(doc.delivery_type, doc.waybill, doc.delivery_details)
	if doc.action == "dispose":
		validate_approval(doc.disposal_approved, doc.approval)
	request = repairs.issue_doc(doc.issue) if doc.action != "transfer" else None
	if any(unit.status not in STATES[doc.action][0] for unit in units):
		frappe.throw(_("The selected units are not at the required repair stage."))
	if doc.action in {"receive", "transfer"}:
		repairs.validate_warehouse(doc.warehouse, doc.company)
	elif doc.warehouse:
		frappe.throw(_("An outbound repair movement cannot have a destination warehouse."))
	if doc.action != "receive" and any(not unit.warehouse or not unit.received_on for unit in units):
		frappe.throw(_("Receive the unit before repair; confirm delivery only after dispatch."))
	if doc.action == "dispose" and any(unit.outcome != "Not Repairable" for unit in units):
		frappe.throw(_("Only units with a Not Repairable result can be disposed of."))
	if doc._action == "submit" and doc.action in {"dispatch", "dispose"}:
		shipments = {
			row.repair_unit: row
			for row in request.custom_repair_shipments
			if row.movement == doc.name and not row.cancelled
		}
		if any(unit.name not in shipments for unit in units):
			frappe.throw(_("Register dispatch and disposal from the service request."))
		for unit in units:
			row = shipments[unit.name]
			if any(
				row.get(key) != doc.get(key)
				for key in ("delivery_type", "waybill", "delivery_details", "disposal_approved", "approval")
			):
				frappe.throw(_("Delivery and disposal details must match the recorded repair action."))
	for detail, unit in zip(doc.items, units, strict=True):
		if doc.action != "receive" and detail.factory_serial != unit.factory_serial:
			frappe.throw(_("Confirm the factory serial number during receipt."))


def before_submit(doc):
	for row, unit in zip(doc.items, selected(doc.issue, [row.repair_unit for row in doc.items]), strict=True):
		row.previous_state = json.dumps(
			{
				key: unit.get(key)
				for key in (
					"warehouse",
					"status",
					"received_on",
					"factory_serial",
					"last_action",
					"repair_user",
				)
			},
			default=str,
		)


def on_submit(doc):
	with repairs.internal_action():
		if doc.action == "receive":
			request = repairs.issue_doc(doc.issue)
			request.custom_repair_delivery_type = doc.delivery_type
			request.custom_repair_waybill = doc.waybill if doc.delivery_type in POSTAL_TYPES else None
			request.custom_repair_delivery_details = (
				doc.delivery_details if doc.delivery_type not in POSTAL_TYPES else None
			)
			request.save()
		for row, unit in zip(
			doc.items, selected(doc.issue, [row.repair_unit for row in doc.items]), strict=True
		):
			unit.warehouse = doc.warehouse if doc.action in {"receive", "transfer"} else None
			unit.status = STATES[doc.action][1] or unit.status
			unit.last_action = doc.name
			if doc.action == "receive":
				unit.received_on = now_datetime()
				unit.factory_serial = row.factory_serial
			unit.save()


def before_cancel(doc):
	saved = frappe.get_doc("Repair Movement", doc.name, for_update=True)
	if any(
		doc.get(key) != saved.get(key)
		for key in (
			"issue",
			"action",
			"company",
			"warehouse",
			"delivery_type",
			"waybill",
			"delivery_details",
			"disposal_approved",
			"approval",
		)
	) or [row.repair_unit for row in doc.items] != [row.repair_unit for row in saved.items]:
		frappe.throw(_("Use repair actions to change repair units."))
	if doc.action != "transfer":
		repairs.issue_doc(doc.issue)
	states = {}
	for row, unit in zip(
		saved.items, selected(saved.issue, [row.repair_unit for row in saved.items]), strict=True
	):
		if unit.last_action != doc.name:
			frappe.throw(
				_(
					"A later repair action exists. Cancel movements in reverse order before changing this movement."
				)
			)
		states[unit.name] = frappe.parse_json(row.previous_state)
	doc.flags.repair_unit_cancel_states = states


def on_cancel(doc):
	with repairs.internal_action():
		for unit in selected(doc.issue, [row.repair_unit for row in doc.items]):
			unit.update(doc.flags.repair_unit_cancel_states[unit.name])
			unit.save()
		if doc.action in {"dispatch", "dispose"}:
			request = repairs.issue_doc(doc.issue)
			for row in request.custom_repair_shipments:
				if row.movement == doc.name:
					row.cancelled = 1
			request.save()


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def warehouse_query(doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict):
	from frappe.utils import cint

	if filters.get("unit"):
		company = repairs.unit_doc(filters["unit"]).company
	else:
		company = repairs.issue_doc(filters.get("issue")).company
	return frappe.get_all(
		"Warehouse",
		filters={"company": company, "is_group": 0, "disabled": 0, "name": ["like", f"%{txt}%"]},
		fields=["name"],
		as_list=True,
		start=max(cint(start), 0),
		page_length=min(max(cint(page_len), 1), 50),
	)


@frappe.whitelist()
def consume_parts(unit: str, parts: str | list):
	doc = repairs.unit_doc(unit)
	repairs.check_work_access(doc)
	frappe.has_permission("Stock Entry", "create", throw=True)
	parts = frappe.parse_json(parts) if isinstance(parts, str) else parts
	if not parts:
		frappe.throw(_("Select one repair unit and specify the consumed parts."))
	entry = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"company": doc.company,
			"purpose": "Material Issue",
			"stock_entry_type": "Material Issue",
			"custom_repair_unit": doc.name,
		}
	)
	for part in parts:
		repairs.validate_warehouse(part.get("warehouse"), doc.company)
		if flt(part.get("qty")) <= 0:
			frappe.throw(_("Part quantity must be greater than zero."))
		entry.append(
			"items",
			{
				"item_code": part["item_code"],
				"qty": flt(part["qty"]),
				"s_warehouse": part["warehouse"],
				"custom_repair_unit": doc.name,
				"use_serial_batch_fields": 1,
				"serial_no": part.get("serial_no"),
				"batch_no": part.get("batch_no"),
			},
		)
	entry.insert()
	return entry.name


def validate_parts(entry):
	unit = repairs.unit_doc(entry.custom_repair_unit)
	repairs.check_work_access(unit)
	if entry.company != unit.company or entry.purpose != "Material Issue" or entry.additional_costs:
		frappe.throw(_("Use actual spare parts and a source warehouse for repair consumption."))
	for row in entry.items:
		if row.custom_repair_unit != unit.name or row.t_warehouse or not row.s_warehouse or flt(row.qty) <= 0:
			frappe.throw(_("Use actual spare parts and a source warehouse for repair consumption."))
		repairs.validate_warehouse(row.s_warehouse, unit.company)


def parts_posted(entry, cancelled=False):
	unit = repairs.unit_doc(entry.custom_repair_unit)
	if not cancelled:
		# Record the actual posting user, independently of draft owner or later edits.
		entry.custom_repair_data = json.dumps(
			{"posted_by": frappe.session.user, "posted_on": str(now_datetime())}
		)
		entry.db_set("custom_repair_data", entry.custom_repair_data, update_modified=False)
	with repairs.internal_action():
		unit.parts_cost = flt(unit.parts_cost) + sum(flt(row.amount) for row in entry.items) * (
			-1 if cancelled else 1
		)
		unit.total_cost = flt(unit.parts_cost) + flt(unit.labor_cost)
		unit.save()


def parts_history(unit):
	"""Expose only this card's consumed parts, without granting general stock access."""
	unit.check_permission("read")
	identities = {unit.name}
	if unit.legacy_order_item:
		identities.add(frappe.db.get_value("Repair Order Item", unit.legacy_order_item, "repair_unit"))
	details = frappe.get_all(
		"Stock Entry Detail",
		filters={"custom_repair_unit": ["in", list(identities - {None})], "docstatus": ["in", [1, 2]]},
		fields=[
			"parent",
			"custom_repair_unit",
			"item_code",
			"item_name",
			"qty",
			"uom",
			"basic_rate",
			"amount",
		],
		order_by="idx asc",
	)
	result = []
	for name in dict.fromkeys(row.parent for row in details):
		entry = frappe.get_doc("Stock Entry", name)
		if entry.company != unit.company or entry.purpose != "Material Issue":
			continue
		if not (
			entry.get("custom_repair_unit") == unit.name
			or (
				unit.legacy_order
				and entry.get("custom_repair_order") == unit.legacy_order
				and entry.get("custom_repair_action") == "parts"
			)
		):
			continue
		info = frappe.parse_json(entry.custom_repair_data or "{}")
		actor, date = info.get("posted_by"), info.get("posted_on")
		if not actor:
			# Historical postings may predate explicit author capture.
			for version in frappe.get_all(
				"Version",
				filters={"ref_doctype": "Stock Entry", "docname": name},
				fields=["owner", "creation", "data"],
				order_by="creation asc",
			):
				changes = frappe.parse_json(version.data or "{}").get("changed", [])
				if any(
					change[0] == "docstatus" and str(change[1]) == "0" and str(change[2]) == "1"
					for change in changes
				):
					actor, date = version.owner, version.creation
					break
		can_open = False
		if frappe.has_permission("Stock Entry", "read", doc=entry):
			can_open = True
		for row in details:
			if row.parent == name:
				result.append(
					{
						**{
							key: row.get(key)
							for key in ("item_code", "item_name", "qty", "uom", "basic_rate", "amount")
						},
						"stock_entry": name,
						"rate": flt(row.amount) / flt(row.qty) if flt(row.qty) else 0,
						"docstatus": entry.docstatus,
						"posted_by": actor,
						"posted_on": date,
						"posted_by_name": frappe.get_cached_value("User", actor, "full_name")
						if actor
						else None,
						"can_open": can_open,
					}
				)
	return result
