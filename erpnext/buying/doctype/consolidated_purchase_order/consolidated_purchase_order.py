from collections import defaultdict
from urllib.parse import unquote, urlsplit

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, escape_html, flt, get_link_to_form, nowdate

PREPAID_PURCHASE_NOTE = (
	"The materials have already been purchased. Review the attached receipts and verify suppliers and prices."
)
LOCKED_WORKFLOW_STATES = {"Перевірка підрозділу", "Фінальне погодження", "Погоджено"}


class ConsolidatedPurchaseOrder(Document):
	def validate(self):
		self._validate_locked_workflow_state()
		self._set_company_currency()
		self._set_ceo_approval_threshold()
		self._set_material_request()
		self._set_prepaid_purchase_note()
		self._apply_default_supplier()
		self._calculate_totals()
		self._validate_items()
		self._validate_supplier_invoices()
		self._validate_material_request_uniqueness()

	def _validate_locked_workflow_state(self):
		before = self.get_doc_before_save()
		if (
			frappe.session.user != "Administrator"
			and before
			and before.workflow_state in LOCKED_WORKFLOW_STATES
			and self.workflow_state == before.workflow_state
		):
			frappe.throw(
				_("The consolidated order cannot be edited while it is under approval."),
				title=_("Document is read-only"),
			)

	def _validate_material_request_uniqueness(self):
		if not self.is_new():
			return
		from erpnext.buying.procurement_automation import validate_material_requests_available

		material_requests = {row.material_request for row in self.items if row.material_request}
		validate_material_requests_available(material_requests, exclude=self.name)

	def on_submit(self):
		self.create_purchase_orders()

	def before_cancel(self):
		linked_orders = self.get_linked_purchase_orders(submitted_only=True)
		if linked_orders:
			frappe.throw(
				_("Cancel the linked Purchase Orders before cancelling this consolidated order: {0}").format(
					", ".join(linked_orders)
				)
			)

	def _set_company_currency(self):
		if self.company:
			self.currency = frappe.get_cached_value("Company", self.company, "default_currency")

	def _set_ceo_approval_threshold(self):
		from erpnext.buying.procurement_final_approval import get_approval_threshold

		self.ceo_approval_threshold = get_approval_threshold()

	def _set_material_request(self):
		material_requests = {row.material_request for row in self.items if row.material_request}
		self.material_request = next(iter(material_requests)) if len(material_requests) == 1 else None

	def _set_prepaid_purchase_note(self):
		self.prepaid_purchase_note = _(PREPAID_PURCHASE_NOTE) if self.items_already_purchased else None

	def _apply_default_supplier(self):
		if not self.set_supplier:
			return
		for row in self.items:
			if not row.supplier:
				row.supplier = self.set_supplier

	def _calculate_totals(self):
		self.total_qty = 0
		self.grand_total = 0
		for row in self.items:
			row.amount = flt(row.qty) * flt(row.rate)
			self.total_qty += flt(row.qty)
			self.grand_total += flt(row.amount)

	def _validate_items(self):
		if not self.items:
			frappe.throw(_("Add at least one item."))

		for row in self.items:
			if not row.supplier:
				frappe.throw(_("Row {0}: Supplier is required.").format(row.idx))
			if (
				row.item_code
				and frappe.get_cached_value("Item", row.item_code, "is_stock_item")
				and not row.warehouse
			):
				frappe.throw(
					_("Row #{1}: Warehouse is mandatory for stock Item {0}").format(
						frappe.bold(row.item_code), row.idx
					)
				)
			if flt(row.qty) <= 0:
				frappe.throw(_("Row {0}: Quantity must be greater than zero.").format(row.idx))
			if flt(row.rate) < 0:
				frappe.throw(_("Row {0}: Rate cannot be negative.").format(row.idx))
			if not row.schedule_date:
				frappe.throw(_("Row {0}: Required By date is required.").format(row.idx))

	def _validate_supplier_invoices(self):
		allowed_suppliers = {row.supplier for row in self.items if row.supplier}
		for row in self.supplier_invoices:
			row.invoice_document = self._get_supplier_invoice_file_name(row.invoice_pdf)
			if not row.invoice_pdf:
				frappe.throw(_("Row {0}: Attach a PDF receipt.").format(row.idx))
			if not row.supplier:
				frappe.throw(_("Row {0}: Supplier is required for the purchase receipt.").format(row.idx))
			if row.supplier not in allowed_suppliers:
				frappe.throw(
					_("Row {0}: Select a supplier used in the order items.").format(row.idx)
				)
			if row.invoice_pdf and not urlsplit(row.invoice_pdf).path.lower().endswith(".pdf"):
				frappe.throw(
					_("The supplier invoice must be a PDF file."),
					title=_("Unsupported File Format"),
				)

	@staticmethod
	def _get_supplier_invoice_file_name(file_url):
		if not file_url:
			return None
		return unquote(urlsplit(file_url).path.rsplit("/", 1)[-1])

	def create_purchase_orders(self):
		groups = defaultdict(list)
		for row in self.items:
			if not row.purchase_order:
				groups[row.supplier].append(row)

		for supplier, rows in groups.items():
			purchase_order = self._make_purchase_order(supplier, rows)
			for source_row, target_row in zip(rows, purchase_order.items, strict=True):
				frappe.db.set_value(
					source_row.doctype,
					source_row.name,
					{
						"purchase_order": purchase_order.name,
						"purchase_order_item": target_row.name,
					},
					update_modified=False,
				)
				source_row.purchase_order = purchase_order.name
				source_row.purchase_order_item = target_row.name

			order_link = get_link_to_form("Purchase Order", purchase_order.name, purchase_order.name)
			self.add_comment(
				"Info",
				text=_("Created and submitted Purchase Order {0} for supplier {1}.").format(
					order_link, escape_html(supplier)
				),
			)

		sync_consolidated_purchase_order_progress(self.name)

	def _make_purchase_order(self, supplier, rows):
		purchase_order = frappe.get_doc(
			{
				"doctype": "Purchase Order",
				"supplier": supplier,
				"company": self.company,
				"transaction_date": self.transaction_date or nowdate(),
				"schedule_date": max(row.schedule_date for row in rows),
				"currency": self.currency,
				"conversion_rate": 1,
				"custom_consolidated_purchase_order": self.name,
				"custom_items_already_purchased": self.items_already_purchased,
				"custom_prepaid_purchase_note": self.prepaid_purchase_note,
			}
		)
		for row in rows:
			purchase_order.append(
				"items",
				{
					"item_code": row.item_code,
					"item_name": row.item_name,
					"description": row.description,
					"qty": row.qty,
					"uom": row.uom,
					"schedule_date": row.schedule_date,
					"warehouse": row.warehouse,
					"rate": row.rate,
					"project": row.project,
					"material_request": row.material_request,
					"material_request_item": row.material_request_item,
					"custom_consolidated_purchase_order_item": row.name,
				},
			)

		purchase_order.flags.ignore_permissions = True
		purchase_order.insert()
		purchase_order.submit()
		return purchase_order

	def get_linked_purchase_orders(self, submitted_only=False):
		filters = {"custom_consolidated_purchase_order": self.name}
		if submitted_only:
			filters["docstatus"] = 1
		return frappe.get_all("Purchase Order", filters=filters, pluck="name")


