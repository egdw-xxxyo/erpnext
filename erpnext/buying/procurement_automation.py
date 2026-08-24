import json
from urllib.parse import unquote, urlsplit

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
from frappe.desk.form.assign_to import _add as add_assignment
from frappe.utils import escape_html, get_link_to_form, nowdate

from erpnext.buying.procurement_workflow import BUYER_ROLE

PURCHASE_ORDER_DOCTYPE = "Purchase Order"
CONSOLIDATED_PURCHASE_ORDER_DOCTYPE = "Consolidated Purchase Order"
MATERIAL_REQUEST_DOCTYPE = "Material Request"
PREPAID_PURCHASE_NOTE = (
	"The materials have already been purchased. Review the attached receipts and verify suppliers and prices."
)
EXTERNAL_PAYMENT_NOTE = "Цей рахунок оплачено не компанією, а ініціатором замовлення матеріалів."
PROCUREMENT_DOCTYPES = (
	MATERIAL_REQUEST_DOCTYPE,
	CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
	PURCHASE_ORDER_DOCTYPE,
)
PARTICIPANT_FIELDS = {
	MATERIAL_REQUEST_DOCTYPE: "custom_procurement_participants",
	CONSOLIDATED_PURCHASE_ORDER_DOCTYPE: "procurement_participants",
	PURCHASE_ORDER_DOCTYPE: "custom_procurement_participants",
}
COMPLETION_FIELDS = {
	MATERIAL_REQUEST_DOCTYPE: "custom_procurement_completion_status",
	CONSOLIDATED_PURCHASE_ORDER_DOCTYPE: "procurement_completion_status",
	PURCHASE_ORDER_DOCTYPE: "custom_procurement_completion_status",
}
PROCUREMENT_PREPARATION = "Підготовка"
PROCUREMENT_APPROVAL = "Погодження"
PROCUREMENT_AWAITING_PAYMENT = "Очікує оплату"
PROCUREMENT_AWAITING_RECEIPT = "Очікує надходження"
PROCUREMENT_COMPLETED = "Завершено"
PROCUREMENT_STATUS_PRIORITY = {
	PROCUREMENT_PREPARATION: 0,
	PROCUREMENT_APPROVAL: 1,
	PROCUREMENT_AWAITING_PAYMENT: 2,
	PROCUREMENT_AWAITING_RECEIPT: 3,
	PROCUREMENT_COMPLETED: 4,
}


def require_buyer_role():
	if frappe.session.user == "Administrator" or BUYER_ROLE in frappe.get_roles():
		return
	frappe.throw(
		_("Only a buyer can create procurement documents from a Material Request."),
		title=_("Insufficient Permissions"),
	)


@frappe.whitelist()
def make_purchase_order(source_name, target_doc=None, args=None):
	require_buyer_role()
	validate_material_requests_available([source_name])
	from erpnext.stock.doctype.material_request.material_request import make_purchase_order as core_make

	mapped_order = core_make(source_name, None, args)
	return _make_consolidated_order(mapped_order, source_name)


@frappe.whitelist()
def make_purchase_order_based_on_supplier(source_name, target_doc=None, args=None):
	require_buyer_role()
	validate_material_requests_available([source_name])
	from erpnext.stock.doctype.material_request.material_request import (
		make_purchase_order_based_on_supplier as core_make,
	)

	mapped_order = core_make(source_name, None, args)
	return _make_consolidated_order(mapped_order, source_name)


@frappe.whitelist()
def make_request_for_quotation(source_name, target_doc=None):
	require_buyer_role()
	from erpnext.stock.doctype.material_request.material_request import (
		make_request_for_quotation as core_make,
	)

	return core_make(source_name, target_doc)


@frappe.whitelist()
def make_supplier_quotation(source_name, target_doc=None):
	require_buyer_role()
	from erpnext.stock.doctype.material_request.material_request import make_supplier_quotation as core_make

	return core_make(source_name, target_doc)


