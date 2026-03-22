import frappe
from frappe import _


@frappe.whitelist()
def generate_serial_numbers_for_pr(purchase_receipt_name):
	"""Generate serial numbers for PR items that have has_serial_no=1.
	Called from Draft stage to create serials before submission."""
	pr = frappe.get_doc("Purchase Receipt", purchase_receipt_name)
	if pr.docstatus != 0:
		frappe.throw(_("Serial numbers can only be generated for Draft Purchase Receipts"))

	created_bundles = []
	for item in pr.items:
		if item.serial_and_batch_bundle:
			continue

		item_details = frappe.get_cached_value(
			"Item", item.item_code,
			["has_serial_no", "serial_no_series", "serial_number_template"],
			as_dict=True
		)
		if not item_details or not item_details.has_serial_no:
			continue

		serial_no_series = item_details.serial_no_series
		if not serial_no_series:
			frappe.throw(
				_("Item {0} has no Serial No Series configured").format(item.item_code)
			)

		if item_details.serial_number_template and "{ATTR:" in (serial_no_series or ""):
			from erpnext.stock.doctype.serial_number_template.serial_number_template import (
				resolve_series_for_item,
			)
			serial_no_series = resolve_series_for_item(
				item_details.serial_number_template, item.item_code
			)

		from erpnext.stock.serial_batch_bundle import SerialBatchCreation

		qty = item.qty or item.received_qty or 0
		if qty <= 0:
			continue

		sbc = SerialBatchCreation({
			"item_code": item.item_code,
			"warehouse": item.warehouse,
			"voucher_type": "Purchase Receipt",
			"voucher_no": "",
			"posting_date": pr.posting_date,
			"posting_time": pr.posting_time,
			"company": pr.company,
			"qty": qty,
			"total_qty": qty,
			"type_of_transaction": "Inward",
			"serial_no_series": serial_no_series,
			"do_not_submit": True,
			"ignore_sabb_validation": True,
		})
		bundle = sbc.make_serial_and_batch_bundle()
		if bundle and bundle.name:
			frappe.db.set_value("Serial and Batch Bundle", bundle.name, "voucher_no", pr.name)
			item.db_set("serial_and_batch_bundle", bundle.name, update_modified=False)
			item.db_set("use_serial_batch_fields", 0, update_modified=False)
			created_bundles.append({
				"item_code": item.item_code,
				"bundle": bundle.name,
				"qty": int(qty),
			})

	if created_bundles:
		frappe.db.commit()

	return created_bundles


@frappe.whitelist()
def get_serial_numbers_for_pr(purchase_receipt_name):
	"""Get all serial numbers from PR's Serial and Batch Bundles."""
	pr = frappe.get_doc("Purchase Receipt", purchase_receipt_name)
	result = []
	for item in pr.items:
		if not item.serial_and_batch_bundle:
			continue
		entries = frappe.get_all(
			"Serial and Batch Entry",
			filters={"parent": item.serial_and_batch_bundle},
			fields=["serial_no"],
			order_by="idx asc",
		)
		for entry in entries:
			result.append({
				"item_code": item.item_code,
				"serial_no": entry.serial_no,
				"item_name": item.item_name,
			})
	return result


@frappe.whitelist()
def create_bulk_quality_inspection(purchase_receipt_name):
	"""Create a single Quality Inspection document with per-serial pass/fail entries.
	Only for items with requires_incoming_qc=1."""
	pr = frappe.get_doc("Purchase Receipt", purchase_receipt_name)
	if pr.docstatus != 0:
		frappe.throw(_("Quality Inspections can only be created for Draft Purchase Receipts"))

	created_qis = []

	for item in pr.items:
		requires_qc = frappe.get_cached_value("Item", item.item_code, "requires_incoming_qc")
		if not requires_qc:
			continue

		if not item.serial_and_batch_bundle:
			frappe.throw(
				_("Please generate serial numbers for {0} before creating Quality Inspections").format(
					item.item_code
				)
			)

		existing_qi = frappe.db.exists("Quality Inspection", {
			"reference_type": "Purchase Receipt",
			"reference_name": pr.name,
			"item_code": item.item_code,
			"docstatus": ["!=", 2],
		})
		if existing_qi:
			created_qis.append(existing_qi)
			continue

		entries = frappe.get_all(
			"Serial and Batch Entry",
			filters={"parent": item.serial_and_batch_bundle},
			fields=["serial_no"],
			order_by="idx asc",
		)

		qi = frappe.new_doc("Quality Inspection")
		qi.inspection_type = "Incoming"
		qi.reference_type = "Purchase Receipt"
		qi.reference_name = pr.name
		qi.item_code = item.item_code
		qi.item_name = item.item_name
		qi.sample_size = len(entries)
		qi.manual_inspection = 1
		qi.report_date = pr.posting_date
		qi.company = pr.company
		qi.inspected_by = frappe.session.user
		qi.verified_by = frappe.session.user

		qi_template = None
		item_spec = frappe.get_cached_value("Item", item.item_code, "item_specification")
		if item_spec:
			qi_template = frappe.get_cached_value(
				"Item Specification", item_spec, "quality_inspection_template"
			)
		if not qi_template:
			qi_template = frappe.get_cached_value("Item", item.item_code, "quality_inspection_template")
		if qi_template:
			qi.quality_inspection_template = qi_template

		for entry in entries:
			qi.append("serial_inspections", {
				"serial_no": entry.serial_no,
				"status": "Pass",
			})

		qi.insert(ignore_permissions=True)
		created_qis.append(qi.name)

		item.db_set("quality_inspection", qi.name, update_modified=False)

	if created_qis:
		frappe.db.commit()

	return created_qis


