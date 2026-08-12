import frappe
from frappe import _
from frappe.desk.form.assign_to import close_all_assignments
from frappe.utils import escape_html, get_link_to_form

from erpnext.buying.procurement_workflow import BUYER_ROLE

PURCHASE_ORDER_DOCTYPE = "Purchase Order"
MATERIAL_REQUEST_DOCTYPE = "Material Request"


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

	return core_make(source_name, target_doc, args)


@frappe.whitelist()
def make_purchase_order_based_on_supplier(source_name, target_doc=None, args=None):
	require_buyer_role()
	from erpnext.stock.doctype.material_request.material_request import (
		make_purchase_order_based_on_supplier as core_make,
	)

	return core_make(source_name, target_doc, args)


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
	if todo.reference_type != PURCHASE_ORDER_DOCTYPE or not todo.reference_name:
		return

	rows = frappe.get_all(
		"ToDo",
		filters={
			"reference_type": PURCHASE_ORDER_DOCTYPE,
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

	if frappe.db.exists(PURCHASE_ORDER_DOCTYPE, todo.reference_name):
		frappe.db.set_value(
			PURCHASE_ORDER_DOCTYPE,
			todo.reference_name,
			"custom_current_assignees",
			", ".join(full_names),
			update_modified=False,
		)


def _current_actor():
	return frappe.get_cached_value("User", frappe.session.user, "full_name") or frappe.session.user