@frappe.whitelist()
def get_purchase_invoice_options(source_name):
	doc = frappe.get_doc("Consolidated Purchase Order", source_name)
	doc.check_permission("read")
	return frappe.get_all(
		"Purchase Order",
		filters={
			"custom_consolidated_purchase_order": source_name,
			"docstatus": 1,
			"status": ["not in", ["Closed", "Cancelled"]],
			"per_billed": ["<", 100],
		},
		fields=["name", "supplier", "supplier_name", "grand_total", "currency", "per_billed"],
		order_by="supplier_name asc, name asc",
	)


@frappe.whitelist()
def get_purchase_order_summary(source_name):
	doc = frappe.get_doc("Consolidated Purchase Order", source_name)
	doc.check_permission("read")
	return _get_purchase_order_summary(source_name)


@frappe.whitelist()
def get_approval_route_summary(source_name):
	from erpnext.buying.procurement_final_approval import (
		REQUIRED_FINAL_APPROVALS,
		get_approval_threshold,
		get_configured_final_approvers,
		is_automatic_final_approval,
	)

	doc = frappe.get_doc("Consolidated Purchase Order", source_name)
	doc.check_permission("read")

	material_request_names = sorted(
		{row.material_request for row in doc.items if row.material_request}
		or ({doc.material_request} if doc.material_request else set())
	)
	material_requests = (
		frappe.get_all(
			"Material Request",
			filters={"name": ["in", material_request_names]},
			fields=["name", "owner"],
			order_by="creation asc",
		)
		if material_request_names
		else []
	)
	for request in material_requests:
		request.created_by = _get_user_summary(request.owner)

	stage_states = {
		"preparation": {"Чернетка", "Потребує доопрацювання"},
		"department_review": {"Перевірка підрозділу"},
		"final_approval": {"Фінальне погодження"},
		"posting": {"Погоджено"},
	}
	stage_actors = {}
	workflow_actions = frappe.get_all(
		"Workflow Action",
		filters={
			"reference_doctype": "Consolidated Purchase Order",
			"reference_name": source_name,
			"status": "Completed",
			"completed_by": ["is", "set"],
		},
		fields=["workflow_state", "completed_by", "modified"],
		order_by="modified asc",
	)
	for action in workflow_actions:
		for stage, states in stage_states.items():
			if action.workflow_state in states:
				stage_actors[stage] = _get_user_summary(action.completed_by)

	current_assignees = frappe.get_all(
		"ToDo",
		filters={
			"reference_type": "Consolidated Purchase Order",
			"reference_name": source_name,
			"status": "Open",
		},
		pluck="allocated_to",
		order_by="creation asc",
	)
	current_assignees = [_get_user_summary(user) for user in dict.fromkeys(current_assignees) if user]
	final_approved_users = [
		_get_user_summary(user)
		for user in (doc.final_approved_by_1, doc.final_approved_by_2)
		if user
	]
	external_payer = material_requests[0].created_by if doc.items_already_purchased and material_requests else None

	return {
		"material_requests": material_requests,
		"stage_actors": stage_actors,
		"current_assignees": current_assignees,
		"final_approval_count": cint(doc.final_approval_count),
		"final_approval_required": REQUIRED_FINAL_APPROVALS,
		"final_approved_users": final_approved_users,
		"final_approvers": [
			_get_user_summary(user) for user in get_configured_final_approvers(throw=False)
		],
		"final_approval_automatic": is_automatic_final_approval(doc),
		"final_approval_threshold": get_approval_threshold(),
		"external_payment": bool(doc.items_already_purchased),
		"external_payer": external_payer,
		**_get_invoice_receipt_summary(source_name),
	}


