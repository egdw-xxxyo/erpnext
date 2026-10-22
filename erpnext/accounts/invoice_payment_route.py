"""Display inherited approvals and protect invoice payments with pending requests."""

import json
from urllib.parse import urlsplit

import frappe
from frappe import _
from frappe.utils import flt, get_link_to_form

from erpnext.accounts.payment_request_approval import DEPARTMENT_ACTOR, FINAL, TREASURY, approvers, votes
from erpnext.buying.procurement_final_approval import (
	get_document_approved_users,
	has_administrator_approval,
	is_automatic_final_approval,
)

SNAPSHOT = "custom_payment_route_snapshot"


def _invoice(doc):
	if doc.doctype == "Purchase Invoice":
		return doc
	if doc.reference_doctype == "Purchase Invoice" and doc.reference_name:
		return frappe.get_doc("Purchase Invoice", doc.reference_name)


def _department_actor(doctype, name):
	return frappe.db.get_value(
		"Workflow Action",
		{
			"reference_doctype": doctype,
			"reference_name": name,
			"workflow_state": "Перевірка підрозділу",
			"status": "Completed",
		},
		"completed_by",
		order_by="modified desc",
	)


def _source_snapshot(invoice):
	source = invoice.get("custom_recurring_purchase") or invoice.get("custom_consolidated_purchase_order")
	if not source:
		return None
	source_type = (
		"Recurring Purchase" if invoice.get("custom_recurring_purchase") else "Consolidated Purchase Order"
	)
	order = frappe.get_doc(source_type, source)
	if order.docstatus != 1 or order.workflow_state != "Проведено":
		return None
	return {
		"source": order.name,
		"source_doctype": source_type,
		"source_owner": order.owner,
		"initiator": order.get("request_initiator_user") or order.owner,
		"department": order.get("department_approved_by") or _department_actor(order.doctype, order.name),
		"ceo": get_document_approved_users(order),
		"automatic": is_automatic_final_approval(order),
		"ceo_administrator": has_administrator_approval(order),
		"invoice_creator": invoice.owner or frappe.session.user,
	}


def capture_source_history(doc, method=None):
	before = doc.get_doc_before_save()
	if doc.doctype == "Payment Request":
		doc.custom_payment_treasury_approved_by = (
			before.get("custom_payment_treasury_approved_by") if before else None
		)
		if before and before.workflow_state == TREASURY and doc.workflow_state == "Погоджено":
			doc.custom_payment_treasury_approved_by = frappe.session.user
	if (
		before
		and before.get(SNAPSHOT)
		and (
			doc.doctype == "Purchase Invoice"
			or (doc.reference_doctype, doc.reference_name)
			== (before.reference_doctype, before.reference_name)
		)
	):
		doc.set(SNAPSHOT, before.get(SNAPSHOT))
		return
	invoice = _invoice(doc)
	stored = (
		invoice.get(SNAPSHOT)
		if invoice and doc.doctype == "Payment Request"
		else (before.get(SNAPSHOT) if before else None)
	)
	data = frappe.parse_json(stored) if stored else None
	if not data and invoice:
		data = _source_snapshot(invoice)
	doc.set(SNAPSHOT, json.dumps(data) if data else None)


def _user(user):
	if not user:
		return None
	values = frappe.get_cached_value("User", user, ["full_name", "user_image"], as_dict=True) or {}
	return {
		"user": user,
		"full_name": values.get("full_name") or user,
		"user_image": values.get("user_image"),
	}


def _step(key, title, users, completed=False, automatic=False):
	return {
		"key": key,
		"title": title,
		"users": [_user(user) for user in dict.fromkeys(users) if user],
		"completed": bool(completed),
		"automatic": bool(automatic),
	}


def _prepaid_receipt(invoice):
	"""An original receipt proves the existing purchase, not a new treasury payment."""
	if (
		not invoice
		or invoice.get("docstatus") != 1
		or invoice.get("is_return")
		or not invoice.get("custom_consolidated_purchase_order")
		or not (invoice.get("is_paid") or flt(invoice.get("outstanding_amount")) <= 0)
	):
		return None
	from erpnext.buying.procurement_workflow_reason import _get_prepaid_material_request

	order = frappe.get_doc("Consolidated Purchase Order", invoice.custom_consolidated_purchase_order)
	if order.docstatus != 1 or order.workflow_state != "Проведено" or order.company != invoice.company:
		return None
	source = _get_prepaid_material_request(order)
	if not source:
		return None
	request = frappe.get_doc("Material Request", source.name)
	for row in request.get("custom_purchase_receipts") or []:
		url = row.get("invoice_pdf") or ""
		if urlsplit(url).path.lower().endswith(".pdf") and frappe.db.exists("File", {"file_url": url}):
			return {"user": source.owner, "request": source.name, "receipt_url": url}


def _payment_progress(doc, invoice):
	evidence = _prepaid_receipt(invoice)
	if evidence:
		step = _step("payment", "Payment confirmed by Material Request receipt", [evidence["user"]], True)
		step["external_payment"] = True
		return step
	filters = {"parenttype": "Payment Entry", "docstatus": 1, "allocated_amount": [">", 0]}
	if doc.doctype == "Payment Request":
		filters["payment_request"] = doc.name
	else:
		filters.update(reference_doctype="Purchase Invoice", reference_name=invoice.name)
	names = frappe.get_all("Payment Entry Reference", filters=filters, pluck="parent")
	entries = (
		frappe.get_all(
			"Payment Entry",
			filters={"name": ["in", names], "docstatus": 1, "payment_type": "Pay"},
			fields=["name", "owner", "custom_fiscal_receipt"],
		)
		if names
		else []
	)
	paid = doc.status == "Paid" if doc.doctype == "Payment Request" else flt(invoice.outstanding_amount) <= 0
	complete = paid and bool(entries) and all(row.custom_fiscal_receipt for row in entries)
	return _step("payment", "Payment and payment instruction", [row.owner for row in entries], complete)


