# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import get_link_to_form

from erpnext.manufacturing.doctype.workstation.workstation import get_time_logs


class Workplace(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		allowed_employees: DF.Table["WorkplaceEmployee"]
		allowed_operations: DF.Table["WorkplaceOperation"]
		company: DF.Link | None
		description: DF.SmallText | None
		is_active: DF.Check
		workplace_name: DF.Data | None

	@frappe.whitelist()
	def get_job_cards(self):
		operations = [row.operation for row in self.allowed_operations]
		if not operations:
			return []

		workstations = [row.workstation for row in self.allowed_operations if row.workstation]

		filters = {
			"operation": ["in", operations],
			"docstatus": ("<", 2),
			"status": ["not in", ["Completed", "Stopped"]],
		}

		if workstations:
			filters["workstation"] = ["in", workstations]

		jc_data = frappe.get_all(
			"Job Card",
			fields=[
				"name",
				"production_item",
				"work_order",
				"operation",
				"total_completed_qty",
				"for_quantity",
				"process_loss_qty",
				"transferred_qty",
				"status",
				"expected_start_date",
				"expected_end_date",
				"time_required",
				"wip_warehouse",
				"workstation",
			],
			filters=filters,
			order_by="expected_start_date, expected_end_date",
			limit=50,
		)

		job_cards = [row.name for row in jc_data]
		time_logs = get_time_logs(job_cards) if job_cards else {}

		user_employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")

		for row in jc_data:
			if row.status == "Open":
				row.status = "Not Started"

			item_code = row.production_item
			row.fg_uom = frappe.get_cached_value("Item", item_code, "stock_uom")

			row.status_colour = _get_status_color(row.status)
			row.job_card_link = (
				f'<a class="ellipsis" data-doctype="Job Card" data-name="{row.name}" '
				f'href="/app/job-card/{row.name}" title="{row.name}">{row.name}</a>'
			)
			row.operation_link = (
				f'<a class="ellipsis" data-doctype="Operation" data-name="{row.operation}" '
				f'href="/app/operation/{row.operation}" title="{row.operation}">{row.operation}</a>'
			)
			row.work_order_link = get_link_to_form("Work Order", row.work_order)
			row.time_logs = time_logs.get(row.name, [])

			row.user_employee = user_employee

		return jc_data

	@frappe.whitelist()
	def find_job_card_by_barcode(self, barcode):
		operations = [row.operation for row in self.allowed_operations]
		if not operations:
			return []

		if frappe.db.exists("Job Card", barcode):
			jc = frappe.db.get_value(
				"Job Card",
				barcode,
				["name", "operation", "status", "production_item", "for_quantity"],
				as_dict=True,
			)
			if jc and jc.operation in operations and jc.status not in ("Completed", "Stopped"):
				return [jc]

		item_code = _resolve_barcode_to_item(barcode)
		if item_code:
			return frappe.get_all(
				"Job Card",
				fields=["name", "operation", "status", "production_item", "for_quantity", "workstation"],
				filters={
					"production_item": item_code,
					"operation": ["in", operations],
					"docstatus": ("<", 2),
					"status": ["not in", ["Completed", "Stopped"]],
				},
				order_by="expected_start_date",
				limit=10,
			)

		return []

	@frappe.whitelist()
	def get_current_employee(self):
		user = frappe.session.user
		for row in self.allowed_employees:
			if row.user == user:
				return row.employee

		return frappe.db.get_value("Employee", {"user_id": user}, "name")


def _get_status_color(status):
	color_map = {
		"Pending": "blue",
		"In Process": "yellow",
		"Submitted": "blue",
		"Open": "gray",
		"Not Started": "gray",
		"Closed": "green",
		"Work In Progress": "orange",
	}
	return color_map.get(status, "blue")


def _resolve_barcode_to_item(barcode):
	item_barcode = frappe.db.get_value("Item Barcode", {"barcode": barcode}, "parent")
	if item_barcode:
		return item_barcode

	serial_no = frappe.db.get_value("Serial No", barcode, "item_code")
	if serial_no:
		return serial_no

	if frappe.db.exists("Item", barcode):
		return barcode

	return None
