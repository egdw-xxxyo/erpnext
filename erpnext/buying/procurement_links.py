import frappe


@frappe.whitelist()
def get_procurement_links(source_name: str):
	"""Traverse document references, then filter every displayed group by read permissions."""
	doc = frappe.get_doc("Consolidated Purchase Order", source_name)
	doc.check_permission("read")
	material_requests = {row.material_request for row in doc.items if row.material_request}
	if doc.material_request:
		material_requests.add(doc.material_request)
	orders = set(
		frappe.get_all(
			"Purchase Order", filters={"custom_consolidated_purchase_order": doc.name}, pluck="name"
		)
	)
	invoices = set(
		frappe.get_all(
			"Purchase Invoice", filters={"custom_consolidated_purchase_order": doc.name}, pluck="name"
		)
	)
	invoices.update(_parents("Purchase Invoice Item", "purchase_order", orders, "Purchase Invoice"))
	receipts = _parents("Purchase Receipt Item", "purchase_order", orders, "Purchase Receipt")
	receipts.update(
		_parents(
			"Purchase Invoice Item", "parent", invoices, "Purchase Invoice", value_field="purchase_receipt"
		)
	)
	requests = set()
	for doctype, names in (("Purchase Order", orders), ("Purchase Invoice", invoices)):
		if names:
			requests.update(
				frappe.get_all(
					"Payment Request",
					filters={"reference_doctype": doctype, "reference_name": ["in", sorted(names)]},
					pluck="name",
				)
			)
	payments = set()
	for doctype, names in (("Purchase Order", orders), ("Purchase Invoice", invoices)):
		if names:
			payments.update(
				frappe.get_all(
					"Payment Entry Reference",
					filters={
						"parenttype": "Payment Entry",
						"reference_doctype": doctype,
						"reference_name": ["in", sorted(names)],
					},
					pluck="parent",
				)
			)
	payments.update(_parents("Payment Entry Reference", "payment_request", requests, "Payment Entry"))
	groups = (
		("Material Request", material_requests),
		("Purchase Order", orders),
		("Purchase Invoice", invoices),
		("Payment Request", requests),
		("Payment Entry", payments),
		("Purchase Receipt", receipts),
	)
	return [
		{"doctype": doctype, "documents": _visible_documents(doctype, names)} for doctype, names in groups
	]


def _parents(child_doctype, fieldname, names, parenttype, value_field="parent"):
	if not names:
		return set()
	return {
		name
		for name in frappe.get_all(
			child_doctype,
			filters={"parenttype": parenttype, fieldname: ["in", sorted(names)]},
			pluck=value_field,
		)
		if name
	}


def _visible_documents(doctype, names):
	if not names or not frappe.has_permission(doctype, "read"):
		return []
	return frappe.get_list(
		doctype,
		filters={"name": ["in", sorted(names)]},
		fields=["name", "docstatus"],
		order_by="creation asc",
		limit_page_length=0,
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_final_approver_users(
	doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: str | dict | None
):
	from erpnext.buying.procurement_final_approval import FINAL_APPROVER_ROLE

	if not frappe.has_permission("Buying Settings", "write"):
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)
	users = frappe.get_all(
		"Has Role", filters={"parenttype": "User", "role": FINAL_APPROVER_ROLE}, pluck="parent"
	)
	if not users:
		return []
	return frappe.get_list(
		"User",
		filters={"name": ["in", users], "enabled": 1},
		or_filters={"name": ["like", f"%{txt}%"], "full_name": ["like", f"%{txt}%"]},
		fields=["name", "full_name"],
		start=start,
		page_length=page_len,
		as_list=True,
	)
