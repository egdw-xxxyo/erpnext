"""Individual repair episodes, work history and company-specific physical custody."""

import json
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import flt, now_datetime
from frappe.utils.data import cast

TERMINAL = {"Delivered", "Disposed"}
WORKING = {"Received", "In Repair", "Waiting for Parts", "Waiting for Customer", "Ready for Dispatch"}


@contextmanager
def internal_action():
	before = frappe.flags.repair_unit_action
	frappe.flags.repair_unit_action = True
	try:
		yield
	finally:
		frappe.flags.repair_unit_action = before


def warehouse_for(company):
	name = frappe.db.get_value(
		"Repair Company Warehouse",
		{"parent": "Repair Settings", "parenttype": "Repair Settings", "company": company},
		"warehouse",
	)
	if name:
		validate_warehouse(name, company)
	return name


def validate_warehouse(name, company):
	values = (
		frappe.db.get_value("Warehouse", name, ["company", "disabled", "is_group"], as_dict=True)
		if name
		else None
	)
	if not values or values.company != company or values.disabled or values.is_group:
		frappe.throw(_("Choose an active non-group warehouse of the repair company."))


def unit_doc(name, permission="write"):
	doc = frappe.get_doc("Repair Unit", name, for_update=True)
	doc.check_permission(permission)
	return doc


def issue_doc(name):
	doc = frappe.get_doc("Issue", name, for_update=True)
	doc.check_permission("write")
	return doc


def validate_issue(doc):
	if not doc.get("custom_service_repair"):
		if frappe.db.exists("Repair Unit", {"issue": doc.name}):
			frappe.throw(_("The repair request identity cannot be changed after creating its repair order."))
		return
	if not doc.company or not doc.contact or not doc.get("custom_repair_items"):
		frappe.throw(_("A repair request needs a company, sender contact and at least one product."))
	before = doc.get_doc_before_save()
	if before and frappe.db.exists("Repair Unit", {"issue": doc.name}):
		if any(doc.get(key) != before.get(key) for key in ("company", "customer", "contact")):
			frappe.throw(_("The repair request identity cannot be changed after creating its repair order."))
		current = {row.name: row for row in doc.custom_repair_items}
		for row in before.get("custom_repair_items", []):
			if row.repair_unit and (
				row.name not in current
				or any(
					current[row.name].get(key) != row.get(key)
					for key in (
						"repair_unit",
						"item_code",
						"product_name",
						"fault_description",
						"accessories",
						"photo",
						"previous_repair",
					)
				)
			):
				frappe.throw(
					_(
						"Products are fixed in the repair order. Create a new request for another repair episode."
					)
				)
	if not frappe.flags.repair_unit_action:
		old_shipments = [r.as_dict() for r in before.get("custom_repair_shipments", [])] if before else []
		new_shipments = [r.as_dict() for r in doc.get("custom_repair_shipments", [])]
		keys = (
			"repair_unit",
			"movement",
			"waybill",
			"approval",
			"cancelled",
			"delivery_type",
			"delivery_details",
			"disposal_approved",
		)
		if len(old_shipments) != len(new_shipments) or any(
			any(a.get(k) != b.get(k) for k in keys)
			for a, b in zip(old_shipments, new_shipments, strict=False)
		):
			frappe.throw(_("Register dispatch and disposal from the service request."))
		old_rows = {r.name: r.repair_unit for r in before.get("custom_repair_items", [])} if before else {}
		if any(row.repair_unit != old_rows.get(row.name) for row in doc.custom_repair_items):
			frappe.throw(_("Create repair units from a service request."))
	for row in doc.custom_repair_items:
		if row.repair_unit:
			values = frappe.db.get_value("Repair Unit", row.repair_unit, ["status", "outcome"], as_dict=True)
			row.repair_status = values.status
			row.repair_outcome = values.outcome
	if doc.status in {"Resolved", "Closed"} and any(
		not row.repair_unit or frappe.db.get_value("Repair Unit", row.repair_unit, "status") not in TERMINAL
		for row in doc.custom_repair_items
	):
		frappe.throw(_("Return or dispose of all repair units before closing the service request."))


def field_changed(doc, before, key):
	"""Compare form JSON with database values using the field's native type."""
	df = doc.meta.get_field(key)
	fieldtype = df.fieldtype if df else "Data"
	return cast(fieldtype, doc.get(key) or None) != cast(fieldtype, before.get(key) or None)


