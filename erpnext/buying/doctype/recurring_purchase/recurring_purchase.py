"""One approved purchasing basis, many invoices; no consumption limits in this MVP."""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import escape_html, flt, getdate, today

from erpnext.buying.procurement_final_approval import (
	ADMINISTRATOR_OVERRIDE,
	FINAL_APPROVAL_STATE,
	FINAL_APPROVER_ROLE,
	SNAPSHOT_FIELD,
	VOTES_FIELD,
	capture_final_approvers,
	get_approval_threshold,
	get_document_approved_users,
	get_document_final_approvers,
	has_administrator_approval,
	is_automatic_final_approval,
)
from erpnext.buying.procurement_workflow import BUYER_ROLE

DOCTYPE = "Recurring Purchase"
EDITABLE_STATES = {"Чернетка", "Потребує доопрацювання"}
BUSINESS_FIELDS = (
	"title",
	"supplier",
	"company",
	"currency",
	"conversion_rate",
	"valid_from",
	"valid_until",
	"contract_file",
	"taxes_and_charges",
	"notes",
)
ITEM_FIELDS = ("item_code", "description", "qty", "uom", "rate", "warehouse")


class RecurringPurchase(Document):
	def validate(self):
		before = self.get_doc_before_save()
		self.submitted_by = before.get("submitted_by") if before else None
		self.supplier_vat_pricing = before.get("supplier_vat_pricing", 0) if before else 0
		self.supplier_is_vat_payer = before.get("supplier_is_vat_payer", 0) if before else 0
		if not before and self.get("workflow_state") not in (None, "", "Чернетка"):
			frappe.throw(_("Create the recurring purchase as a draft first."))
		if before and before.workflow_state not in EDITABLE_STATES:
			if any(self.get(f) != before.get(f) for f in BUSINESS_FIELDS) or _items(self) != _items(before):
				frappe.throw(_("Return the recurring purchase for rework before changing its terms."))
		self.department_approved_by = before.department_approved_by if before else None
		self.ceo_approval_threshold = (
			before.ceo_approval_threshold
			if before and before.workflow_state not in EDITABLE_STATES
			else get_approval_threshold()
		)
		if getdate(self.valid_until) < getdate(self.valid_from):
			frappe.throw(_("Valid Until cannot be earlier than Valid From."))
		if not before or before.workflow_state in EDITABLE_STATES:
			from erpnext.setup.utils import get_exchange_rate

			company_currency = frappe.get_cached_value("Company", self.company, "default_currency")
			self.conversion_rate = get_exchange_rate(self.currency, company_currency, today(), "for_buying")
			self.taxes_and_charges = None
			self.supplier_vat_pricing = 1
		if not self.items or flt(self.conversion_rate) <= 0:
			frappe.throw(_("Add purchase items and a positive exchange rate."))
		for row in self.items:
			if flt(row.qty) <= 0 or flt(row.rate) < 0:
				frappe.throw(_("Quantity must be positive and price cannot be negative."))
			item = frappe.get_cached_doc("Item", row.item_code)
			if item.disabled or not item.is_purchase_item:
				frappe.throw(_("Item {0} is not available for purchase.").format(row.item_code))
			row.item_name = item.item_name
			row.amount = flt(row.qty) * flt(row.rate)
			if (
				row.warehouse
				and frappe.get_cached_value("Warehouse", row.warehouse, "company") != self.company
			):
				frappe.throw(_("Warehouse must belong to the selected company."))
		if before and before.workflow_state not in EDITABLE_STATES:
			self.net_total, self.grand_total = before.net_total, before.grand_total
		else:
			payer = frappe.get_cached_value("Supplier", self.supplier, "custom_is_vat_payer")
			self.supplier_is_vat_payer = int(bool(payer))
			self.grand_total = flt(sum(flt(row.amount) for row in self.items), self.precision("grand_total"))
			vat = (
				flt(self.grand_total - self.grand_total / 1.2, self.precision("grand_total")) if payer else 0
			)
			self.net_total = self.grand_total - vat
		capture_final_approvers(self)
		if before and before.workflow_state != self.workflow_state:
			from erpnext.buying.procurement_workflow_reason import validate_required_reason

			validate_required_reason(self)
			if before.workflow_state == "Перевірка підрозділу" and self.workflow_state in {
				FINAL_APPROVAL_STATE,
				"Погоджено",
			}:
				self.department_approved_by = frappe.session.user
			if self.workflow_state == "Перевірка підрозділу":
				self.department_approved_by = None
				self.set(VOTES_FIELD, "[]")
				self.set(SNAPSHOT_FIELD, None)
				self.final_approval_count = 0
				self.final_approved_by_1 = self.final_approved_by_2 = None
			if self.workflow_state == FINAL_APPROVAL_STATE and self.owner in get_document_final_approvers(
				self
			):
				# Same creator-vote policy as consolidated purchases, without touching their tasks.
				self.set(VOTES_FIELD, json.dumps([self.owner]))
				self.final_approval_count = 1
				self.final_approved_by_1 = self.owner

	def before_submit(self):
		self.submitted_by = frappe.session.user

	def on_update(self):
		before = self.get_doc_before_save()
		if before and before.workflow_state == self.workflow_state:
			return
		from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

		users = []
		if self.workflow_state == "Перевірка підрозділу":
			from erpnext.buying.procurement_workflow import CONSOLIDATED_DEPARTMENT_ASSIGNMENT_RULE_NAME

			users = frappe.get_all(
				"Assignment Rule User",
				filters={
					"parent": CONSOLIDATED_DEPARTMENT_ASSIGNMENT_RULE_NAME,
				},
				pluck="user",
			)
		elif self.workflow_state == FINAL_APPROVAL_STATE:
			users = list(set(get_document_final_approvers(self)) - set(get_document_approved_users(self)))
		elif self.workflow_state in {"Погоджено", "Потребує доопрацювання", "Відхилено"}:
			users = [self.owner]
		users = [u for u in users if frappe.get_cached_value("User", u, "enabled")]
		if users:
			enqueue_create_notification(
				users,
				{
					"type": "Alert",
					"document_type": self.doctype,
					"document_name": self.name,
					"from_user": frappe.session.user,
					"subject": _("Recurring purchase {0}: {1}").format(self.name, self.workflow_state),
					"email_content": _("Review recurring purchase {0}.").format(escape_html(self.name)),
				},
			)


