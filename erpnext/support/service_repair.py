"""Service repair episodes and spare-part consumption; custody has its own register."""

import json

import frappe
from frappe import _
from frappe.utils import flt

TERMINAL = {"Delivered", "Disposed"}
IN_WORKSHOP = {"Received", "In Repair", "Waiting for Parts", "Waiting for Customer", "Ready for Dispatch"}
TRANSITIONS = {"parts": ({"In Repair", "Waiting for Parts"}, None, "Material Issue")}


def aggregate_status(rows):
	states = [row.status for row in rows]
	if not states or all(s == "Awaiting Receipt" for s in states):
		return "Awaiting Receipt"
	if all(s in TERMINAL for s in states):
		return "Closed"
	if all(s in TERMINAL | {"Dispatched"} for s in states):
		return "Dispatched"
	if all(s in TERMINAL | {"Dispatched", "Ready for Dispatch"} for s in states):
		return "Ready for Dispatch"
	if any(
		s in {"In Repair", "Waiting for Parts", "Waiting for Customer", "Ready for Dispatch", "Dispatched"}
		for s in states
	):
		return "In Repair"
	return "Received"


def _lock(doctype, name):
	table = frappe.qb.DocType(doctype)
	frappe.qb.from_(table).select(table.name).where(table.name == name).for_update().run()


def _order(name):
	doc = frappe.get_doc("Repair Order", name, for_update=True)
	doc.check_permission("write")
	if frappe.db.exists("Repair Unit", {"legacy_order": name}):
		frappe.throw(_("Continue this repair in its individual repair cards."))
	return doc


def _rows(doc, names):
	names = frappe.parse_json(names) if isinstance(names, str) else names
	if not isinstance(names, list) or not names or len(names) != len(set(names)):
		frappe.throw(_("Select one or more distinct repair units."))
	by_name = {row.repair_unit: row for row in doc.items}
	rows = [by_name[name] for name in names if name in by_name]
	if len(rows) != len(names):
		frappe.throw(_("Selected units do not belong to this repair order."))
	return rows


def _save(doc):
	doc.status = aggregate_status(doc.items)
	doc.total_cost = sum(flt(r.labor_cost) + flt(r.parts_cost) for r in doc.items)
	doc.flags.repair_action = True
	doc.save()
	from erpnext.support.repair_custody import sync_units

	sync_units(doc)


def validate_issue(doc, method=None):
	from erpnext.support.repair_units import validate_issue as validate_request

	validate_request(doc)


@frappe.whitelist()
def create_order(issue: str):
	request = frappe.get_doc("Issue", issue, for_update=True)
	request.check_permission("write")
	if request.get("custom_repair_order"):
		return request.custom_repair_order
	frappe.throw(
		_("Create individual repair cards from the service request instead of a grouped repair order.")
	)


def validate_order(doc):
	before = doc.get_doc_before_save()
	if not doc.flags.get("repair_action"):
		if doc.is_new():
			frappe.throw(_("Create a repair order from the service request."))
		for field in ("issue", "company", "currency", "support_user", "status", "total_cost"):
			if doc.get(field) != before.get(field):
				frappe.throw(_("Use repair actions to change the repair stage."))
		keys = [
			f.fieldname
			for f in frappe.get_meta("Repair Order Item").fields
			if f.fieldtype not in ("Section Break", "Column Break")
		]
		if len(doc.items) != len(before.items) or any(
			any(a.get(k) != b.get(k) for k in keys) for a, b in zip(doc.items, before.items, strict=False)
		):
			frappe.throw(_("Use repair actions to change repair units."))
	if doc.repair_user:
		user = frappe.get_doc("User", doc.repair_user)
		if (
			not user.enabled
			or user.user_type != "System User"
			or not frappe.has_permission("Repair Order", "write", user=user.name)
		):
			frappe.throw(_("Choose an enabled repair user with access to Repair Order."))


