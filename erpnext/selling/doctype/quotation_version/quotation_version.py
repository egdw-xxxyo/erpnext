# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class QuotationVersion(Document):
	pass


def _last_version(quotation_name):
	rows = frappe.get_all(
		"Quotation Version",
		filters={"quotation": quotation_name},
		fields=["name"],
		order_by="version_no desc",
		limit=1,
	)
	return frappe.get_doc("Quotation Version", rows[0]["name"]) if rows else None


def _baseline_version(doc):
	"""Last version for this quotation, or — for an amended quotation with no
	versions yet — the last version of the document it was amended from, so the
	negotiation history threads across the amend chain."""
	last = _last_version(doc.name)
	if last:
		return last
	if doc.get("amended_from"):
		return _last_version(doc.amended_from)
	return None


def snapshot_quotation(doc, method=None, manual=False, change_reason=None, change_summary=None):
	"""Create a Quotation Version capturing before/after of items and totals.

	Auto-called on Quotation `on_update`; only writes a version when items actually
	changed (or when forced via `manual`)."""
	if doc.doctype != "Quotation":
		return None

	baseline = _baseline_version(doc)
	before_map = {}
	if baseline:
		for r in baseline.items:
			if r.action != "Removed":
				before_map[r.item_code] = (r.qty_after or 0, r.rate_after or 0)

	rows = []
	changed = False
	after_items = doc.get("items") or []
	after_codes = set()
	for d in after_items:
		after_codes.add(d.item_code)
		qa, ra = (d.qty or 0), (d.rate or 0)
		if d.item_code in before_map:
			qb, rb = before_map[d.item_code]
			if qa != qb or ra != rb:
				action = "Modified"
				changed = True
			else:
				action = "Unchanged"
		else:
			qb, rb = 0, 0
			action = "Added"
			changed = True
		rows.append(
			{
				"item_code": d.item_code,
				"item_name": d.get("item_name"),
				"action": action,
				"qty_before": qb,
				"qty_after": qa,
				"rate_before": rb,
				"rate_after": ra,
			}
		)

	for item, (qb, rb) in before_map.items():
		if item not in after_codes:
			rows.append(
				{
					"item_code": item,
					"action": "Removed",
					"qty_before": qb,
					"qty_after": 0,
					"rate_before": rb,
					"rate_after": 0,
				}
			)
			changed = True

	if baseline and not changed and not manual:
		return None

	version_no = (baseline.version_no + 1) if baseline else 1
	ver = frappe.new_doc("Quotation Version")
	ver.quotation = doc.name
	ver.opportunity = doc.get("opportunity")
	ver.version_no = version_no
	ver.snapshot_on = frappe.utils.now_datetime()
	ver.author = frappe.session.user
	ver.negotiation_status = doc.get("negotiation_status")
	ver.change_summary = change_summary
	ver.change_reason = change_reason
	ver.total_before = baseline.total_after if baseline else 0
	ver.total_after = doc.get("grand_total") or doc.get("total") or 0
	ver.item_count_before = len(before_map)
	ver.item_count_after = len(after_items)
	for r in rows:
		ver.append("items", r)
	ver.insert(ignore_permissions=True)
	return ver.name


@frappe.whitelist()
def create_manual_version(quotation, change_reason=None, change_summary=None):
	"""Force a negotiation-step snapshot with a reason/summary from the UI."""
	doc = frappe.get_doc("Quotation", quotation)
	name = snapshot_quotation(doc, manual=True, change_reason=change_reason, change_summary=change_summary)
	frappe.db.commit()
	return name