def validate_unit(doc):
	before = doc.get_doc_before_save()
	if frappe.flags.repair_unit_action:
		return
	if doc.is_new():
		frappe.throw(_("Create repair units from a service request."))
	protected = (
		"issue",
		"request_row",
		"previous_repair",
		"priority",
		"company",
		"item_code",
		"product_name",
		"factory_serial",
		"customer",
		"sender_contact",
		"warehouse",
		"status",
		"received_on",
		"repair_user",
		"support_user",
		"fault_description",
		"accessories",
		"photo",
		"parts_cost",
		"currency",
		"last_action",
		"legacy_order",
		"legacy_order_item",
		"stock_item",
		"serial_no",
	)
	if any(field_changed(doc, before, key) for key in protected):
		frappe.throw(_("Use repair actions to change repair units."))
	old = before.get("work_log", [])
	if len(doc.work_log) < len(old) or any(
		any(
			field_changed(b, a, key)
			for key in (
				"name",
				"performed_on",
				"performed_by",
				"notes",
				"photo",
				"attachment",
				"labor_cost",
				"cost_note",
			)
		)
		for a, b in zip(old, doc.work_log, strict=False)
	):
		frappe.throw(_("Repair work history is append-only. Add a new entry to correct earlier work."))
	work_changed = len(doc.work_log) != len(old) or any(
		doc.get(key) != before.get(key) for key in ("diagnosis", "work_done", "outcome")
	)
	if work_changed:
		check_work_access(doc)
	for row in doc.work_log[len(old) :]:
		if not (row.notes or row.photo or row.attachment):
			frappe.throw(_("Describe the work or attach a repair photo."))
		if flt(row.labor_cost) < 0 or (flt(row.labor_cost) and not row.cost_note):
			frappe.throw(_("Provide a cost explanation and a non-negative labor/external cost."))
		for url in (row.photo, row.attachment):
			if url:
				name = frappe.db.get_value("File", {"file_url": url}, "name")
				if not name:
					frappe.throw(_("Attach a saved file to the repair work entry."))
				frappe.get_doc("File", name).check_permission("read")
		row.performed_on = now_datetime()
		row.performed_by = frappe.session.user
	if work_changed:
		doc.last_action = frappe.generate_hash(length=12)
	doc.labor_cost = sum(flt(row.labor_cost) for row in doc.work_log)
	doc.total_cost = flt(doc.labor_cost) + flt(doc.parts_cost)


def check_work_access(doc):
	if not doc.received_on or doc.status not in WORKING:
		frappe.throw(_("Receive the unit before adding repair work."))
	if (
		doc.repair_user
		and doc.repair_user != frappe.session.user
		and not ({"Support Team", "System Manager"} & set(frappe.get_roles()))
		and frappe.session.user != "Administrator"
	):
		frappe.throw(_("This repair is assigned to another technician."))


def after_unit_update(doc):
	if frappe.flags.in_migrate or frappe.flags.in_patch:
		return
	if doc.request_row:
		frappe.db.set_value(
			"Service Request Item",
			doc.request_row,
			{"repair_status": doc.status, "repair_outcome": doc.outcome},
			update_modified=False,
		)
	before = doc.get_doc_before_save()
	if before and before.status != doc.status and doc.status == "Ready for Dispatch":
		from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

		enqueue_create_notification(
			[doc.support_user],
			{
				"type": "Alert",
				"document_type": "Issue",
				"document_name": doc.issue,
				"subject": _("Repair unit {0} is ready for dispatch").format(doc.name),
				"from_user": frappe.session.user,
			},
		)
	if doc.status not in WORKING:
		for todo in frappe.get_all(
			"ToDo",
			filters={"reference_type": "Repair Unit", "reference_name": doc.name, "status": "Open"},
			pluck="name",
		):
			task = frappe.get_doc("ToDo", todo)
			task.status = "Closed"
			task.save(ignore_permissions=True)


def sync_assignee(doc, method=None):
	if (
		doc.reference_type != "Repair Unit"
		or not doc.reference_name
		or not frappe.db.exists("Repair Unit", doc.reference_name)
	):
		return
	user = frappe.db.get_value(
		"ToDo",
		{"reference_type": "Repair Unit", "reference_name": doc.reference_name, "status": "Open"},
		"allocated_to",
		order_by="creation desc",
	)
	if user:
		frappe.db.set_value("Repair Unit", doc.reference_name, "repair_user", user, update_modified=False)


def sync_priority(doc, method=None):
	if not doc.get("custom_service_repair"):
		return
	for name in frappe.get_all("Repair Unit", filters={"issue": doc.name}, pluck="name"):
		frappe.db.set_value("Repair Unit", name, "priority", doc.priority, update_modified=False)


@frappe.whitelist()
def create_units(issue: str):
	request = issue_doc(issue)
	if not request.custom_service_repair:
		frappe.throw(_("Enable Product Repair first."))
	if not warehouse_for(request.company):
		frappe.throw(_("Configure a repair warehouse for this company in Repair Settings first."))
	result = []
	with internal_action():
		for row in request.custom_repair_items:
			if row.repair_unit:
				result.append(row.repair_unit)
				continue
			if not row.item_code:
				frappe.throw(_("Choose an item for every repair unit."))
			if row.previous_repair:
				previous = unit_doc(row.previous_repair, "read")
				if (
					previous.status not in TERMINAL
					or previous.company != request.company
					or previous.item_code != row.item_code
					or previous.customer != request.customer
					or previous.sender_contact != request.contact
				):
					frappe.throw(_("Choose a completed previous repair of the same customer's item."))
				if frappe.db.exists(
					"Repair Unit", {"previous_repair": previous.name, "status": ["not in", list(TERMINAL)]}
				):
					frappe.throw(_("Repair unit {0} already has an unfinished repair.").format(previous.name))
			unit = frappe.get_doc(
				{
					"doctype": "Repair Unit",
					"issue": request.name,
					"request_row": row.name,
					"previous_repair": row.previous_repair,
					"priority": request.priority,
					"company": request.company,
					"item_code": row.item_code,
					"product_name": row.product_name,
					"factory_serial": previous.factory_serial if row.previous_repair else None,
					"customer": request.customer,
					"sender_contact": request.contact,
					"support_user": frappe.session.user,
					"currency": frappe.get_cached_value("Company", request.company, "default_currency"),
					"fault_description": row.fault_description,
					"accessories": row.accessories,
					"photo": row.photo,
					"status": "Awaiting Receipt",
				}
			)
			# Creation is gated by write permission on the customer's request.
			unit.insert(ignore_permissions=True)
			row.repair_unit = unit.name
			row.repair_status = unit.status
			result.append(unit.name)
		request.save()
	return result


