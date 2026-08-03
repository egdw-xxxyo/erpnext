# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import date_diff, flt


def execute(filters=None):
	filters = filters or {}
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{
			"label": _("Opportunity"),
			"fieldname": "opportunity",
			"fieldtype": "Link",
			"options": "Opportunity",
			"width": 150,
		},
		{
			"label": _("Quotation"),
			"fieldname": "quotation",
			"fieldtype": "Link",
			"options": "Quotation",
			"width": 160,
		},
		{"label": _("Versions"), "fieldname": "versions", "fieldtype": "Int", "width": 90},
		{"label": _("First Total"), "fieldname": "first_total", "fieldtype": "Currency", "width": 120},
		{"label": _("Final Total"), "fieldname": "final_total", "fieldtype": "Currency", "width": 120},
		{"label": _("Total Change"), "fieldname": "total_change", "fieldtype": "Currency", "width": 120},
		{"label": _("Items Removed"), "fieldname": "items_removed", "fieldtype": "Int", "width": 110},
		{"label": _("Final Status"), "fieldname": "final_status", "fieldtype": "Data", "width": 160},
		{"label": _("Approval Days"), "fieldname": "approval_days", "fieldtype": "Int", "width": 110},
		{"label": _("Final Version"), "fieldname": "final_version", "fieldtype": "Int", "width": 110},
	]


def get_data(filters):
	version_filters = {}
	if filters.get("opportunity"):
		version_filters["opportunity"] = filters["opportunity"]
	if filters.get("quotation"):
		version_filters["quotation"] = filters["quotation"]

	versions = frappe.get_all(
		"Quotation Version",
		filters=version_filters,
		fields=[
			"name",
			"quotation",
			"opportunity",
			"version_no",
			"snapshot_on",
			"total_after",
			"negotiation_status",
		],
		order_by="quotation asc, version_no asc",
	)

	# Count Removed rows per version in one query.
	removed_by_version = {}
	if versions:
		for row in frappe.get_all(
			"Quotation Version Item",
			filters={"parent": ["in", [v["name"] for v in versions]], "action": "Removed"},
			fields=["parent", "count(name) as cnt"],
			group_by="parent",
		):
			removed_by_version[row["parent"]] = row["cnt"]

	grouped = {}
	for v in versions:
		grouped.setdefault(v["quotation"], []).append(v)

	data = []
	for quotation, rows in grouped.items():
		first, last = rows[0], rows[-1]
		first_total = flt(first["total_after"])
		final_total = flt(last["total_after"])
		items_removed = sum(removed_by_version.get(r["name"], 0) for r in rows)
		approval_days = 0
		if first["snapshot_on"] and last["snapshot_on"]:
			approval_days = date_diff(last["snapshot_on"], first["snapshot_on"])

		data.append(
			{
				"opportunity": last["opportunity"],
				"quotation": quotation,
				"versions": len(rows),
				"first_total": first_total,
				"final_total": final_total,
				"total_change": final_total - first_total,
				"items_removed": items_removed,
				"final_status": last["negotiation_status"],
				"approval_days": approval_days,
				"final_version": last["version_no"],
			}
		)

	data.sort(key=lambda d: d["quotation"])
	return data
