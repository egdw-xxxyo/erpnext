"""Read-only VAT breakdowns; accounting values are never changed."""

import re

import frappe
from frappe import _
from frappe.utils import flt


def split_amount(gross, ratio):
	vat = flt(flt(gross) * ratio, 2)
	return {"gross": flt(gross, 2), "vat": vat, "net": flt(flt(gross) - vat, 2)}


def invoice_breakdown(doc, payer):
	vat_rows = [
		row
		for row in doc.get("taxes") or []
		if row.get("category") != "Valuation"
		and (flt(row.get("rate")) == 20 or re.search(r"vat|пдв|ндс", row.get("account_head") or "", re.I))
	]
	if doc.get("taxes"):
		vat = flt(
			sum(
				flt(
					row.get("tax_amount_after_discount_amount")
					if row.get("tax_amount_after_discount_amount") is not None
					else row.get("tax_amount")
				)
				* (-1 if row.get("add_deduct_tax") == "Deduct" else 1)
				for row in vat_rows
			),
			2,
		)
		gross = flt(doc.get("grand_total"))
		ratio = vat / gross if gross else 0
		return {"gross": flt(gross, 2), "vat": vat, "net": flt(gross - vat, 2)}, ratio, vat_rows
	else:
		ratio = 1 / 6 if payer else 0
	return split_amount(doc.get("grand_total"), ratio), ratio, vat_rows


def _item_values(doc, payer, vat_rows):
	rows = {}
	items = doc.get("items") or []
	for item in items:
		qty = flt(item.get("qty"))
		if not doc.get("taxes"):
			gross = flt(item.get("rate"))
			net = gross / 1.2 if payer else gross
		else:
			net = flt(item.get("net_rate"))
			vat = 0
			for tax in vat_rows:
				details = frappe.parse_json(tax.get("item_wise_tax_detail") or "{}")
				entry = details.get(item.get("item_code"))
				if entry:
					raw_tax = sum(flt(value[1]) for value in details.values())
					actual_tax = flt(
						tax.get("tax_amount_after_discount_amount")
						if tax.get("tax_amount_after_discount_amount") is not None
						else tax.get("tax_amount")
					)
					scale = actual_tax / raw_tax if raw_tax else 0
					weight = sum(
						flt(other.get("net_amount"))
						for other in items
						if other.get("item_code") == item.get("item_code")
					)
					portion = flt(item.get("net_amount")) / weight if weight else 0
					vat += (
						flt(entry[1]) * portion * scale * (-1 if tax.get("add_deduct_tax") == "Deduct" else 1)
					)
				else:
					weight = sum(flt(other.get("net_amount")) for other in items)
					actual_tax = flt(
						tax.get("tax_amount_after_discount_amount")
						if tax.get("tax_amount_after_discount_amount") is not None
						else tax.get("tax_amount")
					)
					vat += (actual_tax * flt(item.get("net_amount")) / weight if weight else 0) * (
						-1 if tax.get("add_deduct_tax") == "Deduct" else 1
					)
			gross = net + (vat / qty if qty else 0)
		rows[item.name] = {
			"net_rate": flt(net, 2),
			"gross_rate": flt(gross, 2),
			"gross_amount": flt(gross * qty, 2),
		}
	return rows


def payment_breakdown(doc, payer, reference_ratio):
	"""Split the supplier-side amount, including advances and refunds."""
	default_ratio = 1 / 6 if payer else 0
	rows = {}
	vat = allocated = 0
	direction = (
		-1
		if doc.payment_type == "Receive"
		and sum(flt(row.allocated_amount) for row in doc.get("references") or []) < 0
		else 1
	)
	for row in doc.get("references") or []:
		amount = flt(row.allocated_amount) * direction
		entry = split_amount(amount, reference_ratio(row.reference_doctype, row.reference_name))
		rows[row.name] = entry
		vat += entry["vat"]
		allocated += amount
	gross = flt(doc.received_amount if doc.payment_type == "Pay" else doc.paid_amount)
	vat += (gross - allocated) * default_ratio
	return split_amount(gross, vat / gross if gross else 0), rows