def on_material_request_submit(doc, method=None):
	if doc.material_request_type != "Purchase":
		return
	actor = _current_actor()
	doc.add_comment(
		"Comment",
		text=_("{0} submitted the Material Request and transferred it to procurement.").format(
			f"<b>{escape_html(actor)}</b>"
		),
	)


def validate_material_request_purchase_receipts(doc, method=None):
	if not doc.get("custom_items_already_purchased"):
		doc.custom_prepaid_purchase_note = None
		return

	doc.custom_prepaid_purchase_note = _(PREPAID_PURCHASE_NOTE)
	receipts = doc.get("custom_purchase_receipts") or []
	if not receipts:
		frappe.throw(_("Attach at least one PDF receipt when the materials are already purchased."))

	for row in receipts:
		row.invoice_document = _get_file_name(row.invoice_pdf)
		if not row.invoice_pdf:
			frappe.throw(_("Row {0}: Attach a PDF receipt.").format(row.idx))
		if not urlsplit(row.invoice_pdf).path.lower().endswith(".pdf"):
			frappe.throw(
				_("The purchase receipt must be a PDF file."),
				title=_("Unsupported File Format"),
			)


def validate_material_requests_available(material_requests, exclude=None):
	for material_request in set(material_requests or []):
		if not material_request:
			continue
		existing = get_active_consolidated_purchase_order(material_request, exclude=exclude)
		if existing:
			frappe.throw(
				_(
					"Material Request {0} is already linked to active consolidated order {1}. "
					"A new consolidated order can be created only after the existing one is rejected."
				).format(
					get_link_to_form(MATERIAL_REQUEST_DOCTYPE, material_request),
					get_link_to_form(CONSOLIDATED_PURCHASE_ORDER_DOCTYPE, existing),
				),
				title=_("Consolidated order already exists"),
			)


def get_active_consolidated_purchase_order(material_request, exclude=None):
	parents = set(
		frappe.get_all(
			"Consolidated Purchase Order Item",
			filters={"material_request": material_request},
			pluck="parent",
		)
	)
	parents.update(
		frappe.get_all(
			CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
			filters={"material_request": material_request},
			pluck="name",
		)
	)
	if exclude:
		parents.discard(exclude)
	if not parents:
		return None

	return frappe.db.get_value(
		CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
		{
			"name": ["in", list(parents)],
			"workflow_state": ["!=", "Відхилено"],
			"docstatus": ["!=", 2],
		},
		"name",
		order_by="creation desc",
	)


@frappe.whitelist()
def get_existing_consolidated_purchase_order(source_name):
	doc = frappe.get_doc(MATERIAL_REQUEST_DOCTYPE, source_name)
	doc.check_permission("read")
	return get_active_consolidated_purchase_order(source_name)


def set_purchase_invoice_external_payment_details(doc, method=None):
	consolidated_name = doc.get("custom_consolidated_purchase_order")
	if not consolidated_name:
		purchase_orders = {row.purchase_order for row in doc.get("items") or [] if row.purchase_order}
		if purchase_orders:
			consolidated_name = frappe.db.get_value(
				"Purchase Order",
				{"name": ["in", list(purchase_orders)]},
				"custom_consolidated_purchase_order",
			)
	if not consolidated_name or not frappe.db.exists(
		CONSOLIDATED_PURCHASE_ORDER_DOCTYPE, consolidated_name
	):
		_clear_external_payment_details(doc)
		return
	doc.custom_consolidated_purchase_order = consolidated_name

	consolidated = frappe.get_doc(CONSOLIDATED_PURCHASE_ORDER_DOCTYPE, consolidated_name)
	if not consolidated.items_already_purchased:
		_clear_external_payment_details(doc)
		return
	set_external_payment_details(doc, consolidated)