def sync_consolidated_purchase_order_progress(source_name):
	if not source_name or not frappe.db.exists("Consolidated Purchase Order", source_name):
		return

	rows = _get_purchase_order_summary(source_name)
	total = sum(flt(row.grand_total) for row in rows)
	billed = sum(flt(row.grand_total) * flt(row.per_billed) / 100 for row in rows)
	paid = sum(flt(row.paid_amount) for row in rows)
	receipt_summary = _get_invoice_receipt_summary(source_name)
	frappe.db.set_value(
		"Consolidated Purchase Order",
		source_name,
		{
			"per_billed": _as_percent(billed, total),
			"per_paid": _as_percent(paid, total),
			"payment_invoice_count": receipt_summary["payment_invoice_count"],
			"payment_receipt_count": receipt_summary["payment_receipt_count"],
			"payment_receipts_progress": receipt_summary["payment_receipts_progress"],
		},
		update_modified=False,
	)

	from erpnext.buying.procurement_automation import sync_procurement_completion_status

	sync_procurement_completion_status(source_name, receipt_summary)


def sync_linked_consolidated_purchase_order_progress(doc, method=None):
	source_names = set()
	if doc.doctype in ("Purchase Order", "Purchase Invoice"):
		if doc.get("custom_consolidated_purchase_order"):
			source_names.add(doc.custom_consolidated_purchase_order)
	elif doc.doctype == "Purchase Receipt":
		purchase_orders = {
			row.purchase_order for row in (doc.get("items") or []) if row.purchase_order
		}
		if purchase_orders:
			source_names.update(
				frappe.get_all(
					"Purchase Order",
					filters={"name": ["in", list(purchase_orders)]},
					pluck="custom_consolidated_purchase_order",
				)
			)
	elif doc.doctype == "Payment Entry":
		for reference in doc.get("references") or []:
			if reference.reference_doctype not in ("Purchase Order", "Purchase Invoice"):
				continue
			source_name = frappe.db.get_value(
				reference.reference_doctype,
				reference.reference_name,
				"custom_consolidated_purchase_order",
			)
			if source_name:
				source_names.add(source_name)

	for source_name in filter(None, source_names):
		sync_consolidated_purchase_order_progress(source_name)


