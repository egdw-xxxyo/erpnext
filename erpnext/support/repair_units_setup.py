"""Idempotent transition from grouped repair orders to individual repair cards."""

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.support.repair_units import internal_action


def execute():
	if not frappe.db.exists("Role", "Repair Technician"):
		frappe.get_doc({"doctype": "Role", "role_name": "Repair Technician", "desk_access": 1}).insert(
			ignore_permissions=True
		)
	settings = frappe.get_single("Repair Settings")
	if settings.repair_warehouse:
		company = frappe.db.get_value("Warehouse", settings.repair_warehouse, "company")
		if company and not any(row.company == company for row in settings.warehouses):
			settings.append("warehouses", {"company": company, "warehouse": settings.repair_warehouse})
		settings.repair_warehouse = None
		settings.save(ignore_permissions=True)
	before_patch = frappe.flags.in_patch
	frappe.flags.in_patch = True
	try:
		with internal_action():
			migrate_orders()
			for unit in frappe.get_all("Repair Unit", fields=["request_row", "status", "outcome"]):
				if unit.request_row:
					frappe.db.set_value(
						"Service Request Item",
						unit.request_row,
						{"repair_status": unit.status, "repair_outcome": unit.outcome},
						update_modified=False,
					)
	finally:
		frappe.flags.in_patch = before_patch


def migrate_orders():
	last = {}
	for name in frappe.get_all("Repair Order", pluck="name", order_by="creation asc"):
		order = frappe.get_doc("Repair Order", name)
		request = frappe.get_doc("Issue", order.issue)
		for row in order.items:
			existing = frappe.db.get_value("Repair Unit", {"legacy_order_item": row.name}, "name")
			if existing:
				last[row.repair_unit] = existing
				continue
			original = frappe.get_doc("Repair Unit", row.repair_unit)
			source = next(
				(source for source in request.custom_repair_items if source.repair_unit == row.repair_unit),
				None,
			)
			if not source:
				# Early grouped orders did not copy the new unit link back to Issue.
				# Prefer the original row index when an item occurs more than once.
				candidates = [
					source
					for source in request.custom_repair_items
					if not source.repair_unit
					and source.item_code == original.item_code
					and not frappe.db.exists("Repair Unit", {"request_row": source.name})
				]
				source = next((source for source in candidates if source.idx == row.idx), None)
				if not source and len(candidates) == 1:
					source = candidates[0]
				if not source:
					frappe.throw(
						_(
							"Cannot match repair {0} to its source request row. Check the original request."
						).format(row.repair_unit)
					)
			unit = original if not original.issue else frappe.new_doc("Repair Unit")
			unit.update(
				{
					"issue": request.name,
					"request_row": source.name,
					"previous_repair": last.get(original.name),
					"legacy_order": order.name,
					"legacy_order_item": row.name,
					"company": order.company,
					"currency": order.currency,
					"item_code": original.item_code,
					"product_name": row.product_name,
					"factory_serial": original.factory_serial,
					"customer": request.customer,
					"sender_contact": request.contact,
					"priority": request.priority,
					"support_user": order.support_user,
					"repair_user": order.repair_user,
					"warehouse": row.warehouse,
					"status": row.status,
					"fault_description": row.fault_description,
					"accessories": row.accessories,
					"photo": row.photo,
					"diagnosis": row.diagnosis,
					"work_done": row.work_done,
					"outcome": row.outcome,
					"received_on": order.creation if row.status != "Awaiting Receipt" else None,
					"labor_cost": flt(row.labor_cost),
					"parts_cost": flt(row.parts_cost),
					"total_cost": flt(row.labor_cost) + flt(row.parts_cost),
					"last_action": row.last_action,
				}
			)
			if row.work_done or row.diagnosis or row.labor_cost:
				unit.append(
					"work_log",
					{
						"notes": row.work_done or row.diagnosis or _("Previous repair work"),
						"performed_on": order.modified,
						"performed_by": order.modified_by,
						"labor_cost": row.labor_cost,
						"cost_note": row.cost_note,
					},
				)
			unit.save(ignore_permissions=True)
			last[original.name] = unit.name
			frappe.db.set_value(
				"Service Request Item",
				source.name,
				{"repair_unit": unit.name, "repair_status": unit.status},
				update_modified=False,
			)