@frappe.whitelist()
def get_payment_route(doctype: str, name: str):
	if doctype not in {"Purchase Invoice", "Payment Request"}:
		frappe.throw(_("Unsupported payment route document."))
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	invoice = _invoice(doc)
	data = (
		frappe.parse_json(doc.get(SNAPSHOT))
		if doc.get(SNAPSHOT)
		else (_source_snapshot(invoice) if invoice else None)
	)
	if data:
		steps = [
			_step("initiator", "Purchase initiator", [data.get("initiator")], True),
			_step("department", "Department Review", [data.get("department")], True),
			_step("ceo", "Final Approval", data.get("ceo") or [], True, data.get("automatic")),
			_step("invoice", "Invoice created by", [data.get("invoice_creator")], True),
		]
	elif doctype == "Payment Request" and invoice:
		state = doc.workflow_state
		department_done = state in {FINAL, TREASURY, "Погоджено"}
		ceo_done = state in {TREASURY, "Погоджено"}
		steps = [
			_step("initiator", "Payment initiator", [doc.get("custom_initiator_user") or doc.owner], True),
			_step(
				"department",
				"Department Review",
				[doc.get(DEPARTMENT_ACTOR) or _department_actor(doctype, name)],
				department_done,
			),
			_step("ceo", "Final Approval", votes(doc), ceo_done, doc.get("custom_payment_ceo_automatic")),
			_step(
				"treasury",
				"Treasury Review",
				[doc.get("custom_payment_treasury_approved_by")] if doc.docstatus == 1 else [],
				doc.docstatus == 1,
			),
		]
	else:
		return {"visible": False}
	steps.append(_payment_progress(doc, invoice))
	return {
		"visible": True,
		"source": data.get("source") if data else None,
		"source_doctype": data.get("source_doctype", "Consolidated Purchase Order") if data else None,
		"source_creator": _user(
			data.get("source_owner")
			or frappe.get_cached_value(
				data.get("source_doctype", "Consolidated Purchase Order"), data["source"], "owner"
			)
		)
		if data
		else None,
		"steps": steps,
		"ceo_votes": len(votes(doc)) if not data else len(data.get("ceo") or []),
		"ceo_administrator": has_administrator_approval(doc, "custom_payment_ceo_votes")
		if not data
		else bool(data.get("ceo_administrator")),
		"ceo_required": len(approvers(doc)) if not data else len(data.get("ceo") or []),
	}


def _pending_requests(invoice):
	return frappe.get_all(
		"Payment Request",
		filters={
			"reference_doctype": "Purchase Invoice",
			"reference_name": invoice.name,
			"docstatus": 0,
			"workflow_state": ["!=", "Відхилено"],
		},
		fields=["name", "workflow_state"],
		order_by="name",
	)


def _can_confirm(invoice, requests):
	return bool(
		_source_snapshot(invoice)
		and requests
		and all(row.workflow_state in {"Чернетка", TREASURY} for row in requests)
		and (frappe.session.user == "Administrator" or "Payments: Казначей" in frappe.get_roles())
	)


@frappe.whitelist()
def get_invoice_payment_context(invoice_name: str):
	invoice = frappe.get_doc("Purchase Invoice", invoice_name)
	invoice.check_permission("read")
	requests = _pending_requests(invoice)
	return {"requests": requests, "can_confirm": _can_confirm(invoice, requests)}


@frappe.whitelist(methods=["POST"])
def confirm_invoice_payment_requests(invoice_name: str, request_names: str | list[str]):
	from frappe.model.workflow import apply_workflow

	invoice = frappe.get_doc("Purchase Invoice", invoice_name, for_update=True)
	invoice.check_permission("read")
	if invoice.docstatus != 1 or flt(invoice.outstanding_amount) <= 0:
		frappe.throw(_("Select a submitted invoice with an unpaid balance."))
	requests = _pending_requests(invoice)
	selected = frappe.parse_json(request_names)
	if sorted(selected) != sorted(row.name for row in requests) or not _can_confirm(invoice, requests):
		frappe.throw(
			_(
				"The payment request has not completed approval. Complete its approval before paying this invoice."
			)
		)
	for row in requests:
		request = frappe.get_doc("Payment Request", row.name, for_update=True)
		request.check_permission("submit")
		if (
			request.docstatus != 0
			or request.workflow_state != row.workflow_state
			or request.reference_name != invoice.name
		):
			frappe.throw(_("The payment request changed. Refresh the invoice and try again."))
		if request.workflow_state == "Чернетка":
			request = apply_workflow(request.as_dict(), "Подати на перевірку казначейству")
		apply_workflow(request.as_dict(), "Погодити")
	return [row.name for row in requests]


def validate_pending_requests(doc, method=None):
	if doc.payment_type != "Pay" or doc.party_type != "Supplier":
		return
	for row in doc.references:
		if row.reference_doctype != "Purchase Invoice" or flt(row.allocated_amount) <= 0:
			continue
		invoice = frappe.get_doc("Purchase Invoice", row.reference_name, for_update=True)
		requests = _pending_requests(invoice)
		if requests:
			frappe.throw(
				_(
					"The payment request has not completed approval. Complete its approval before paying this invoice."
				)
				+ "<br>"
				+ ", ".join(get_link_to_form("Payment Request", request.name) for request in requests)
			)