@frappe.whitelist()
def check_all_inspections_passed(purchase_receipt_name):
	"""Check if all Quality Inspections for this PR are submitted and accepted.
	Returns dict with status and details."""
	pr = frappe.get_doc("Purchase Receipt", purchase_receipt_name)

	items_needing_qc = []
	for item in pr.items:
		requires_qc = frappe.get_cached_value("Item", item.item_code, "requires_incoming_qc")
		if requires_qc:
			items_needing_qc.append(item)

	if not items_needing_qc:
		return {"passed": True, "message": _("No items require quality inspection")}

	for item in items_needing_qc:
		if not item.quality_inspection:
			return {
				"passed": False,
				"message": _("Item {0} has no Quality Inspection linked").format(item.item_code),
			}

		qi_status, qi_docstatus = frappe.db.get_value(
			"Quality Inspection", item.quality_inspection, ["status", "docstatus"]
		)

		if qi_docstatus != 1:
			return {
				"passed": False,
				"message": _("Quality Inspection {0} is not submitted").format(item.quality_inspection),
			}

		if qi_status == "Rejected":
			failed_count = frappe.db.count(
				"QI Serial Entry",
				filters={"parent": item.quality_inspection, "status": "Fail"},
			)
			total_count = frappe.db.count(
				"QI Serial Entry",
				filters={"parent": item.quality_inspection},
			)
			return {
				"passed": False,
				"message": _("Quality Inspection {0}: {1} of {2} serials failed").format(
					item.quality_inspection, failed_count, total_count
				),
			}

	return {"passed": True, "message": _("All quality inspections passed")}


@frappe.whitelist()
def update_pr_quantities_from_qi(quality_inspection_name):
	"""After QI is submitted, update PR item quantities based on pass/fail results.
	Passed serials → qty (accepted), Failed serials → rejected_qty."""
	frappe.has_permission("Quality Inspection", "write", quality_inspection_name, throw=True)
	qi = frappe.get_doc("Quality Inspection", quality_inspection_name)

	if qi.reference_type != "Purchase Receipt" or not qi.reference_name:
		return

	pass_count = 0
	fail_count = 0
	failed_serials = []

	for entry in qi.get("serial_inspections", []):
		if entry.status == "Pass":
			pass_count += 1
		else:
			fail_count += 1
			failed_serials.append(entry.serial_no)

	if not (pass_count + fail_count):
		return

	pr = frappe.get_doc("Purchase Receipt", qi.reference_name)
	for item in pr.items:
		if item.item_code == qi.item_code:
			# Only accepted serials enter the warehouse — failed ones stay with supplier
			item.db_set("received_qty", pass_count, update_modified=False)
			item.db_set("qty", pass_count, update_modified=False)
			item.db_set("rejected_qty", 0, update_modified=False)
			item.db_set("amount", pass_count * (item.rate or 0), update_modified=False)
			item.db_set("base_amount", pass_count * (item.base_rate or 0), update_modified=False)
			# Remove failed serials from the bundle
			if failed_serials and item.serial_and_batch_bundle:
				frappe.db.delete("Serial and Batch Entry", {
					"parent": item.serial_and_batch_bundle,
					"serial_no": ("in", failed_serials),
				})
			break

	qi_status = "Accepted" if fail_count == 0 else "Rejected"
	qi.db_set("status", qi_status, update_modified=False)

	frappe.db.commit()
	return {
		"pass_count": pass_count,
		"fail_count": fail_count,
		"failed_serials": failed_serials,
		"qi_status": qi_status,
	}


@frappe.whitelist()
def get_label_templates_for_items(item_codes):
	"""Return label templates configured on items. item_codes is a JSON list."""
	import json
	if isinstance(item_codes, str):
		item_codes = json.loads(item_codes)
	if not item_codes:
		return {}
	rows = frappe.get_all(
		"Item Label Template",
		filters=[["parent", "in", item_codes]],
		fields=["parent", "label_template", "label_printer"],
		ignore_permissions=True,
	)
	result = {}
	for r in rows:
		result.setdefault(r.parent, []).append({
			"label_template": r.label_template,
			"label_printer": r.label_printer,
		})
	return result


@frappe.whitelist()
def cleanup_draft_bundles(purchase_receipt_name):
	"""Delete draft Serial and Batch Bundles when PR is cancelled or deleted."""
	bundles = frappe.get_all(
		"Serial and Batch Bundle",
		filters={
			"voucher_type": "Purchase Receipt",
			"voucher_no": purchase_receipt_name,
			"docstatus": 0,
		},
		pluck="name",
	)
	for bundle_name in bundles:
		frappe.delete_doc("Serial and Batch Bundle", bundle_name, force=True)
	if bundles:
		frappe.db.commit()
	return len(bundles)
