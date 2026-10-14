"""Move the spools of a line that are not packed yet to the staging warehouse.

A line that changes route (units land in staging after quality control and are packed later by
a `Packing Job`) still has spools made the old way: some finished at the bench with the packing
card open and no stock entry yet, some already in finished goods but in no box. Both kinds
belong in staging, where packing picks them up like any other.

`migrate_unpacked_to_staging` lists first (`dry_run`) and moves a batch per call, so a request
never has to carry the whole backlog. A moved unit is in staging and drops out of the search, so
a repeated call is harmless.
"""

import frappe
from frappe import _
from frappe.utils import cint

from erpnext.manufacturing.doctype.production_line.production_line import (
	LIVE_WORK_ORDER_STATUSES,
	PACKING_OPERATION,
	_rejected_inspection,
	finish_packed_unit,
)
from erpnext.manufacturing.packing import ATTRIBUTE, landing_warehouse

TRANSFER_CHUNK = 50


def _line_items(line):
	items = {row.item_code for row in line.get("plan") or [] if row.item_code}
	items |= {row.item_code for row in line.get("orders") or [] if row.item_code}
	return sorted(items)


def _deferred_units(line, item_code):
	"""Units finished at the bench whose Manufacture was left for packing: closed bench card, no entry."""
	work_orders = frappe.get_all(
		"Work Order",
		filters={
			"production_line": line,
			"production_item": item_code,
			"docstatus": 1,
			"status": ["in", LIVE_WORK_ORDER_STATUSES],
		},
		pluck="name",
	)
	if not work_orders:
		return []
	return frappe.db.sql_list(
		"""
		SELECT DISTINCT bc.serial_no
		  FROM `tabJob Card` bc
		  JOIN `tabSerial No` sn ON sn.name = bc.serial_no
		 WHERE bc.work_order IN %(work_orders)s
		   AND bc.docstatus = 1
		   AND bc.operation != %(packing)s
		   AND IFNULL(sn.warehouse, '') = ''
		   AND NOT EXISTS (
			SELECT 1 FROM `tabJob Card` x
			  JOIN `tabStock Entry` se ON se.name = x.auto_stock_entry AND se.docstatus = 1
			 WHERE x.serial_no = bc.serial_no
		   )
		 ORDER BY bc.serial_no
		""",
		{"work_orders": tuple(work_orders), "packing": PACKING_OPERATION},
	)


def _unpacked_in_stock(item_code, skip_warehouses):
	"""Units in stock that are in no live box and carry no «Упаковка» note."""
	return frappe.db.sql(
		"""
		SELECT sn.name AS serial_no, sn.warehouse
		  FROM `tabSerial No` sn
		 WHERE sn.item_code = %(item)s
		   AND sn.status = 'Active'
		   AND IFNULL(sn.warehouse, '') != ''
		   AND sn.warehouse NOT IN %(skip)s
		   AND NOT EXISTS (
			SELECT 1 FROM `tabPackage Item` pi
			  JOIN `tabPackage` p ON p.name = pi.parent
			 WHERE pi.serial_no = sn.name
			   AND p.docstatus < 2
			   AND p.status NOT IN ('Cancelled', 'Unpacked')
		   )
		   AND NOT EXISTS (
			SELECT 1 FROM `tabAdditional Attribute Row` r
			 WHERE r.parenttype = 'Serial No' AND r.parent = sn.name AND r.attribute = %(attribute)s
		   )
		 ORDER BY sn.warehouse, sn.name
		""",
		{"item": item_code, "skip": tuple(skip_warehouses), "attribute": ATTRIBUTE},
		as_dict=True,
	)


def _transfer_to_staging(item_code, source, serials, target):
	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = "Material Transfer"
	entry.purpose = "Material Transfer"
	entry.company = frappe.get_cached_value("Warehouse", target, "company")
	entry.remarks = "Міграція: неупаковані котушки на склад комплектування"
	entry.append(
		"items",
		{
			"item_code": item_code,
			"qty": len(serials),
			"s_warehouse": source,
			"t_warehouse": target,
			"use_serial_batch_fields": 1,
			"serial_no": "\n".join(serials),
		},
	)
	entry.flags.ignore_permissions = True
	entry.insert()
	entry.submit()
	return entry.name


@frappe.whitelist(methods=["POST"])
def migrate_unpacked_to_staging(line, dry_run=1, limit=100):
	"""List, or move, the line's unpacked spools to the staging warehouse of their item's BOM.

	`limit` units per call, deferred ones first (they have no stock at all yet). `dry_run` only counts.
	"""
	frappe.only_for(("System Manager", "Manufacturing Manager"))
	doc = frappe.get_doc("Production Line", line)
	limit = cint(limit) or 100
	report = {"dry_run": bool(cint(dry_run)), "items": {}, "moved": 0, "remaining": 0, "errors": []}

	for item_code in _line_items(doc):
		default_bom = frappe.db.get_value("Item", item_code, "default_bom")
		staging = landing_warehouse(default_bom)
		if not staging:
			report["items"][item_code] = {"skipped": _("The default BOM names no staging warehouse")}
			continue

		deferred = [sn for sn in _deferred_units(line, item_code) if not _rejected_inspection(sn)]
		skip = {staging} | ({doc.reject_warehouse} if doc.reject_warehouse else set())
		in_stock = _unpacked_in_stock(item_code, skip)
		report["items"][item_code] = {
			"staging": staging,
			"deferred": len(deferred),
			"in_stock": len(in_stock),
			"in_stock_by_warehouse": _count_by(in_stock),
		}
		if report["dry_run"]:
			report["remaining"] += len(deferred) + len(in_stock)
			continue

		moved_before = report["moved"]
		budget = limit - report["moved"]
		for serial in deferred[: max(budget, 0)]:
			result = finish_packed_unit(serial, target_warehouse=staging)
			if result.get("error"):
				report["errors"].append(f"{serial}: {result['error']}")
			else:
				report["moved"] += 1
		budget = limit - report["moved"]

		by_source = {}
		for row in in_stock:
			by_source.setdefault(row.warehouse, []).append(row.serial_no)
		for source, serials in by_source.items():
			while serials and budget > 0:
				chunk, serials = (
					serials[: min(TRANSFER_CHUNK, budget)],
					serials[min(TRANSFER_CHUNK, budget) :],
				)
				try:
					_transfer_to_staging(item_code, source, chunk, staging)
					frappe.db.commit()
					report["moved"] += len(chunk)
					budget -= len(chunk)
				except Exception as e:
					frappe.db.rollback()
					report["errors"].append(f"{source}: {str(e)[:200]}")
					frappe.log_error(
						title=f"Staging migration: transfer from {source} failed",
						message=frappe.get_traceback(),
					)
					serials = []

		left = len(deferred) + len(in_stock) - (report["moved"] - moved_before)
		report["remaining"] += max(left, 0)

	return report


def _count_by(rows):
	counts = {}
	for row in rows:
		counts[row.warehouse] = counts.get(row.warehouse, 0) + 1
	return counts
