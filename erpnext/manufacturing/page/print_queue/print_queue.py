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
def get_queue(printer_name=None, status=None):
	filters = {}
	if printer_name:
		filters["label_printer"] = printer_name
	if status and status != "All":
		filters["status"] = status

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
def get_label_sizes():
	return frappe.get_all("Label Size", fields=["name", "label_size_name", "width_mm", "height_mm"])