def sync_all_consolidated_purchase_order_progress():
	if not frappe.db.table_exists("Consolidated Purchase Order"):
		return
	for source_name in frappe.get_all("Consolidated Purchase Order", pluck="name"):
		sync_consolidated_purchase_order_progress(source_name)


def _get_purchase_order_summary(source_name):
	orders = frappe.get_all(
		"Purchase Order",
		filters={
			"custom_consolidated_purchase_order": source_name,
			"docstatus": 1,
		},
		fields=[
			"name",
			"supplier",
			"supplier_name",
			"grand_total",
			"currency",
			"per_billed",
			"per_received",
			"advance_paid",
		],
		order_by="supplier_name asc, name asc",
	)
	paid_by_order = _get_paid_amounts_by_purchase_order(source_name, orders)
	receipt_summary = _get_invoice_receipt_summary(source_name, orders)
	for order in orders:
		order.paid_amount = min(
			flt(order.grand_total),
			max(flt(order.advance_paid), flt(paid_by_order.get(order.name))),
		)
		order.per_paid = _as_percent(order.paid_amount, order.grand_total)
		order_summary = receipt_summary["by_order"].get(order.name, {})
		order.payment_complete = order_summary.get("payment_complete", False)
		order.fiscal_receipt_added = order_summary.get("fiscal_receipt_added", False)
		order.purchase_receipts = order_summary.get("purchase_receipts", [])
		order.purchase_receipt_complete = order_summary.get("purchase_receipt_complete", False)
	return orders


def _get_paid_amounts_by_purchase_order(source_name, orders):
	paid_by_order = defaultdict(float)
	invoices = frappe.get_all(
		"Purchase Invoice",
		filters={"custom_consolidated_purchase_order": source_name, "docstatus": 1},
		fields=["name", "supplier", "grand_total", "outstanding_amount"],
	)
	if not invoices:
		return paid_by_order

	invoice_names = [invoice.name for invoice in invoices]
	invoice_items = frappe.get_all(
		"Purchase Invoice Item",
		filters={"parent": ["in", invoice_names], "purchase_order": ["is", "set"]},
		fields=["parent", "purchase_order", "base_net_amount"],
	)
	weights_by_invoice = defaultdict(lambda: defaultdict(float))
	for row in invoice_items:
		weights_by_invoice[row.parent][row.purchase_order] += abs(flt(row.base_net_amount))

	orders_by_supplier = defaultdict(list)
	for order in orders:
		orders_by_supplier[order.supplier].append(order.name)

	for invoice in invoices:
		paid_amount = max(0, flt(invoice.grand_total) - flt(invoice.outstanding_amount))
		weights = weights_by_invoice.get(invoice.name)
		if weights:
			total_weight = sum(weights.values())
			if total_weight:
				for purchase_order, weight in weights.items():
					paid_by_order[purchase_order] += paid_amount * weight / total_weight
				continue

		matching_orders = orders_by_supplier.get(invoice.supplier) or []
		if len(matching_orders) == 1:
			paid_by_order[matching_orders[0]] += paid_amount

	return paid_by_order