def _items(doc):
	return [tuple(row.get(f) for f in ITEM_FIELDS) for row in doc.items]


def check_active(source, posting_date=None):
	if source.docstatus != 1 or source.workflow_state != "Проведено":
		frappe.throw(_("Submit the approved recurring purchase before creating an invoice."))
	for date in (today(), posting_date or today()):
		if not getdate(source.valid_from) <= getdate(date) <= getdate(source.valid_until):
			frappe.throw(
				_(
					"The invoice can only be created and submitted during the recurring purchase validity period."
				)
			)


def build_invoice(source):
	from erpnext.controllers.accounts_controller import get_taxes_and_charges

	invoice = frappe.new_doc("Purchase Invoice")
	invoice.update(
		{
			"supplier": source.supplier,
			"company": source.company,
			"currency": source.currency,
			"conversion_rate": source.conversion_rate,
			"posting_date": today(),
			"update_stock": 0,
			"custom_recurring_purchase": source.name,
			"taxes_and_charges": source.taxes_and_charges,
		}
	)
	for row in source.items:
		invoice.append("items", {f: row.get(f) for f in ITEM_FIELDS})
	if source.taxes_and_charges:
		if (
			frappe.get_cached_value(
				"Purchase Taxes and Charges Template", source.taxes_and_charges, "company"
			)
			!= source.company
		):
			frappe.throw(_("Tax template must belong to the selected company."))
		invoice.set(
			"taxes", get_taxes_and_charges("Purchase Taxes and Charges Template", source.taxes_and_charges)
		)
	invoice.set_missing_values()
	if source.get("supplier_vat_pricing"):
		# Like consolidated purchases, rate is the final payable price; VAT is a breakdown.
		# Party/item defaults must not add VAT again on top of that price.
		invoice.taxes_and_charges = None
		invoice.set("taxes", [])
		for row in invoice.items:
			row.item_tax_template = None
	# Item/party defaults must not replace the explicitly entered template prices.
	for original, row in zip(source.items, invoice.items, strict=True):
		row.rate = original.rate
		row.discount_percentage = row.discount_amount = 0
	invoice.calculate_taxes_and_totals()
	return invoice


@frappe.whitelist()
def make_purchase_invoice(source_name: str):
	source = frappe.get_doc(DOCTYPE, source_name)
	source.check_permission("read")
	if frappe.session.user != "Administrator" and BUYER_ROLE not in frappe.get_roles():
		frappe.throw(_("Only a buyer can create invoices from a recurring purchase."), frappe.PermissionError)
	frappe.has_permission("Purchase Invoice", "create", throw=True)
	check_active(source)
	return build_invoice(source)


