"""CEO votes and approval history for standalone supplier invoice requests."""

import json

import frappe
from frappe import _

from erpnext.buying.procurement_final_approval import (
	ADMINISTRATOR_OVERRIDE,
	get_approval_threshold,
	get_configured_final_approvers,
	has_administrator_approval,
)

FINAL = "Фінальне погодження"
TREASURY = "Перевірка казначейства"
SNAPSHOT = "custom_payment_ceo_approvers"
VOTES = "custom_payment_ceo_votes"
THRESHOLD = "custom_payment_ceo_threshold"
DEPARTMENT_ACTOR = "custom_payment_department_approved_by"
DYNAMIC = "custom_payment_dynamic_approval"


def uses_invoice_route(doc):
	return bool(
		doc.reference_doctype == "Purchase Invoice"
		and doc.payment_request_type == "Outward"
		and doc.party_type == "Supplier"
		and not doc.get("custom_procurement_approved")
	)


def approvers(doc):
	return frappe.parse_json(doc.get(SNAPSHOT) or "[]")


def votes(doc):
	return [
		user
		for user in dict.fromkeys(frappe.parse_json(doc.get(VOTES) or "[]"))
		if user in approvers(doc) or (user == "Administrator" and has_administrator_approval(doc, VOTES))
	]


def prepare_approval(doc, method=None):
	from erpnext.accounts.payment_procurement_route import set_procurement_approval_route

	set_procurement_approval_route(doc)
	before = doc.get_doc_before_save()
	if before and before.get("workflow_state") in {FINAL, TREASURY, "Погоджено"}:
		for field in ("grand_total", "currency", "company", "party", "reference_doctype", "reference_name"):
			if doc.get(field) != before.get(field):
				frappe.throw(_("Return the payment request for rework before changing its amount or source."))
	dynamic = uses_invoice_route(doc)
	doc.set(DYNAMIC, int(dynamic))
	if not dynamic:
		return
	state = doc.get("workflow_state") or "Чернетка"
	previous = before.get("workflow_state") if before else None
	if before:
		for field in (SNAPSHOT, VOTES, THRESHOLD, DEPARTMENT_ACTOR, "custom_payment_ceo_automatic"):
			doc.set(field, before.get(field))
	else:
		for field in (SNAPSHOT, VOTES, DEPARTMENT_ACTOR, "custom_payment_ceo_automatic"):
			doc.set(field, None)
	if not before or (state == "Перевірка підрозділу" and state != previous):
		doc.set(THRESHOLD, get_approval_threshold())
		doc.set(SNAPSHOT, None)
		doc.set(VOTES, "[]")
		doc.set(DEPARTMENT_ACTOR, None)
		doc.custom_payment_ceo_automatic = 0
	if previous == "Перевірка підрозділу" and state in {FINAL, TREASURY}:
		doc.set(DEPARTMENT_ACTOR, frappe.session.user)
		doc.custom_payment_ceo_automatic = int(state == TREASURY)
	if state == FINAL and state != previous:
		doc.set(SNAPSHOT, json.dumps(get_configured_final_approvers()))
		doc.set(VOTES, "[]")
	if previous == FINAL and state == TREASURY and not has_administrator_approval(doc, VOTES):
		if not approvers(doc) or set(votes(doc)) != set(approvers(doc)):
			frappe.throw(_("All recorded CEO approvers must approve this payment request."))


def record_vote(doc):
	doc = frappe.get_doc("Payment Request", doc.name, for_update=True)
	doc.check_permission("write")
	if doc.workflow_state != FINAL or not uses_invoice_route(doc):
		frappe.throw(_("The payment request is not awaiting CEO approval."))
	user = frappe.session.user
	# Existing requests are initialized on an explicit approval action, never during migration.
	if not doc.get(SNAPSHOT):
		doc.set(SNAPSHOT, json.dumps(get_configured_final_approvers(throw=user != "Administrator")))
		doc.set(VOTES, "[]")
		doc.set(THRESHOLD, get_approval_threshold())
	if user != "Administrator" and (
		user not in approvers(doc) or "Payments: Фінальний погоджувач" not in frappe.get_roles()
	):
		frappe.throw(
			_("Only a recorded CEO approver can decide this payment request."), frappe.PermissionError
		)
	approved = votes(doc)
	if user != "Administrator" and user in approved and len(approved) < len(approvers(doc)):
		frappe.throw(_("You have already approved this payment request."))
	if user not in approved or (user == "Administrator" and not has_administrator_approval(doc, VOTES)):
		if user not in approved:
			approved.append(user)
		stored = [*approved, ADMINISTRATOR_OVERRIDE] if user == "Administrator" else approved
		doc.set(VOTES, json.dumps(stored))
		frappe.db.set_value(
			doc.doctype,
			doc.name,
			{SNAPSHOT: doc.get(SNAPSHOT), VOTES: doc.get(VOTES), THRESHOLD: doc.get(THRESHOLD)},
		)
		doc.add_comment(
			"Comment",
			text=_("Administrator completed CEO approval without the remaining CEO votes.")
			if user == "Administrator"
			else _("CEO approval recorded: {0}/{1}.").format(len(approved), len(approvers(doc))),
		)
		from erpnext.accounts.payment_workflow_automation import sync_payment_request_assignment

		sync_payment_request_assignment(doc)
		doc.reload()
	return doc, has_administrator_approval(doc, VOTES) or len(approved) == len(approvers(doc))


def check_final_decision(doc):
	if (
		frappe.session.user != "Administrator"
		and uses_invoice_route(doc)
		and doc.get(SNAPSHOT)
		and frappe.session.user not in approvers(doc)
	):
		frappe.throw(
			_("Only a recorded CEO approver can decide this payment request."), frappe.PermissionError
		)