def _get_invoice_receipt_summary(source_name, orders=None):
	"""Summarize verified payments and submitted Purchase Receipts for every order."""
	external_payment = bool(
		frappe.db.get_value("Consolidated Purchase Order", source_name, "items_already_purchased")
	)
	invoices = frappe.get_all(
		"Purchase Invoice",
		filters={"custom_consolidated_purchase_order": source_name, "docstatus": 1},
		fields=["name", "supplier", "grand_total", "outstanding_amount"],
	)
	invoice_names = [invoice.name for invoice in invoices]
	payment_references = (
		frappe.get_all(
			"Payment Entry Reference",
			filters={
				"reference_doctype": "Purchase Invoice",
				"reference_name": ["in", invoice_names],
				"parenttype": "Payment Entry",
				"docstatus": 1,
			},
			fields=["parent", "reference_name"],
		)
		if invoice_names
		else []
	)
	payment_entries = set(reference.parent for reference in payment_references)
	receipt_entries = (
		frappe.get_all(
			"Payment Entry",
			filters={
				"name": ["in", list(payment_entries)],
				"docstatus": 1,
				"custom_fiscal_receipt": ["is", "set"],
			},
			fields=["name", "modified_by", "modified"],
			order_by="modified asc",
		)
		if payment_entries
		else []
	)
	receipt_entry_names = {entry.name for entry in receipt_entries}
	orders = orders or frappe.get_all(
		"Purchase Order",
		filters={"custom_consolidated_purchase_order": source_name, "docstatus": 1},
		fields=["name", "supplier", "per_billed", "per_received"],
	)
	purchase_receipts_by_order, receipt_actors = _get_purchase_receipts_by_order(orders)
	invoice_orders = _get_invoice_purchase_orders(invoices, orders)
	invoices_by_order = defaultdict(list)
	for invoice in invoices:
		for purchase_order in invoice_orders.get(invoice.name, set()):
			invoices_by_order[purchase_order].append(invoice)

	payment_entries_by_invoice = defaultdict(set)
	for reference in payment_references:
		payment_entries_by_invoice[reference.reference_name].add(reference.parent)

	by_order = {}
	created_invoice_count = 0
	payment_complete_count = 0
	completed_supplier_count = 0
	for order in orders:
		order_invoices = invoices_by_order.get(order.name, [])
		if order_invoices:
			created_invoice_count += 1
		payment_complete = external_payment or (
			bool(order_invoices)
			and flt(order.per_billed) >= 99.99
			and all(abs(flt(invoice.outstanding_amount)) <= 0.01 for invoice in order_invoices)
		)
		order_payment_entries = {
			payment_entry
			for invoice in order_invoices
			for payment_entry in payment_entries_by_invoice.get(invoice.name, set())
		}
		fiscal_receipt_added = external_payment or bool(order_payment_entries & receipt_entry_names)
		fully_completed = payment_complete and fiscal_receipt_added
		purchase_receipts = purchase_receipts_by_order.get(order.name, [])
		purchase_receipt_complete = bool(purchase_receipts) and flt(order.per_received) >= 99.99
		if payment_complete:
			payment_complete_count += 1
		if fully_completed:
			completed_supplier_count += 1
		by_order[order.name] = {
			"invoice_count": len(order_invoices),
			"payment_complete": payment_complete,
			"fiscal_receipt_added": fiscal_receipt_added,
			"fully_completed": fully_completed,
			"purchase_receipts": purchase_receipts,
			"purchase_receipt_complete": purchase_receipt_complete,
		}

	supplier_count = len(orders)
	users = list(dict.fromkeys(entry.modified_by for entry in receipt_entries if entry.modified_by))
	purchase_receipt_complete = _is_purchase_receipt_stage_complete(
		external_payment, orders, by_order
	)
	if external_payment:
		from erpnext.buying.procurement_automation import _get_primary_procurement_initiator

		initiator = _get_primary_procurement_initiator(source_name)
		if initiator:
			receipt_actors = [initiator]
	return {
		"submitted_invoice_count": len(invoices),
		"created_invoice_count": created_invoice_count,
		"payment_invoice_count": supplier_count,
		"payment_complete_count": payment_complete_count,
		"payment_receipt_count": completed_supplier_count,
		"payment_receipts_progress": _format_receipt_progress(
			completed_supplier_count, supplier_count
		),
		"payment_actors": [_get_user_summary(user) for user in users],
		"purchase_receipt_complete": purchase_receipt_complete,
		"receipt_actors": [_get_user_summary(user) for user in receipt_actors],
		"by_order": by_order,
	}


def _is_purchase_receipt_stage_complete(external_payment, orders, by_order):
	"""Prepaid materials are already physically held by their initiator."""
	return bool(external_payment) or (
		bool(orders) and all(row["purchase_receipt_complete"] for row in by_order.values())
	)