@frappe.whitelist()
def change_stage(unit: str, status: str):
	doc = unit_doc(unit)
	if status == "Delivered":
		issue_doc(doc.issue)
		if doc.status != "Dispatched":
			frappe.throw(_("Receive the unit before repair; confirm delivery only after dispatch."))
	else:
		check_work_access(doc)
		if status not in {"In Repair", "Waiting for Parts", "Waiting for Customer", "Ready for Dispatch"}:
			frappe.throw(_("Invalid repair stage."))
		if status == "Ready for Dispatch" and (
			not doc.work_done or doc.outcome not in {"Repaired", "No Fault Found", "Not Repairable"}
		):
			frappe.throw(_("Specify work done and the repair result before marking the unit ready."))
	with internal_action():
		doc.status = status
		doc.last_action = frappe.generate_hash(length=12)
		doc.save()
	return doc.name


def summary(doc):
	from erpnext.support.service_repair import aggregate_status

	if doc.doctype == "Issue":
		names = frappe.get_all("Repair Unit", filters={"issue": doc.name}, pluck="name")
	else:
		names = [doc.name]
	items = []
	users = set()
	for name in names:
		unit = frappe.get_doc("Repair Unit", name)
		unit.check_permission("read")
		items.append(
			{
				**{
					key: unit.get(key)
					for key in (
						"status",
						"warehouse",
						"factory_serial",
						"product_name",
						"item_code",
						"priority",
						"outcome",
					)
				},
				"repair_unit": name,
			}
		)
		if unit.repair_user:
			users.add(unit.repair_user)
	data = {
		"status": aggregate_status([frappe._dict(row) for row in items]),
		"items": items,
		"default_warehouse": warehouse_for(doc.company),
		"support_user": frappe._dict(user=doc.owner),
		"repair_users": [
			{"user": user, "full_name": frappe.get_cached_value("User", user, "full_name")}
			for user in sorted(users)
		],
		"movements": [],
		"legacy_stock_entries": [],
	}
	if doc.doctype == "Repair Unit":
		from erpnext.support.repair_unit_movement import parts_history

		data["consumed_parts"] = parts_history(doc)
		old_unit = (
			frappe.db.get_value("Repair Order Item", doc.legacy_order_item, "repair_unit")
			if doc.legacy_order_item
			else None
		)
		parents = frappe.get_all(
			"Repair Movement Item",
			filters={
				"repair_unit": ["in", [doc.name, old_unit or doc.name]],
				"parenttype": "Repair Movement",
			},
			pluck="parent",
		)
		data["movements"] = (
			[
				dict(row, doctype="Repair Movement")
				for row in frappe.get_list(
					"Repair Movement",
					filters={"name": ["in", parents]},
					or_filters={"issue": doc.issue, "repair_order": doc.legacy_order or ""},
					fields=["name", "docstatus", "action as custom_repair_action"],
					order_by="creation desc",
				)
			]
			if parents
			else []
		)
		if frappe.has_permission("Stock Entry", "read"):
			data["movements"] += [
				dict(row, doctype="Stock Entry", custom_repair_action="parts")
				for row in frappe.get_list(
					"Stock Entry",
					filters={"custom_repair_unit": doc.name},
					fields=["name", "docstatus"],
					order_by="creation desc",
				)
			]
		data["previous_repairs"] = []
		if doc.legacy_order and frappe.has_permission("Repair Order", "read", doc=doc.legacy_order):
			data["legacy_order"] = doc.legacy_order
		name = doc.previous_repair
		seen = {doc.name}
		while name and name not in seen:
			seen.add(name)
			previous = frappe.get_doc("Repair Unit", name)
			previous.check_permission("read")
			data["previous_repairs"].append(
				{"name": name, "issue": previous.issue, "status": previous.status}
			)
			name = previous.previous_repair
	if frappe.has_permission("Stock Entry", "read"):
		orders = list(
			{frappe.db.get_value("Repair Unit", name, "legacy_order") for name in names} - {None, ""}
		)
		if orders:
			data["legacy_stock_entries"] = frappe.get_list(
				"Stock Entry",
				filters={"custom_repair_order": ["in", orders], "docstatus": 1},
				pluck="name",
			)
	return data