def create_external_payment_purchase_receipt(doc, method=None):
	"""Receive prepaid goods automatically once the buyer submits their Purchase Invoice."""
	if (
		doc.docstatus != 1
		or not doc.get("custom_paid_outside_company")
		or doc.get("update_stock")
		or doc.get("is_return")
	):
		return

	consolidated_name = doc.get("custom_consolidated_purchase_order")
	if not consolidated_name or not frappe.db.get_value(
		CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
		consolidated_name,
		"items_already_purchased",
	):
		return

	if frappe.db.exists(
		"Purchase Receipt Item",
		{
			"purchase_invoice": doc.name,
			"docstatus": ["<", 2],
		},
	):
		return

	from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_purchase_receipt

	receipt = make_purchase_receipt(doc.name)
	if not receipt.get("items"):
		return

	receipt.flags.ignore_permissions = True
	receipt.insert(ignore_permissions=True)
	receipt.submit()

	initiator = _get_primary_procurement_initiator(consolidated_name)
	initiator_name = (
		frappe.get_cached_value("User", initiator, "full_name") or initiator
		if initiator
		else _("the initiator")
	)
	receipt.add_comment(
		"Info",
		text=_("Received automatically on behalf of initiator {0} for prepaid invoice {1}.").format(
			f"<b>{escape_html(initiator_name)}</b>",
			get_link_to_form("Purchase Invoice", doc.name, escape_html(doc.name)),
		),
	)


def set_external_payment_details(invoice, consolidated):
	material_requests = sorted(
		{row.material_request for row in consolidated.items if row.material_request}
		or ({consolidated.material_request} if consolidated.material_request else set())
	)
	payer = (
		frappe.db.get_value(
			MATERIAL_REQUEST_DOCTYPE,
			{"name": ["in", material_requests]},
			"owner",
			order_by="creation asc",
		)
		if material_requests
		else None
	)
	invoice.custom_paid_outside_company = 1
	invoice.custom_external_payer = payer
	invoice.custom_external_payment_note = EXTERNAL_PAYMENT_NOTE


def _clear_external_payment_details(invoice):
	invoice.custom_paid_outside_company = 0
	invoice.custom_external_payer = None
	invoice.custom_external_payment_note = None


def sync_existing_purchase_invoice_external_payment_details():
	if not frappe.db.has_column("Purchase Invoice", "custom_paid_outside_company"):
		return
	for name in frappe.get_all(
		"Purchase Invoice",
		filters={"custom_consolidated_purchase_order": ["is", "set"]},
		pluck="name",
	):
		invoice = frappe.get_doc("Purchase Invoice", name)
		set_purchase_invoice_external_payment_details(invoice)
		frappe.db.set_value(
			"Purchase Invoice",
			name,
			{
				"custom_paid_outside_company": invoice.custom_paid_outside_company,
				"custom_external_payer": invoice.custom_external_payer,
				"custom_external_payment_note": invoice.custom_external_payment_note,
			},
			update_modified=False,
		)


def on_purchase_order_insert(doc, method=None):
	material_requests = sorted({row.material_request for row in doc.items if row.material_request})
	if not material_requests:
		return

	actor = _current_actor()
	order_link = get_link_to_form(PURCHASE_ORDER_DOCTYPE, doc.name, escape_html(doc.name))
	for material_request in material_requests:
		_close_assignments_silently(MATERIAL_REQUEST_DOCTYPE, material_request)
		request_doc = frappe.get_doc(MATERIAL_REQUEST_DOCTYPE, material_request)
		request_doc.add_comment(
			"Comment",
			text=_(
				"{0} created {1} based on this Material Request and completed its processing by the buyer."
			).format(f"<b>{escape_html(actor)}</b>", order_link),
		)

	request_links = ", ".join(
		get_link_to_form(MATERIAL_REQUEST_DOCTYPE, name, escape_html(name)) for name in material_requests
	)
	doc.add_comment(
		"Comment",
		text=_("{0} created this Purchase Order from {1}.").format(
			f"<b>{escape_html(actor)}</b>", request_links
		),
	)
	sync_procurement_participants_for_reference(PURCHASE_ORDER_DOCTYPE, doc.name)


