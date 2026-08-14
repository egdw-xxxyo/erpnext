from urllib.parse import unquote, urlsplit

import frappe
from frappe import _
from frappe.desk.form.assign_to import close_all_assignments
from frappe.utils import escape_html, get_link_to_form, nowdate

from erpnext.buying.procurement_workflow import BUYER_ROLE

PURCHASE_ORDER_DOCTYPE = "Purchase Order"
CONSOLIDATED_PURCHASE_ORDER_DOCTYPE = "Consolidated Purchase Order"
MATERIAL_REQUEST_DOCTYPE = "Material Request"
PREPAID_PURCHASE_NOTE = (
	"The materials have already been purchased. Review the attached receipts and verify suppliers and prices."
)


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
	from erpnext.stock.doctype.material_request.material_request import make_purchase_order as core_make

	mapped_order = core_make(source_name, None, args)
	return _make_consolidated_order(mapped_order, source_name)


@frappe.whitelist()
def make_purchase_order_based_on_supplier(source_name, target_doc=None, args=None):
	require_buyer_role()
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


def on_purchase_order_insert(doc, method=None):
	material_requests = sorted({row.material_request for row in doc.items if row.material_request})
	if not material_requests:
		return

	actor = _current_actor()
	order_link = get_link_to_form(PURCHASE_ORDER_DOCTYPE, doc.name, escape_html(doc.name))
	for material_request in material_requests:
		close_all_assignments(MATERIAL_REQUEST_DOCTYPE, material_request, ignore_permissions=True)
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


def sync_current_assignees(todo, method=None):
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
