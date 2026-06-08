import frappe


def _status_from_qi(qi_status: str) -> str | None:
	if qi_status == "Accepted":
		return "Pass"
	if qi_status == "Rejected":
		return "Fail"
	return None


def sync_inspection_status_on_submit(doc, method=None):
	serial = (doc.item_serial_no or "").strip()
	if not serial:
		return
	new_status = _status_from_qi(doc.status)
	if not new_status:
		return
	if not frappe.db.exists("Serial No", serial):
		return
	frappe.db.set_value("Serial No", serial, "inspection_status", new_status)


def clear_inspection_status_on_cancel(doc, method=None):
	serial = (doc.item_serial_no or "").strip()
	if not serial:
		return
	if not frappe.db.exists("Serial No", serial):
		return
	other = frappe.db.get_value(
		"Quality Inspection",
		{
			"item_serial_no": serial,
			"docstatus": 1,
			"name": ("!=", doc.name),
		},
		["name", "status"],
		order_by="creation desc",
		as_dict=True,
	)
	new_status = _status_from_qi(other.status) if other else ""
	frappe.db.set_value("Serial No", serial, "inspection_status", new_status or None)