def sync_current_assignees(todo, method=None):
	sync_procurement_participants(todo, method)

	if todo.reference_type != CONSOLIDATED_PURCHASE_ORDER_DOCTYPE or not todo.reference_name:
		return

	rows = frappe.get_all(
		"ToDo",
		filters={
			"reference_type": CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
			"reference_name": todo.reference_name,
			"status": "Open",
		},
		fields=["name", "allocated_to"],
	)
	users = [row.allocated_to for row in rows if method != "on_trash" or row.name != todo.name]
	full_names = []
	for user in users:
		full_name = frappe.get_cached_value("User", user, "full_name") or user
		if full_name not in full_names:
			full_names.append(full_name)

	if frappe.db.exists(CONSOLIDATED_PURCHASE_ORDER_DOCTYPE, todo.reference_name):
		frappe.db.set_value(
			CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
			todo.reference_name,
			"current_assignees",
			", ".join(full_names),
			update_modified=False,
		)


def sync_procurement_participants(todo, method=None):
	"""Keep an immutable, filterable history of everyone assigned in a procurement chain."""
	if todo.reference_type not in PROCUREMENT_DOCTYPES or not todo.reference_name:
		return
	sync_procurement_participants_for_reference(
		todo.reference_type,
		todo.reference_name,
		additional_user=todo.allocated_to,
	)


def sync_procurement_participants_for_reference(
	reference_type, reference_name, additional_user=None
):
	if reference_type not in PROCUREMENT_DOCTYPES or not reference_name:
		return

	chain = _get_procurement_chain(reference_type, reference_name)
	users = set()
	for doctype, names in chain.items():
		if not names:
			continue
		identity_fields = ["owner"]
		if doctype == MATERIAL_REQUEST_DOCTYPE:
			identity_fields.append("custom_procurement_initiator_user")
		elif doctype == CONSOLIDATED_PURCHASE_ORDER_DOCTYPE:
			identity_fields.append("initiator_user")
		for row in frappe.get_all(
			doctype,
			filters={"name": ["in", list(names)]},
			fields=identity_fields,
		):
			users.update(row.get(field) for field in identity_fields if row.get(field))
		users.update(
			frappe.get_all(
				"ToDo",
				filters={
					"reference_type": doctype,
					"reference_name": ["in", list(names)],
					"allocated_to": ["is", "set"],
				},
				pluck="allocated_to",
			)
		)

	# Preserve users from ToDos that may already have been deleted.
	for doctype, names in chain.items():
		fieldname = PARTICIPANT_FIELDS[doctype]
		if not frappe.db.has_column(doctype, fieldname):
			continue
		for value in frappe.get_all(
			doctype,
			filters={"name": ["in", list(names)]},
			pluck=fieldname,
		):
			users.update(_parse_participants(value))

	if additional_user:
		users.add(additional_user)
	_serialized_users = json.dumps(sorted(users), ensure_ascii=False)
	for doctype, names in chain.items():
		fieldname = PARTICIPANT_FIELDS[doctype]
		if not names or not frappe.db.has_column(doctype, fieldname):
			continue
		for name in names:
			frappe.db.set_value(doctype, name, fieldname, _serialized_users, update_modified=False)


def sync_all_procurement_participants():
	"""Backfill assignment history into the three procurement list filter fields."""
	if not all(frappe.db.has_column(dt, field) for dt, field in PARTICIPANT_FIELDS.items()):
		return

	for row in frappe.get_all(
		"ToDo",
		filters={"reference_type": ["in", list(PROCUREMENT_DOCTYPES)]},
		fields=["reference_type", "reference_name", "allocated_to"],
		order_by="creation asc",
	):
		sync_procurement_participants(row)

	# Drafts may not have a ToDo yet, but their creator already participates.
	for doctype, fieldname in PARTICIPANT_FIELDS.items():
		identity_fields = ["name", "owner", fieldname]
		if doctype == MATERIAL_REQUEST_DOCTYPE:
			identity_fields.append("custom_procurement_initiator_user")
		elif doctype == CONSOLIDATED_PURCHASE_ORDER_DOCTYPE:
			identity_fields.append("initiator_user")
		for row in frappe.get_all(doctype, fields=identity_fields):
			users = set(_parse_participants(row.get(fieldname)))
			users.add(row.owner)
			users.update(
				row.get(field)
				for field in identity_fields
				if field not in ("name", "owner", fieldname) and row.get(field)
			)
			frappe.db.set_value(
				doctype,
				row.name,
				fieldname,
				json.dumps(sorted(users), ensure_ascii=False),
				update_modified=False,
			)


