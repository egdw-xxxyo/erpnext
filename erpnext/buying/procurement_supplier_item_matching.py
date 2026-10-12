"""Learn supplier aliases only from explicitly confirmed, accessible invoice rows."""

from difflib import SequenceMatcher
from math import isfinite

import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext.buying.doctype.supplier_item_alias.supplier_item_alias import alias_key, normalize_alias
from erpnext.buying.procurement_invoice_items import read_invoice_items

ALIAS = "Supplier Item Alias"
CPO = "Consolidated Purchase Order"


def _check_order(source_name, supplier, file_url, for_update=False):
	doc = frappe.get_doc(CPO, source_name, for_update=for_update)
	doc.check_permission("read")
	user = frappe.session.user
	if user != "Administrator" and not (
		"Закупівельник" in frappe.get_roles() and user in (doc.owner, doc.initiator_user)
	):
		frappe.throw(
			_("Only the buyer responsible for this order can confirm supplier item names."),
			frappe.PermissionError,
		)
	if doc.docstatus == 2:
		frappe.throw(_("Cannot match items from a cancelled order."))
	if not any(row.supplier == supplier and row.invoice_pdf == file_url for row in doc.supplier_invoices):
		frappe.throw(_("Select a saved supplier invoice from this order."), frappe.PermissionError)
	if not file_url.lower().split("?", 1)[0].endswith(".pdf"):
		frappe.throw(_("Select a PDF invoice."))
	supplier_doc = frappe.get_doc("Supplier", supplier)
	supplier_doc.check_permission("read")
	return doc


def _known_items(supplier):
	aliases = frappe.get_all(
		ALIAS, filters={"supplier": supplier}, fields=["item_code", "supplier_item_name", "supplier_part_no"]
	)
	aliases.extend(
		frappe.get_all(
			"Item Supplier",
			filters={"supplier": supplier, "parenttype": "Item"},
			fields=[
				"parent as item_code",
				"custom_supplier_item_name as supplier_item_name",
				"supplier_part_no",
			],
		)
	)
	return aliases


def _check_prefill_order(doc):
	doc.check_permission("write")
	if doc.docstatus != 0 or doc.workflow_state in {
		"Перевірка підрозділу",
		"Фінальне погодження",
		"Погоджено",
	}:
		frappe.throw(_("PDF prefill is only available in an editable draft."))


def _prefill_context(supplier, file_url, draft_doc):
	values = frappe.parse_json(draft_doc)
	if not isinstance(values, dict) or values.get("doctype") != CPO:
		frappe.throw(_("PDF prefill is only available in an editable draft."))
	doc = frappe.get_doc(values)
	user = frappe.session.user
	if doc.is_new():
		doc.check_permission("create")
		if user != "Administrator" and "Закупівельник" not in frappe.get_roles():
			frappe.throw(_("Not permitted"), frappe.PermissionError)
	else:
		stored = frappe.get_doc(CPO, doc.name)
		stored.check_permission("read")
		_check_prefill_order(stored)
		if user != "Administrator" and not (
			"Закупівельник" in frappe.get_roles() and user in (stored.owner, stored.initiator_user)
		):
			frappe.throw(_("Not permitted"), frappe.PermissionError)
	if doc.docstatus != 0 or doc.workflow_state in {
		"Перевірка підрозділу",
		"Фінальне погодження",
		"Погоджено",
	}:
		frappe.throw(_("PDF prefill is only available in an editable draft."))
	if not any(row.supplier == supplier and row.invoice_pdf == file_url for row in doc.supplier_invoices):
		frappe.throw(_("Select a supplier invoice from this draft."), frappe.PermissionError)
	file = frappe.get_doc("File", {"file_url": file_url})
	file.check_permission("read")
	if file.attached_to_doctype:
		if file.attached_to_doctype != CPO or file.attached_to_name != doc.name:
			frappe.throw(_("Upload a file for this order."), frappe.PermissionError)
	elif file.owner != user and user != "Administrator":
		frappe.throw(_("Upload a file for this order."), frappe.PermissionError)
	if not file_url.lower().split("?", 1)[0].endswith(".pdf"):
		frappe.throw(_("Select a PDF invoice."))
	frappe.get_doc("Supplier", supplier).check_permission("read")
	return doc


@frappe.whitelist()
def get_prefill_preview(supplier: str, file_url: str, draft_doc: str | dict):
	_prefill_context(supplier, file_url, draft_doc)
	result = read_invoice_items(file_url)
	aliases = _known_items(supplier)
	candidates = {row.item_code for row in aliases}
	allowed = (
		set(
			frappe.get_list(
				"Item",
				filters={
					"name": ["in", list(candidates)],
					"disabled": 0,
					"has_variants": 0,
					"is_purchase_item": 1,
				},
				pluck="name",
				limit_page_length=0,
			)
		)
		if candidates
		else set()
	)
	for row in result["rows"]:
		known = _saved_item_codes(row, aliases)
		row["suggested_item_code"] = next(iter(known)) if len(known) == 1 and known <= allowed else None
	return result