def apply_workflow(doc, action):
	from frappe.model.workflow import apply_workflow as core_apply_workflow

	from erpnext.buying.procurement_workflow_reason import (
		REQUIRED_ACTIONS,
		_apply_creator_department_approval,
		_validate_reason,
	)

	payload = frappe.parse_json(doc)
	current = frappe.get_doc(DOCTYPE, payload.get("name"), for_update=True)
	current.check_permission("write")
	reason = (payload.get("workflow_action_reason") or "").strip()
	if action in REQUIRED_ACTIONS:
		_validate_reason(reason)
	if current.workflow_state == FINAL_APPROVAL_STATE:
		user = frappe.session.user
		if (
			user != "Administrator"
			and action != "Відкликати на доопрацювання"
			and (
				user not in get_document_final_approvers(current)
				or FINAL_APPROVER_ROLE not in frappe.get_roles()
			)
		):
			frappe.throw(
				_("Only a configured CEO approver can approve this purchase."), frappe.PermissionError
			)
		if action == "Погодити":
			approved = get_document_approved_users(current)
			if (
				user != "Administrator"
				and user in approved
				and set(approved) != set(get_document_final_approvers(current))
			):
				frappe.throw(_("You have already approved this purchase."))
			if user not in approved:
				approved.append(user)
			stored = [*approved, ADMINISTRATOR_OVERRIDE] if user == "Administrator" else approved
			values = {VOTES_FIELD: json.dumps(stored), "final_approval_count": len(approved)}
			for i, field in enumerate(("final_approved_by_1", "final_approved_by_2")):
				values[field] = approved[i] if i < len(approved) else None
			frappe.db.set_value(DOCTYPE, current.name, values)
			current.reload()
			current.add_comment(
				"Comment",
				_("CEO approval recorded: {0}/{1}.").format(
					len(approved), len(get_document_final_approvers(current))
				),
			)
			if user != "Administrator" and set(approved) != set(get_document_final_approvers(current)):
				return current
	old_reason = frappe.flags.procurement_workflow_reason
	old_action = frappe.flags.procurement_workflow_action
	frappe.flags.procurement_workflow_reason = reason
	frappe.flags.procurement_workflow_action = action
	try:
		result = core_apply_workflow(current, action)
		# Reuse the department creator policy, retaining the actual approver identity.
		department_creator_approval = result.workflow_state == "Перевірка підрозділу"
		result = _apply_creator_department_approval(result, core_apply_workflow)
		if department_creator_approval and result.workflow_state != "Перевірка підрозділу":
			result.db_set("department_approved_by", result.owner)
		if reason:
			result.add_comment("Comment", escape_html(reason))
		return result
	finally:
		frappe.flags.procurement_workflow_reason = old_reason
		frappe.flags.procurement_workflow_action = old_action


@frappe.whitelist()
def get_overview(name: str):
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")
	invoices = (
		frappe.get_list(
			"Purchase Invoice",
			filters={"custom_recurring_purchase": name},
			fields=[
				"name",
				"posting_date",
				"docstatus",
				"status",
				"currency",
				"grand_total",
				"outstanding_amount",
				"owner",
			],
			order_by="creation desc",
			limit_page_length=0,
		)
		if frappe.has_permission("Purchase Invoice", "read")
		else []
	)
	submitted_by = doc.get("submitted_by")
	if not submitted_by and doc.docstatus == 1:
		submitted_by = frappe.db.get_value(
			"Workflow Action",
			{
				"reference_doctype": DOCTYPE,
				"reference_name": name,
				"workflow_state": "Погоджено",
				"status": "Completed",
			},
			"completed_by",
			order_by="modified desc",
		)
	users = {doc.owner, doc.department_approved_by, submitted_by, *get_document_approved_users(doc)}
	users.update(row.owner for row in invoices)
	identities = {
		row.name: {"user": row.name, "full_name": row.full_name, "user_image": row.user_image}
		for row in frappe.get_all(
			"User",
			filters={"name": ["in", list(users - {None, ""})]},
			fields=["name", "full_name", "user_image"],
		)
	}
	return {
		"invoices": invoices,
		"users": identities,
		"submitted_by": submitted_by,
		"approvers": get_document_final_approvers(doc),
		"votes": get_document_approved_users(doc),
		"automatic": is_automatic_final_approval(doc),
		"administrator": has_administrator_approval(doc),
	}