def sync_procurement_document_participants(doc, method=None):
	sync_procurement_participants_for_reference(doc.doctype, doc.name, additional_user=doc.owner)


def sync_procurement_completion_status(source_name, receipt_summary=None):
	"""Propagate the current procurement stage to its PO and MR chain."""
	if not source_name or not frappe.db.exists(CONSOLIDATED_PURCHASE_ORDER_DOCTYPE, source_name):
		return

	from erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order import (
		_get_invoice_receipt_summary,
	)

	receipt_summary = receipt_summary or _get_invoice_receipt_summary(source_name)
	consolidated = frappe.db.get_value(
		CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
		source_name,
		["docstatus", "workflow_state", "items_already_purchased"],
		as_dict=True,
	)
	terminal = consolidated.docstatus == 2 or consolidated.workflow_state == "Відхилено"
	externally_paid = bool(consolidated.items_already_purchased and consolidated.docstatus == 1)
	all_payments_verified = bool(
		receipt_summary["payment_invoice_count"]
		and receipt_summary["payment_receipt_count"] >= receipt_summary["payment_invoice_count"]
	)
	all_payments_submitted = bool(
		receipt_summary["payment_invoice_count"]
		and receipt_summary.get("payment_complete_count", 0)
		>= receipt_summary["payment_invoice_count"]
	)
	purchase_receipt_complete = bool(receipt_summary.get("purchase_receipt_complete"))
	consolidated_status = _get_consolidated_procurement_status(
		consolidated,
		terminal=terminal,
		payment_complete=externally_paid or all_payments_submitted,
		fiscal_receipt_complete=externally_paid or all_payments_verified,
		purchase_receipt_complete=purchase_receipt_complete,
	)
	_set_procurement_status(
		CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
		source_name,
		consolidated_status,
	)
	if terminal:
		_notify_procurement_initiators(source_name, "cancelled")
	elif consolidated_status == PROCUREMENT_COMPLETED:
		_notify_procurement_initiators(source_name, "completed")

	orders = frappe.get_all(
		PURCHASE_ORDER_DOCTYPE,
		filters={"custom_consolidated_purchase_order": source_name},
		fields=["name", "docstatus"],
	)
	for order in orders:
		order_summary = receipt_summary.get("by_order", {}).get(order.name, {})
		if order.docstatus == 2 or terminal:
			order_status = PROCUREMENT_COMPLETED
		elif consolidated.docstatus != 1:
			order_status = consolidated_status
		elif order_summary.get("purchase_receipt_complete") and (
			externally_paid or order_summary.get("fully_completed")
		):
			order_status = PROCUREMENT_COMPLETED
		elif externally_paid or order_summary.get("payment_complete"):
			order_status = PROCUREMENT_AWAITING_RECEIPT
		else:
			order_status = PROCUREMENT_AWAITING_PAYMENT
		_set_procurement_status(PURCHASE_ORDER_DOCTYPE, order.name, order_status)
		_apply_purchase_order_assignment_rule(order.name)

	material_requests = set(
		frappe.get_all(
			"Consolidated Purchase Order Item",
			filters={"parent": source_name, "material_request": ["is", "set"]},
			pluck="material_request",
		)
	)
	direct_request = frappe.db.get_value(
		CONSOLIDATED_PURCHASE_ORDER_DOCTYPE, source_name, "material_request"
	)
	if direct_request:
		material_requests.add(direct_request)
	for material_request in material_requests:
		_sync_material_request_completion(material_request)


