import frappe
from frappe import _
from frappe.utils import cint

CPO = "Consolidated Purchase Order"


def can_add_delivery_note(doc):
	if doc.docstatus != 1 or doc.procurement_completion_status == "Завершено":
		return False
	roles = frappe.get_roles()
	return (
		frappe.session.user == "Administrator"
		or "Payments: Казначей" in roles
		or ("Закупівельник" in roles and frappe.session.user in (doc.owner, doc.initiator_user))
	)


@frappe.whitelist(methods=["POST"])
def add_delivery_note(name: str, supplier: str, file_url: str):
	# This endpoint permits only an append to the delivery-note table. It does not
	# grant the treasurer general write access to the procurement document.
	doc = frappe.get_doc(CPO, name, for_update=True)
	doc.check_permission("read")
	if not can_add_delivery_note(doc):
		frappe.throw(_("Not permitted to add delivery notes to this order."), frappe.PermissionError)
	uploaded_file = frappe.db.exists(
		"File", {"file_url": file_url, "owner": frappe.session.user, "attached_to_doctype": ["is", "not set"]}
	)
	file = frappe.get_doc(
		"File", uploaded_file or {"file_url": file_url, "attached_to_doctype": CPO, "attached_to_name": name}
	)
	file.check_permission("read")
	if file.attached_to_doctype and (file.attached_to_doctype != CPO or file.attached_to_name != name):
		frappe.throw(_("Upload a file for this order."), frappe.PermissionError)
	if not file.attached_to_doctype and file.owner != frappe.session.user:
		frappe.throw(_("Upload a file for this order."), frappe.PermissionError)
	if not any(row.supplier == supplier and row.delivery_note_file == file_url for row in doc.delivery_notes):
		doc.append("delivery_notes", {"supplier": supplier, "delivery_note_file": file_url})
		doc.save(ignore_permissions=True)
	file.db_set({"attached_to_doctype": CPO, "attached_to_name": name}, update_modified=False)
	return doc.name


def sync_order_details(doc, method=None):
	if doc.doctype == "Purchase Order":
		initiator = (
			frappe.db.get_value(CPO, doc.custom_consolidated_purchase_order, "request_initiator_user")
			if doc.get("custom_consolidated_purchase_order")
			else None
		)
		doc.custom_request_initiator_user = initiator
		return
	suppliers = {row.supplier for row in doc.items if row.supplier}
	attached = {row.supplier for row in doc.delivery_notes or [] if row.delivery_note_file}
	values = {
		"custom_has_delivery_note": int(bool(suppliers & attached)),
		"custom_delivery_note_supplier_count": len(suppliers & attached),
		"custom_delivery_note_supplier_total": len(suppliers),
	}
	changed = {key: value for key, value in values.items() if cint(doc.get(key)) != value}
	if changed:
		frappe.db.set_value(CPO, doc.name, changed, update_modified=False)
		for key, value in changed.items():
			doc.set(key, value)
	for order in frappe.get_all(
		"Purchase Order",
		filters={"custom_consolidated_purchase_order": doc.name},
		fields=["name", "custom_request_initiator_user"],
	):
		if order.custom_request_initiator_user != doc.request_initiator_user:
			frappe.db.set_value(
				"Purchase Order",
				order.name,
				"custom_request_initiator_user",
				doc.request_initiator_user,
				update_modified=False,
			)


def sync_supplier_vat(doc, method=None):
	supplier = (
		doc.get("supplier")
		if doc.doctype == "Purchase Invoice"
		else (doc.get("party") if doc.get("party_type") == "Supplier" else None)
	)
	if doc.doctype == "Payment Request":
		for key in ("tax_id", "edrpou"):
			doc.set(
				f"custom_party_{key}", frappe.db.get_value("Supplier", supplier, key) if supplier else None
			)
	doc.custom_supplier_is_vat_payer = cint(
		frappe.db.get_value("Supplier", supplier, "custom_is_vat_payer") if supplier else 0
	)


def backfill_order_details():
	# Database-only updates deliberately avoid saves, assignments and notifications.
	for name in frappe.get_all(CPO, pluck="name"):
		sync_order_details(frappe.get_doc(CPO, name))
	for row in frappe.get_all(
		"Purchase Order",
		fields=["name", "custom_consolidated_purchase_order", "custom_request_initiator_user"],
	):
		previous = row.custom_request_initiator_user
		row.doctype = "Purchase Order"
		sync_order_details(row)
		if previous != row.custom_request_initiator_user:
			frappe.db.set_value(
				"Purchase Order",
				row.name,
				"custom_request_initiator_user",
				row.custom_request_initiator_user,
				update_modified=False,
			)