def _get_purchase_receipts_by_order(orders):
	order_names = [order.name for order in orders]
	if not order_names:
		return {}, []

	items = frappe.get_all(
		"Purchase Receipt Item",
		filters={"purchase_order": ["in", order_names], "docstatus": ["<", 2]},
		fields=["parent", "purchase_order", "warehouse"],
	)
	receipt_names = list(dict.fromkeys(row.parent for row in items))
	if not receipt_names:
		return {}, []

	receipts = frappe.get_all(
		"Purchase Receipt",
		filters={"name": ["in", receipt_names], "docstatus": ["<", 2]},
		fields=["name", "status", "docstatus", "modified_by", "modified"],
		order_by="posting_date asc, creation asc",
	)
	receipts_by_name = {receipt.name: receipt for receipt in receipts}
	by_order = defaultdict(list)
	for item in items:
		receipt = receipts_by_name.get(item.parent)
		if not receipt:
			continue
		if not any(
			row["name"] == receipt.name and row["warehouse"] == item.warehouse
			for row in by_order[item.purchase_order]
		):
			by_order[item.purchase_order].append(
				{
					"name": receipt.name,
					"status": receipt.status,
					"docstatus": receipt.docstatus,
					"warehouse": item.warehouse,
					"purchase_order": item.purchase_order,
				}
			)
	actors = list(
		dict.fromkeys(
			receipt.modified_by
			for receipt in receipts
			if receipt.docstatus == 1 and receipt.modified_by
		)
	)
	return dict(by_order), actors


def _get_invoice_purchase_orders(invoices, orders):
	invoice_names = [invoice.name for invoice in invoices]
	invoice_orders = defaultdict(set)
	if invoice_names:
		for row in frappe.get_all(
			"Purchase Invoice Item",
			filters={"parent": ["in", invoice_names], "purchase_order": ["is", "set"]},
			fields=["parent", "purchase_order"],
		):
			invoice_orders[row.parent].add(row.purchase_order)

	orders_by_supplier = defaultdict(list)
	for order in orders:
		orders_by_supplier[order.supplier].append(order.name)
	for invoice in invoices:
		if invoice_orders.get(invoice.name):
			continue
		matching_orders = orders_by_supplier.get(invoice.supplier) or []
		if len(matching_orders) == 1:
			invoice_orders[invoice.name].add(matching_orders[0])
	return invoice_orders


def _format_receipt_progress(receipt_count, invoice_count):
	return f"{receipt_count}/{invoice_count}"


def _get_user_summary(user):
	return {
		"user": user,
		"full_name": frappe.get_cached_value("User", user, "full_name") or user,
	}


def _as_percent(amount, total):
	if not flt(total):
		return 0
	return min(100, max(0, flt(amount) / flt(total) * 100))


@frappe.whitelist()
def make_purchase_invoice(source_name, supplier=None):
	supplier = supplier or (frappe.flags.args or {}).get("supplier")
	if not supplier:
		frappe.throw(_("Supplier is required for all selected Items"))

	doc = frappe.get_doc("Consolidated Purchase Order", source_name)
	doc.check_permission("read")
	if doc.docstatus != 1:
		frappe.throw(_("Submit the consolidated order before creating a Purchase Invoice."))

	purchase_order = frappe.db.get_value(
		"Purchase Order",
		{
			"custom_consolidated_purchase_order": source_name,
			"supplier": supplier,
			"docstatus": 1,
			"status": ["not in", ["Closed", "Cancelled"]],
			"per_billed": ["<", 100],
		},
		"name",
	)
	if not purchase_order:
		frappe.throw(_("No billable Purchase Order was found for supplier {0}.").format(supplier))

	from erpnext.buying.doctype.purchase_order.purchase_order import get_mapped_purchase_invoice

	invoice = get_mapped_purchase_invoice(purchase_order)
	invoice.custom_consolidated_purchase_order = source_name
	if doc.items_already_purchased:
		from erpnext.buying.procurement_automation import set_external_payment_details

		invoice.is_paid = 1
		set_external_payment_details(invoice, doc)
	return invoice