def sync_procurement_document_completion(doc, method=None):
	if doc.doctype == CONSOLIDATED_PURCHASE_ORDER_DOCTYPE:
		from erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order import (
			sync_consolidated_purchase_order_progress,
		)

		sync_consolidated_purchase_order_progress(doc.name)
	elif doc.doctype == MATERIAL_REQUEST_DOCTYPE:
		_sync_material_request_completion(doc.name)


def _sync_material_request_completion(material_request):
	if not frappe.db.exists(MATERIAL_REQUEST_DOCTYPE, material_request):
		return
	request = frappe.db.get_value(
		MATERIAL_REQUEST_DOCTYPE, material_request, ["docstatus", "status"], as_dict=True
	)
	if request.docstatus == 2 or request.status == "Stopped":
		_set_procurement_status(MATERIAL_REQUEST_DOCTYPE, material_request, PROCUREMENT_COMPLETED)
		return

	consolidated_names = set(
		frappe.get_all(
			"Consolidated Purchase Order Item",
			filters={"material_request": material_request},
			pluck="parent",
		)
	)
	consolidated_names.update(
		frappe.get_all(
			CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
			filters={"material_request": material_request},
			pluck="name",
		)
	)
	if not consolidated_names:
		_set_procurement_status(MATERIAL_REQUEST_DOCTYPE, material_request, PROCUREMENT_PREPARATION)
		return

	consolidated_rows = frappe.get_all(
		CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
		filters={"name": ["in", list(consolidated_names)]},
		fields=["docstatus", "workflow_state", COMPLETION_FIELDS[CONSOLIDATED_PURCHASE_ORDER_DOCTYPE]],
	)
	statuses = []
	for row in consolidated_rows:
		if row.docstatus == 2 or row.workflow_state == "Відхилено":
			statuses.append(PROCUREMENT_COMPLETED)
		else:
			statuses.append(row.get(COMPLETION_FIELDS[CONSOLIDATED_PURCHASE_ORDER_DOCTYPE]))
	status = min(
		(status for status in statuses if status in PROCUREMENT_STATUS_PRIORITY),
		key=PROCUREMENT_STATUS_PRIORITY.get,
		default=PROCUREMENT_PREPARATION,
	)
	_set_procurement_status(MATERIAL_REQUEST_DOCTYPE, material_request, status)


def _get_consolidated_procurement_status(
	consolidated, *, terminal, payment_complete, fiscal_receipt_complete, purchase_receipt_complete
):
	if terminal or (fiscal_receipt_complete and purchase_receipt_complete):
		return PROCUREMENT_COMPLETED
	if consolidated.docstatus != 1:
		if consolidated.workflow_state in {"Чернетка", "Потребує доопрацювання"}:
			return PROCUREMENT_PREPARATION
		return PROCUREMENT_APPROVAL
	if payment_complete:
		return PROCUREMENT_AWAITING_RECEIPT
	return PROCUREMENT_AWAITING_PAYMENT