def _saved_item_codes(invoice_row, aliases):
	"""Exact supplier aliases only; conflicting name/article matches need manual choice."""
	name = normalize_alias(invoice_row.get("supplier_item_name"))
	part = normalize_alias(invoice_row.get("supplier_part_no"))
	return {
		row.item_code
		for row in aliases
		if (name and normalize_alias(row.supplier_item_name) == name)
		or (part and normalize_alias(row.supplier_part_no) == part)
	}


@frappe.whitelist()
def prepare_prefill_items(
	supplier: str,
	file_url: str,
	draft_doc: str | dict,
	mappings: str | list[dict],
	import_values: bool | int | str = False,
):
	"""Return unsaved rows; PDF quantities/prices require explicit opt-in."""
	doc = _prefill_context(supplier, file_url, draft_doc)
	mappings = frappe.parse_json(mappings)
	if (
		not isinstance(mappings, list)
		or not mappings
		or len(mappings) > 200
		or any(not isinstance(mapping, dict) for mapping in mappings)
	):
		frappe.throw(_("Select invoice rows and their matching order items."))
	invoice_rows = {row["id"]: row for row in read_invoice_items(file_url)["rows"]}
	seen = set()
	rows = []
	missing_values = False
	from erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order import (
		get_allowed_related_supplier_names,
	)

	allowed = get_allowed_related_supplier_names(supplier)
	existing_related = next(
		(
			row.related_supplier
			for row in doc.items
			if row.supplier == supplier and row.related_supplier in allowed
		),
		None,
	)
	related_supplier = existing_related or (allowed[0] if len(allowed) == 1 else None)
	for mapping in mappings:
		invoice_id = mapping.get("invoice_row")
		if invoice_id not in invoice_rows or invoice_id in seen or not mapping.get("item_code"):
			frappe.throw(_("The invoice or order items changed. Open the matching window again."))
		seen.add(invoice_id)
		item = frappe.get_doc("Item", mapping["item_code"])
		item.check_permission("read")
		if item.disabled or item.has_variants or not item.is_purchase_item:
			frappe.throw(_("Select an enabled purchase Item without variants."))
		rows.append(
			{
				"supplier": supplier,
				"related_supplier": related_supplier,
				"item_code": item.name,
				"item_name": item.item_name,
				"description": item.description,
				"uom": item.stock_uom,
				"schedule_date": doc.set_schedule_date,
				"warehouse": doc.set_warehouse,
			}
		)
		if cint(import_values):
			invoice = invoice_rows[invoice_id]
			for fieldname in ("qty", "rate"):
				value = invoice.get(fieldname)
				if (
					value is not None
					and isfinite(value)
					and (value > 0 if fieldname == "qty" else value >= 0)
				):
					rows[-1][fieldname] = value
				else:
					missing_values = True
	return {"items": rows, "missing_values": missing_values}


def suggest_rows(invoice_row, order_rows, aliases):
	name = normalize_alias(invoice_row["supplier_item_name"])
	part = normalize_alias(invoice_row.get("supplier_part_no"))
	by_part = {row.item_code for row in aliases if part and normalize_alias(row.supplier_part_no) == part}
	by_name = {row.item_code for row in aliases if normalize_alias(row.supplier_item_name) == name}
	known = by_part or by_name
	candidates = []
	for row in order_rows:
		reasons = []
		score = 0
		if row.item_code in known:
			score += 100
			reasons.append("Saved supplier match")
		similarity = SequenceMatcher(None, name, normalize_alias(row.item_name)).ratio()
		if similarity >= 0.6:
			score += round(similarity * 30)
			reasons.append("Similar name")
		if abs(flt(row.qty) - invoice_row["qty"]) < 0.000001:
			score += 10
			reasons.append("Same quantity")
		if invoice_row.get("rate") is not None and abs(flt(row.rate) - invoice_row["rate"]) < 0.005:
			score += 10
			reasons.append("Same price")
		if invoice_row.get("uom") and normalize_alias(row.uom) == normalize_alias(invoice_row["uom"]):
			score += 5
			reasons.append("Same unit")
		candidates.append({"order_row": row.name, "score": score, "reasons": reasons})
	candidates.sort(key=lambda row: row["score"], reverse=True)
	# A quantity/price coincidence alone must never preselect an Item.
	selected = None
	if candidates and len(known) <= 1 and candidates[0]["score"] >= 30:
		if len(candidates) == 1 or candidates[0]["score"] > candidates[1]["score"]:
			selected = candidates[0]["order_row"]
	return {"candidates": candidates, "suggested_order_row": selected}


