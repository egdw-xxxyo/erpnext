import frappe


@frappe.whitelist()
def get_printers():
	return frappe.get_all(
		"Label Printer",
		filters={"is_enabled": 1},
		fields=[
			"name", "printer_name", "printer_model", "ip_address",
			"loaded_label_size", "is_label_change_in_progress",
			"label_change_message", "pending_label_size", "last_status",
		],
	)


@frappe.whitelist()
def get_queue(printer_name=None, status=None, label_template=None, created_by_user=None):
	filters = {}
	if printer_name:
		filters["label_printer"] = printer_name
	if status and status != "All":
		filters["status"] = status
	if label_template:
		filters["label_template"] = label_template
	if created_by_user:
		filters["created_by_user"] = created_by_user

	return frappe.get_all(
		"Print Job",
		filters=filters,
		fields=[
			"name", "label_template", "label_printer", "label_size",
			"reference_doctype", "reference_name", "status", "copies",
			"created_by_user", "creation", "printed_at", "error_message",
		],
		order_by="creation desc",
		limit=100,
	)


@frappe.whitelist()
def get_filter_options(printer_name=None):
	filters = {}
	if printer_name:
		filters["label_printer"] = printer_name

	templates = frappe.get_all(
		"Print Job",
		filters=filters,
		fields=["label_template"],
		distinct=True,
		order_by="label_template asc",
	)

	users = frappe.get_all(
		"Print Job",
		filters=filters,
		fields=["created_by_user"],
		distinct=True,
		order_by="created_by_user asc",
	)

	return {
		"templates": [t.label_template for t in templates if t.label_template],
		"users": [u.created_by_user for u in users if u.created_by_user],
	}


@frappe.whitelist()
def get_label_sizes():
	return frappe.get_all("Label Size", fields=["name", "label_size_name", "width_mm", "height_mm"])


@frappe.whitelist()
def resolve_scan(doctype, value):
	if not doctype or not value:
		return None

	from erpnext.stock.utils import _get_keyboard_layout_variants

	for candidate in _get_keyboard_layout_variants(value):
		result = _resolve_scan_single(doctype, candidate)
		if result:
			return result

	return None


def _resolve_scan_single(doctype, value):
	if frappe.db.exists(doctype, value):
		return value

	meta = frappe.get_meta(doctype)
	if meta.has_field("serial_no"):
		results = frappe.get_all(
			doctype,
			filters={"serial_no": value},
			fields=["name"],
			limit=1,
		)
		if results:
			return results[0].name

	if meta.has_field("barcode"):
		results = frappe.get_all(
			doctype,
			filters={"barcode": value},
			fields=["name"],
			limit=1,
		)
		if results:
			return results[0].name

	return None


@frappe.whitelist()
def get_template_doctypes(doctype, txt, searchfield, start, page_len, filters):
	doctypes = frappe.get_all(
		"Label Template",
		filters={"reference_doctype": ["is", "set"]},
		fields=["reference_doctype"],
		distinct=True,
	)
	names = list({d.reference_doctype for d in doctypes if d.reference_doctype})
	if txt:
		names = [n for n in names if txt.lower() in n.lower()]
	return [[n] for n in sorted(names)]