def _apply_purchase_order_assignment_rule(purchase_order):
	from erpnext.buying.procurement_workflow import WAREHOUSE_ASSIGNMENT_RULE_NAME

	if not frappe.db.exists("Assignment Rule", WAREHOUSE_ASSIGNMENT_RULE_NAME):
		return
	rule = frappe.get_doc("Assignment Rule", WAREHOUSE_ASSIGNMENT_RULE_NAME)
	status = frappe.db.get_value(
		PURCHASE_ORDER_DOCTYPE, purchase_order, COMPLETION_FIELDS[PURCHASE_ORDER_DOCTYPE]
	)
	filters = {
		"reference_type": PURCHASE_ORDER_DOCTYPE,
		"reference_name": purchase_order,
		"assignment_rule": WAREHOUSE_ASSIGNMENT_RULE_NAME,
		"status": "Open",
	}
	if status != PROCUREMENT_AWAITING_RECEIPT:
		_close_assignments_silently(PURCHASE_ORDER_DOCTYPE, purchase_order, filters=filters)
		return
	if frappe.db.exists("ToDo", filters):
		return

	order = frappe.get_doc(PURCHASE_ORDER_DOCTYPE, purchase_order)
	user = rule.get_user(order.as_dict())
	if not user or not frappe.db.get_value("User", user, "enabled"):
		return
	add_assignment(
		{
			"assign_to": [user],
			"doctype": PURCHASE_ORDER_DOCTYPE,
			"name": purchase_order,
			"description": frappe.render_template(rule.description, order.as_dict()),
			"assignment_rule": rule.name,
			"date": order.get(rule.due_date_based_on) if rule.due_date_based_on else None,
		},
		ignore_permissions=True,
	)
	rule.db_set("last_user", user)


def _close_assignments_silently(doctype, name, filters=None):
	filters = filters or {
		"reference_type": doctype,
		"reference_name": name,
		"status": "Open",
	}
	for todo_name in frappe.get_all("ToDo", filters=filters, pluck="name"):
		todo = frappe.get_doc("ToDo", todo_name)
		todo.status = "Closed"
		todo.save(ignore_permissions=True)


def _notify_procurement_initiators(source_name, outcome):
	users = _get_procurement_initiators(source_name)
	if not users:
		return

	if outcome == "cancelled":
		subject = f"Замовлення {source_name} скасовано"
		description = "Ваше замовлення на закупівлю було скасовано."
	else:
		subject = f"Замовлення {source_name} завершено"
		description = "Ваше замовлення на закупівлю виконано та завершено."
	enqueue_create_notification(
		users,
		{
			"type": "Alert",
			"document_type": CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
			"document_name": source_name,
			"from_user": frappe.session.user,
			"subject": subject,
			"email_content": description,
		},
		dedupe_on=["document_type", "document_name", "subject"],
	)


def _get_procurement_initiators(source_name):
	chain = _get_procurement_chain(CONSOLIDATED_PURCHASE_ORDER_DOCTYPE, source_name)
	users = set()
	request_names = chain[MATERIAL_REQUEST_DOCTYPE]
	if request_names:
		for row in frappe.get_all(
			MATERIAL_REQUEST_DOCTYPE,
			filters={"name": ["in", list(request_names)]},
			fields=["owner", "custom_procurement_initiator_user"],
		):
			users.add(row.custom_procurement_initiator_user or row.owner)
	if not users:
		users.add(
			frappe.db.get_value(CONSOLIDATED_PURCHASE_ORDER_DOCTYPE, source_name, "initiator_user")
		)
	return sorted(user for user in users if user and user not in {"Administrator", "Guest"})


def _get_primary_procurement_initiator(source_name):
	users = _get_procurement_initiators(source_name)
	return users[0] if users else None


def _set_procurement_status(doctype, name, status):
	fieldname = COMPLETION_FIELDS[doctype]
	if frappe.db.has_column(doctype, fieldname):
		frappe.db.set_value(
			doctype,
			name,
			fieldname,
			status,
			update_modified=False,
		)