def order_updated(doc):
	before = doc.get_doc_before_save()
	working = doc.status not in {"Ready for Dispatch", "Dispatched", "Closed"}
	reassigned = not before or doc.repair_user != before.repair_user
	returned_to_repair = before and before.status in {"Ready for Dispatch", "Dispatched"} and working
	if working and (reassigned or returned_to_repair):
		_close_assignments(doc)
		if doc.repair_user:
			_assign(doc, doc.repair_user, _("Repair order {0} assigned for repair").format(doc.name))
	if before and before.status != doc.status and doc.status == "Ready for Dispatch":
		_close_assignments(doc)
		_assign(doc, doc.support_user, _("Repair order {0} is ready for dispatch").format(doc.name))
	if before and before.status != doc.status and doc.status == "Closed":
		_close_assignments(doc)


def _close_assignments(doc):
	for name in frappe.get_all(
		"ToDo",
		filters={
			"reference_type": doc.doctype,
			"reference_name": doc.name,
			"custom_repair_managed": 1,
			"status": "Open",
		},
		pluck="name",
	):
		todo = frappe.get_doc("ToDo", name)
		todo.status = "Closed"
		todo.save(ignore_permissions=True)


def _assign(doc, user, message):
	from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

	if not frappe.db.exists(
		"ToDo",
		{
			"reference_type": doc.doctype,
			"reference_name": doc.name,
			"allocated_to": user,
			"status": "Open",
			"custom_repair_managed": 1,
		},
	):
		frappe.get_doc(
			{
				"doctype": "ToDo",
				"allocated_to": user,
				"assigned_by": frappe.session.user,
				"reference_type": doc.doctype,
				"reference_name": doc.name,
				"description": message,
				"status": "Open",
				"custom_repair_managed": 1,
			}
		).insert(ignore_permissions=True)
	enqueue_create_notification(
		[user],
		{
			"type": "Alert",
			"document_type": doc.doctype,
			"document_name": doc.name,
			"subject": message,
			"from_user": frappe.session.user,
		},
	)


@frappe.whitelist()
def update_units(
	order: str,
	units: str | list,
	status: str,
	diagnosis: str | None = None,
	work_done: str | None = None,
	outcome: str | None = None,
	labor_cost: float | str | None = None,
	cost_note: str | None = None,
):
	doc = _order(order)
	if status == "Delivered":
		from erpnext.support.repair_custody import logistics_request

		logistics_request(doc)
	rows = _rows(doc, units)
	if status not in {
		"In Repair",
		"Waiting for Parts",
		"Waiting for Customer",
		"Ready for Dispatch",
		"Delivered",
	}:
		frappe.throw(_("Invalid repair stage."))
	if outcome and outcome not in {"Repaired", "No Fault Found", "Not Repairable"}:
		frappe.throw(_("Invalid repair result."))
	for row in rows:
		allowed = {"Dispatched"} if status == "Delivered" else IN_WORKSHOP
		if row.status not in allowed:
			frappe.throw(_("Receive the unit before repair; confirm delivery only after dispatch."))
		if status == "Ready for Dispatch" and (
			not work_done or outcome not in {"Repaired", "No Fault Found", "Not Repairable"}
		):
			frappe.throw(_("Specify work done and the repair result before marking the unit ready."))
		if flt(labor_cost) < 0 or (flt(labor_cost) and not cost_note):
			frappe.throw(_("Provide a cost explanation and a non-negative labor/external cost."))
		row.status = status
		if status != "Delivered":
			row.diagnosis = diagnosis or row.diagnosis
			row.work_done = work_done or row.work_done
			row.outcome = outcome or row.outcome
			if labor_cost not in (None, ""):
				row.labor_cost = flt(labor_cost)
				row.cost_note = cost_note
		row.last_action = frappe.generate_hash(length=12)
	_save(doc)
	return doc.name


def _warehouse(name, company, check_permission=True):
	doc = frappe.get_doc("Warehouse", name)
	if check_permission:
		doc.check_permission("read")
	if doc.company != company or doc.is_group or doc.disabled:
		frappe.throw(_("Choose an active non-group warehouse of the repair company."))


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def repair_warehouse_query(
	doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict
):
	from frappe.utils import cint

	order = frappe.get_doc("Repair Order", (filters or {}).get("repair_order"))
	order.check_permission("write")
	# Only names of eligible locations for this repair are exposed; no stock access is granted.
	return frappe.get_all(
		"Warehouse",
		filters={"company": order.company, "is_group": 0, "disabled": 0, "name": ["like", f"%{txt}%"]},
		fields=["name"],
		as_list=True,
		start=max(cint(start), 0),
		page_length=min(max(cint(page_len), 1), 50),
	)