@frappe.whitelist()
def get_invoice_list_vat(names: str | list):
	names = frappe.parse_json(names)
	if not isinstance(names, list) or len(names) > 500 or not all(isinstance(name, str) for name in names):
		frappe.throw(_("Invalid invoice selection."))
	result = {}
	for row in frappe.get_list(
		"Purchase Invoice", filters={"name": ["in", names]}, fields=["name"], limit_page_length=0
	):
		invoice = frappe.get_doc("Purchase Invoice", row.name)
		payer = bool(frappe.get_cached_value("Supplier", invoice.supplier, "custom_is_vat_payer"))
		result[row.name] = {"payer": payer, "totals": invoice_breakdown(invoice, payer)[0]}
	return result


@frappe.whitelist()
def get_supplier_paid_vat(supplier: str):
	party = frappe.get_doc("Supplier", supplier)
	party.check_permission("read")
	payer = bool(party.get("custom_is_vat_payer"))
	if not frappe.has_permission("Payment Entry", "read"):
		return {"visible": False}
	payments = frappe.get_list(
		"Payment Entry",
		filters={
			"party_type": "Supplier",
			"party": supplier,
			"docstatus": 1,
			"payment_type": ["in", ["Pay", "Receive"]],
		},
		fields=["name"],
		limit_page_length=0,
	)
	groups = {}
	for row in payments:
		payment = frappe.get_doc("Payment Entry", row.name)

		def reference_ratio(doctype, name):
			if doctype not in {"Purchase Invoice", "Purchase Order"} or not name:
				return 1 / 6 if payer else 0
			source = frappe.get_cached_doc(doctype, name)
			source.check_permission("read")
			if source.supplier != supplier or source.company != payment.company:
				return 0
			return invoice_breakdown(source, payer)[1]

		totals, _rows = payment_breakdown(payment, payer, reference_ratio)
		currency = frappe.get_cached_value("Company", payment.company, "default_currency")
		group = groups.setdefault(
			payment.company, {"company": payment.company, "currency": currency, "vat": 0}
		)
		exchange_rate = (
			payment.target_exchange_rate if payment.payment_type == "Pay" else payment.source_exchange_rate
		)
		group["vat"] += totals["vat"] * flt(exchange_rate) * (1 if payment.payment_type == "Pay" else -1)
	for group in groups.values():
		group["vat"] = flt(group["vat"], 2)
	return {"payer": payer, "groups": list(groups.values())}


@frappe.whitelist()
def get_supplier_vat_display(doc: str | dict):
	values = frappe.parse_json(doc)
	if not isinstance(values, dict) or values.get("doctype") not in {
		"Purchase Invoice",
		"Payment Request",
		"Payment Entry",
	}:
		frappe.throw(_("Unsupported payment route document."))
	doc = frappe.get_doc(values)
	if doc.is_new():
		frappe.has_permission(doc.doctype, "create", throw=True)
	else:
		frappe.get_doc(doc.doctype, doc.name).check_permission("read")
	supplier = (
		doc.get("supplier")
		if doc.doctype == "Purchase Invoice"
		else doc.get("party")
		if doc.get("party_type") == "Supplier"
		else None
	)
	if (
		not supplier
		or (doc.doctype == "Payment Entry" and doc.payment_type != "Pay")
		or (doc.doctype == "Payment Request" and doc.payment_request_type != "Outward")
	):
		return {"visible": False}
	party = frappe.get_doc("Supplier", supplier)
	party.check_permission("read")
	payer = bool(party.get("custom_is_vat_payer"))
	default_ratio = 1 / 6 if payer else 0

	def reference_ratio(doctype, name):
		if doctype not in {"Purchase Invoice", "Purchase Order"} or not name:
			return default_ratio
		source = frappe.get_doc(doctype, name)
		source.check_permission("read")
		if source.supplier != supplier or source.company != doc.company:
			frappe.throw(_("The invoice or order items changed. Open the matching window again."))
		return invoice_breakdown(source, payer)[1]

	rows = {}
	if doc.doctype == "Purchase Invoice":
		totals, ratio, vat_rows = invoice_breakdown(doc, payer)
		rows = _item_values(doc, payer, vat_rows)
		currency = doc.currency
	elif doc.doctype == "Payment Request":
		ratio = reference_ratio(doc.reference_doctype, doc.reference_name)
		totals = split_amount(doc.grand_total, ratio)
		rows = {row.name: split_amount(row.amount, ratio) for row in doc.get("payment_reference") or []}
		currency = doc.currency
	else:
		totals, rows = payment_breakdown(doc, payer, reference_ratio)
		currency = doc.paid_to_account_currency
	return {"visible": True, "payer": payer, "totals": totals, "rows": rows, "currency": currency}