def _get_procurement_chain(reference_type, reference_name):
	chain = {doctype: set() for doctype in PROCUREMENT_DOCTYPES}
	chain[reference_type].add(reference_name)
	consolidated_names = set()

	if reference_type == CONSOLIDATED_PURCHASE_ORDER_DOCTYPE:
		consolidated_names.add(reference_name)
	elif reference_type == PURCHASE_ORDER_DOCTYPE:
		consolidated = frappe.db.get_value(
			PURCHASE_ORDER_DOCTYPE, reference_name, "custom_consolidated_purchase_order"
		)
		if consolidated:
			consolidated_names.add(consolidated)
		chain[MATERIAL_REQUEST_DOCTYPE].update(
			frappe.get_all(
				"Purchase Order Item",
				filters={"parent": reference_name, "material_request": ["is", "set"]},
				pluck="material_request",
			)
		)
	else:
		consolidated_names.update(
			frappe.get_all(
				"Consolidated Purchase Order Item",
				filters={"material_request": reference_name},
				pluck="parent",
			)
		)
		consolidated_names.update(
			frappe.get_all(
				CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
				filters={"material_request": reference_name},
				pluck="name",
			)
		)

	chain[CONSOLIDATED_PURCHASE_ORDER_DOCTYPE].update(consolidated_names)
	if consolidated_names:
		chain[PURCHASE_ORDER_DOCTYPE].update(
			frappe.get_all(
				PURCHASE_ORDER_DOCTYPE,
				filters={"custom_consolidated_purchase_order": ["in", list(consolidated_names)]},
				pluck="name",
			)
		)
		chain[MATERIAL_REQUEST_DOCTYPE].update(
			frappe.get_all(
				"Consolidated Purchase Order Item",
				filters={"parent": ["in", list(consolidated_names)], "material_request": ["is", "set"]},
				pluck="material_request",
			)
		)
		chain[MATERIAL_REQUEST_DOCTYPE].update(
			frappe.get_all(
				CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
				filters={"name": ["in", list(consolidated_names)], "material_request": ["is", "set"]},
				pluck="material_request",
			)
		)
	return chain


def _parse_participants(value):
	if not value:
		return []
	try:
		parsed = json.loads(value)
		return parsed if isinstance(parsed, list) else []
	except (TypeError, ValueError):
		return []


def _current_actor():
	return frappe.get_cached_value("User", frappe.session.user, "full_name") or frappe.session.user


def _make_consolidated_order(mapped_order, source_name):
	source_request = frappe.get_doc(MATERIAL_REQUEST_DOCTYPE, source_name)
	consolidated = frappe.new_doc(CONSOLIDATED_PURCHASE_ORDER_DOCTYPE)
	consolidated.company = mapped_order.company
	consolidated.transaction_date = mapped_order.transaction_date or nowdate()
	consolidated.currency = (
		frappe.get_cached_value("Company", mapped_order.company, "default_currency")
		if mapped_order.company
		else None
	)
	consolidated.set_supplier = mapped_order.supplier
	material_requests = {row.material_request for row in mapped_order.items if row.material_request}
	consolidated.material_request = next(iter(material_requests)) if len(material_requests) == 1 else None
	consolidated.items_already_purchased = source_request.get("custom_items_already_purchased") or 0
	if consolidated.items_already_purchased:
		consolidated.prepaid_purchase_note = _(PREPAID_PURCHASE_NOTE)

	for row in mapped_order.items:
		default_supplier = frappe.db.get_value(
			"Item Default",
			{"parent": row.item_code, "company": mapped_order.company},
			"default_supplier",
		)
		consolidated.append(
			"items",
			{
				"supplier": mapped_order.supplier or default_supplier,
				"item_code": row.item_code,
				"item_name": row.item_name,
				"description": row.description,
				"qty": row.qty,
				"uom": row.uom,
				"rate": row.base_rate or row.rate,
				"amount": (row.base_rate or row.rate) * row.qty,
				"schedule_date": row.schedule_date or mapped_order.schedule_date or nowdate(),
				"warehouse": row.warehouse,
				"project": row.project,
				"material_request": row.material_request,
				"material_request_item": row.material_request_item,
			},
		)

	if consolidated.items_already_purchased:
		for receipt in source_request.get("custom_purchase_receipts") or []:
			consolidated.append(
				"supplier_invoices",
				{
					"invoice_document": receipt.invoice_document or _get_file_name(receipt.invoice_pdf),
					"invoice_pdf": receipt.invoice_pdf,
				},
			)

	return consolidated


def _get_file_name(file_url):
	if not file_url:
		return None
	return unquote(urlsplit(file_url).path.rsplit("/", 1)[-1])