@frappe.whitelist()
def make_movement(
	order: str,
	units: str | list,
	action: str,
	warehouse: str | None = None,
	waybill: str | None = None,
	approval: str | None = None,
	parts: str | list | None = None,
	serials: str | dict | None = None,
):
	"""Register customer custody immediately; actual spare parts use a draft Stock Entry."""
	doc = _order(order)
	if action != "parts":
		from erpnext.support.repair_custody import create_movement

		return create_movement(doc, units, action, warehouse, waybill, approval, serials)
	rows = _rows(doc, units)
	if action not in TRANSITIONS:
		frappe.throw(_("Invalid repair action."))
	frappe.has_permission("Stock Entry", "create", throw=True)
	allowed, _next, purpose = TRANSITIONS[action]
	if any(r.status not in allowed for r in rows):
		frappe.throw(_("The selected units are not at the required repair stage."))
	if action in ("receive", "transfer"):
		_warehouse(warehouse, doc.company)
	entry = frappe.new_doc("Stock Entry")
	entry.company = doc.company
	entry.purpose = entry.stock_entry_type = purpose
	entry.custom_repair_order = doc.name
	entry.custom_repair_action = action
	entry.custom_repair_data = json.dumps({"waybill": waybill, "approval": approval})
	if action == "parts":
		parts = frappe.parse_json(parts) if isinstance(parts, str) else parts
		if len(rows) != 1 or not parts:
			frappe.throw(_("Select one repair unit and specify the consumed parts."))
		for part in parts:
			_warehouse(part.get("warehouse"), doc.company)
			if flt(part.get("qty")) <= 0:
				frappe.throw(_("Part quantity must be greater than zero."))
			entry.append(
				"items",
				{
					"item_code": part["item_code"],
					"qty": flt(part["qty"]),
					"s_warehouse": part["warehouse"],
					"custom_repair_unit": rows[0].repair_unit,
					"use_serial_batch_fields": 1,
					"serial_no": part.get("serial_no"),
					"batch_no": part.get("batch_no"),
				},
			)
	entry.insert()
	return entry.name


def validate_stock_entry(entry, method=None):
	if entry.get("custom_repair_unit"):
		from erpnext.support.repair_unit_movement import validate_parts

		return validate_parts(entry)
	if not entry.get("custom_repair_order"):
		return
	order = _order(entry.custom_repair_order)
	action = entry.custom_repair_action
	if action != "parts":
		frappe.throw(_("Register customer property movements in the repair register."))
	if action not in TRANSITIONS:
		frappe.throw(_("Invalid repair action."))
	allowed, _next, purpose = TRANSITIONS[action]
	if entry.purpose != purpose or entry.company != order.company or entry.additional_costs:
		frappe.throw(_("Repair movement purpose, company and zero additional costs must be preserved."))
	rows = _rows(order, list(dict.fromkeys(r.custom_repair_unit for r in entry.items)))
	if action != "parts" and len(rows) != len(entry.items):
		frappe.throw(_("Each repair movement row must represent exactly one unit."))
	if action == "parts" and len(rows) != 1:
		frappe.throw(_("Consume parts for one repair unit at a time."))
	info = frappe.parse_json(entry.custom_repair_data or "{}")
	for row in rows:
		_lock("Repair Unit", row.repair_unit)
		if row.status not in allowed:
			frappe.throw(_("The selected units are not at the required repair stage."))
	for detail in entry.items:
		row = next(r for r in rows if r.repair_unit == detail.custom_repair_unit)
		if action == "parts":
			if detail.t_warehouse or not detail.s_warehouse or flt(detail.qty) <= 0:
				frappe.throw(_("Use actual spare parts and a source warehouse for repair consumption."))
		if detail.s_warehouse:
			_warehouse(detail.s_warehouse, order.company)
	if entry._action == "submit":
		# Cancellation can restore the exact episode, but only if no later action occurred.
		info["before"] = {
			r.repair_unit: {
				k: r.get(k)
				for k in (
					"status",
					"warehouse",
					"last_stock_entry",
					"last_action",
					"parts_cost",
					"outbound_waybill",
					"disposal_approval",
				)
			}
			for r in rows
		}
		entry.custom_repair_data = json.dumps(info)