@frappe.whitelist()
def get_matching_preview(source_name: str, supplier: str, file_url: str):
	doc = _check_order(source_name, supplier, file_url)
	order_rows = [row for row in doc.items if row.supplier == supplier]
	for item_code in {row.item_code for row in order_rows}:
		frappe.get_doc("Item", item_code).check_permission("read")
	result = read_invoice_items(file_url)
	aliases = _known_items(supplier)
	for row in result["rows"]:
		row.update(suggest_rows(row, order_rows, aliases))
	result["order_rows"] = [
		{key: row.get(key) for key in ("name", "idx", "item_code", "item_name", "qty", "rate", "uom")}
		for row in order_rows
	]
	result["file_url"] = file_url
	return result


@frappe.whitelist(methods=["POST"])
def confirm_matches(source_name: str, supplier: str, file_url: str, mappings: str | list[dict]):
	doc = _check_order(source_name, supplier, file_url, for_update=True)
	mappings = frappe.parse_json(mappings)
	if (
		not isinstance(mappings, list)
		or not mappings
		or len(mappings) > 200
		or any(not isinstance(mapping, dict) for mapping in mappings)
	):
		frappe.throw(_("Select invoice rows and their matching order items."))
	# Re-read the saved PDF: client text, prices and Item codes are never trusted.
	invoice_rows = {row["id"]: row for row in read_invoice_items(file_url)["rows"]}
	order_rows = {row.name: row for row in doc.items if row.supplier == supplier}
	seen = set()
	confirmed = []
	for mapping in mappings:
		invoice_id = mapping.get("invoice_row")
		order_id = mapping.get("order_row")
		if invoice_id in seen or invoice_id not in invoice_rows or order_id not in order_rows:
			frappe.throw(_("The invoice or order items changed. Open the matching window again."))
		seen.add(invoice_id)
		invoice_row = invoice_rows[invoice_id]
		if len(invoice_row["supplier_item_name"]) > 140 or len(invoice_row["supplier_part_no"]) > 140:
			frappe.throw(
				_("The supplier item name or part number is too long to save. Check the PDF layout.")
			)
		confirmed.append((invoice_row, order_rows[order_id].item_code))
	# Serialize confirmations for a supplier, including different target Items.
	frappe.get_doc("Supplier", supplier, for_update=True).check_permission("read")
	items = {}
	for code in sorted({code for _invoice_row, code in confirmed}):
		item = frappe.get_doc("Item", code, for_update=True)
		item.check_permission("read")
		if item.disabled:
			frappe.throw(_("Cannot save a supplier match for a disabled Item."))
		items[code] = item
	saved = 0
	changed_items = set()
	for invoice_row, code in confirmed:
		key = alias_key(supplier, invoice_row["supplier_item_name"], invoice_row["supplier_part_no"])
		existing = frappe.db.get_value(ALIAS, key, "item_code")
		if existing and existing != code:
			frappe.throw(_("This supplier name and part number are already linked to another Item."))
		if existing:
			continue
		if invoice_row["supplier_part_no"]:
			part_matches = {
				row.item_code
				for row in _known_items(supplier)
				if normalize_alias(row.supplier_part_no) == normalize_alias(invoice_row["supplier_part_no"])
			}
			if part_matches - {code}:
				frappe.throw(_("This supplier part number is already linked to another Item."))
		# Narrow, permission-checked endpoint; buyers do not receive general Item write access.
		frappe.get_doc(
			{
				"doctype": ALIAS,
				"supplier": supplier,
				"item_code": code,
				"supplier_item_name": invoice_row["supplier_item_name"],
				"supplier_part_no": invoice_row["supplier_part_no"],
				"source_order": doc.name,
				"source_file": file_url,
				"confirmed_by": frappe.session.user,
			}
		).insert(ignore_permissions=True)
		item = items[code]
		canonical = next((row for row in item.supplier_items if row.supplier == supplier), None)
		if not canonical:
			canonical = item.append("supplier_items", {"supplier": supplier})
			changed_items.add(code)
		if _fill_canonical(canonical, invoice_row):
			changed_items.add(code)
		saved += 1
	for code in sorted(changed_items):
		items[code].save(ignore_permissions=True)
	return {"saved": saved, "already_saved": len(confirmed) - saved}


def _fill_canonical(canonical, invoice_row):
	# Keep name/article pairs together; a new alias must not alter an older pair.
	for field, source in (
		("custom_supplier_item_name", "supplier_item_name"),
		("supplier_part_no", "supplier_part_no"),
	):
		if canonical.get(field) and invoice_row[source]:
			if normalize_alias(canonical.get(field)) != normalize_alias(invoice_row[source]):
				return False
	changed = False
	for field, source in (
		("custom_supplier_item_name", "supplier_item_name"),
		("supplier_part_no", "supplier_part_no"),
	):
		if not canonical.get(field) and invoice_row[source]:
			setattr(canonical, field, invoice_row[source])
			changed = True
	return changed