def submit_stock_entry(entry, method=None):
	if entry.get("custom_repair_unit"):
		from erpnext.support.repair_unit_movement import parts_posted

		return parts_posted(entry)
	if not entry.get("custom_repair_order"):
		return
	order = _order(entry.custom_repair_order)
	action = entry.custom_repair_action
	for row in order.items:
		details = [d for d in entry.items if d.custom_repair_unit == row.repair_unit]
		if not details:
			continue
		if action == "parts":
			row.parts_cost = flt(row.parts_cost) + sum(flt(d.amount) for d in details)

		row.last_stock_entry = row.last_action = entry.name
	_save(order)


def cancel_stock_entry(entry, method=None):
	if entry.get("custom_repair_unit"):
		from erpnext.support.repair_unit_movement import parts_posted

		return parts_posted(entry, cancelled=True)
	if not entry.get("custom_repair_order"):
		return
	order = _order(entry.custom_repair_order)
	info = frappe.parse_json(entry.custom_repair_data)
	if not info.get("before"):
		frappe.throw(_("This repair movement has no cancellation snapshot."))
	for row in order.items:
		if row.repair_unit not in info["before"]:
			continue
		if row.last_action != entry.name:
			frappe.throw(
				_(
					"A later repair action exists. Cancel movements in reverse order before changing this movement."
				)
			)
		row.update(info["before"][row.repair_unit])
	_save(order)


@frappe.whitelist()
def get_summary(doctype: str, name: str):
	if doctype in {"Issue", "Repair Unit"}:
		from erpnext.support.repair_units import summary

		doc = frappe.get_doc(doctype, name)
		doc.check_permission("read")
		return summary(doc)
	doc = frappe.get_doc(doctype, name) if doctype in ("Issue", "Repair Order", "Repair Unit") else None
	if not doc:
		frappe.throw(_("Invalid repair document."))
	doc.check_permission("read")
	if doctype == "Repair Unit":
		parents = frappe.get_all("Repair Order Item", filters={"repair_unit": name}, pluck="parent")
		return {
			"orders": frappe.get_list(
				"Repair Order",
				filters={"name": ["in", parents]},
				fields=["name", "status", "issue"],
				order_by="creation desc",
			)
			if parents
			else [],
			"warehouse": doc.warehouse,
		}
	if doctype == "Issue":
		if not doc.get("custom_repair_order"):
			return {"status": "Awaiting Receipt", "items": []}
		doc = frappe.get_doc("Repair Order", doc.custom_repair_order)
		doc.check_permission("read")
	from erpnext.support.repair_custody import default_warehouse

	part_movements = (
		[
			dict(row, doctype="Stock Entry")
			for row in frappe.get_list(
				"Stock Entry",
				filters={"custom_repair_order": doc.name, "custom_repair_action": "parts"},
				fields=["name", "docstatus", "custom_repair_action"],
				order_by="creation desc",
			)
		]
		if frappe.has_permission("Stock Entry", "read")
		else []
	)
	return {
		"default_warehouse": default_warehouse(doc.company),
		"order": doc.name,
		"status": doc.status,
		"support_user": frappe.db.get_value(
			"User", doc.support_user, ["name as user", "full_name", "user_image"], as_dict=True
		),
		"repair_user": frappe.db.get_value(
			"User", doc.repair_user, ["name as user", "full_name", "user_image"], as_dict=True
		)
		if doc.repair_user
		else None,
		"items": [
			{
				key: r.get(key)
				for key in (
					"repair_unit",
					"product_name",
					"item_code",
					"factory_serial",
					"status",
					"warehouse",
				)
			}
			for r in doc.items
		],
		"movements": [
			dict(row, doctype="Repair Movement")
			for row in frappe.get_list(
				"Repair Movement",
				filters={"repair_order": doc.name},
				fields=["name", "docstatus", "action as custom_repair_action"],
				order_by="creation desc",
			)
		]
		+ part_movements,
		"legacy_stock_entries": frappe.get_list(
			"Stock Entry",
			filters={
				"custom_repair_order": doc.name,
				"custom_repair_action": ["!=", "parts"],
				"docstatus": 1,
			},
			pluck="name",
		)
		if frappe.has_permission("Stock Entry", "read")
		else [],
	}
