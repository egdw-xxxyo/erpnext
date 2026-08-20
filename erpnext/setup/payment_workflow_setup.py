import json

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

PAYMENTS_CUSTOM_FIELDS = {
	"Payment Request": [
		{
			"fieldname": "custom_task",
			"fieldtype": "Link",
			"label": "Task",
			"options": "Task",
			"read_only": 1,
			"in_standard_filter": 1,
			"insert_after": "reference_name",
		},
		{
			"fieldname": "custom_short_description",
			"fieldtype": "Data",
			"label": "Short Description",
			"length": 255,
			"insert_after": "custom_task",
		},
		{
			"fieldname": "custom_procurement_approved",
			"fieldtype": "Check",
			"label": "Procurement Approval Confirmed",
			"default": "0",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "custom_short_description",
		},
		{
			"fieldname": "custom_payments_approval_section",
			"fieldtype": "Section Break",
			"label": "Payment Approval Details",
			"insert_after": "custom_procurement_approved",
		},
		{
			"fieldname": "custom_department",
			"fieldtype": "Link",
			"label": "Department",
			"options": "Department",
			"insert_after": "custom_payments_approval_section",
			"in_standard_filter": 1,
		},
		{
			"fieldname": "custom_initiator_user",
			"fieldtype": "Link",
			"label": "Initiator User",
			"options": "User",
			"default": "__user",
			"read_only": 1,
			"insert_after": "custom_department",
		},
		{
			"fieldname": "custom_initiator_employee",
			"fieldtype": "Link",
			"label": "Initiator Employee",
			"options": "Employee",
			"read_only": 1,
			"ignore_user_permissions": 1,
			"insert_after": "custom_initiator_user",
		},
		{
			"fieldname": "custom_payments_approval_column",
			"fieldtype": "Column Break",
			"insert_after": "custom_initiator_employee",
		},
		{
			"fieldname": "custom_payment_purpose",
			"fieldtype": "Small Text",
			"label": "Payment Purpose",
			"insert_after": "custom_payments_approval_column",
		},
		{
			"fieldname": "custom_priority",
			"fieldtype": "Select",
			"label": "Priority",
			"options": "Звичайний\nТерміновий",
			"default": "Звичайний",
			"insert_after": "custom_payment_purpose",
			"in_standard_filter": 1,
		},
		{
			"fieldname": "custom_requested_payment_date",
			"fieldtype": "Date",
			"label": "Requested Payment Date",
			"insert_after": "custom_priority",
		},
		{
			"fieldname": "custom_planned_payment_date",
			"fieldtype": "Date",
			"label": "Planned Payment Date",
			"insert_after": "custom_requested_payment_date",
		},
		{
			"fieldname": "custom_workflow_action_reason",
			"fieldtype": "Small Text",
			"label": "Workflow Action Reason",
			"hidden": 1,
			"no_copy": 1,
			"insert_after": "custom_planned_payment_date",
		},
		{
			"fieldname": "custom_fiscal_receipt_status",
			"fieldtype": "Select",
			"label": "Fiscal Receipt",
			"options": "\nДодано\nВідсутній\nЧастково",
			"read_only": 1,
			"no_copy": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
			"depends_on": "eval:doc.status == 'Paid'",
			"insert_after": "custom_workflow_action_reason",
		},
	],
	"Payment Entry": [
		{
			"fieldname": "custom_fiscal_receipt_section",
			"fieldtype": "Section Break",
			"label": "Fiscal Receipt",
			"insert_after": "reference_date",
		},
		{
			"fieldname": "custom_fiscal_receipt",
			"fieldtype": "Attach",
			"label": "Fiscal Receipt (File)",
			"allow_on_submit": 1,
			"no_copy": 1,
			"insert_after": "custom_fiscal_receipt_section",
		},
		{
			"fieldname": "custom_fiscal_receipt_status",
			"fieldtype": "Select",
			"label": "Fiscal Receipt Availability",
			"options": "Відсутній\nДодано",
			"default": "Відсутній",
			"read_only": 1,
			"allow_on_submit": 1,
			"no_copy": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
			"insert_after": "custom_fiscal_receipt",
		},
	],
	"Purchase Invoice": [
		{
			"fieldname": "custom_task",
			"fieldtype": "Link",
			"label": "Task",
			"options": "Task",
			"in_standard_filter": 1,
			"insert_after": "project",
		},
	],
	"Material Request": [
		{
			"fieldname": "custom_task",
			"fieldtype": "Link",
			"label": "Task",
			"options": "Task",
			"in_standard_filter": 1,
			"insert_after": "material_request_type",
		},
	],
	"Task": [
		{
			"fieldname": "custom_payments_section",
			"fieldtype": "Section Break",
			"label": "Task Payments",
			"insert_after": "total_billing_amount",
		},
		{
			"fieldname": "custom_payment_request_count",
			"fieldtype": "Int",
			"label": "Payment Request Count",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "custom_payments_section",
		},
		{
			"fieldname": "custom_payment_request_total",
			"fieldtype": "Currency",
			"label": "Payment Request Expenses",
			"options": "custom_payment_currency",
			"read_only": 1,
			"no_copy": 1,
			"in_list_view": 1,
			"insert_after": "custom_payment_request_count",
		},
		{
			"fieldname": "custom_payment_summary_column",
			"fieldtype": "Column Break",
			"insert_after": "custom_payment_request_total",
		},
		{
			"fieldname": "custom_payment_status",
			"fieldtype": "Select",
			"label": "Payment Status",
			"options": "Немає запитів на оплату\nЄ неоплачені запити\nОплачено",
			"default": "Немає запитів на оплату",
			"read_only": 1,
			"no_copy": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
			"insert_after": "custom_payment_summary_column",
		},
		{
			"fieldname": "custom_payment_currency",
			"fieldtype": "Link",
			"label": "Expense Currency",
			"options": "Currency",
			"read_only": 1,
			"no_copy": 1,
			"hidden": 1,
			"insert_after": "custom_payment_status",
		},
		{
			"fieldname": "custom_payment_requests_section",
			"fieldtype": "Section Break",
			"insert_after": "custom_payment_currency",
		},
		{
			"fieldname": "custom_payment_requests_html",
			"fieldtype": "HTML",
			"label": "Payment Requests",
			"insert_after": "custom_payment_requests_section",
		},
		{
			"fieldname": "custom_material_requests_section",
			"fieldtype": "Section Break",
			"insert_after": "custom_payment_requests_html",
		},
		{
			"fieldname": "custom_material_requests_html",
			"fieldtype": "HTML",
			"label": "Material Requests",
			"insert_after": "custom_material_requests_section",
		},
	],
	"Task Depends On": [
		{
			"fieldname": "custom_payment_request_total",
			"fieldtype": "Currency",
			"label": "Expenses",
			"read_only": 1,
			"no_copy": 1,
			"in_list_view": 1,
			"insert_after": "subject",
		},
		{
			"fieldname": "custom_payment_status",
			"fieldtype": "Select",
			"label": "Payment Status",
			"options": "Немає запитів на оплату\nЄ неоплачені запити\nОплачено",
			"default": "Немає запитів на оплату",
			"read_only": 1,
			"no_copy": 1,
			"in_list_view": 1,
			"insert_after": "custom_payment_request_total",
		},
	],
}

PAYMENTS_ROLES = (
	"Payments: Ініціатор",
	"Payments: Керівник підрозділу",
	"Payments: Фінальний погоджувач",
	"Payments: Казначей",
	"Payments: Аудитор",
)


def before_migrate():
	"""Remove legacy Custom Field rows before the same fields are loaded from core DocType JSON."""
	for doctype, fields in PAYMENTS_CUSTOM_FIELDS.items():
		for field in fields:
			frappe.db.delete(
				"Custom Field",
				{"dt": doctype, "fieldname": field["fieldname"]},
			)


def after_migrate():
	_ensure_roles()
	sync_payment_request_list_fields()
	sync_payment_entry_list_fields()
	sync_todo_list_fields()

	from erpnext.accounts.payment_workflow import sync_workflow_configuration

	sync_workflow_configuration()

	from erpnext.accounts.payment_workflow_automation import sync_automation_configuration

	sync_automation_configuration()

	from erpnext.accounts.payment_workflow_reason import sync_workflow_reason_configuration

	sync_workflow_reason_configuration()

	from erpnext.accounts.payment_fiscal_receipt import sync_fiscal_receipt_configuration

	sync_fiscal_receipt_configuration()

	from erpnext.projects.task_payments import sync_task_payment_configuration

	sync_task_payment_configuration()


def smoke_test():
	"""Return a read-only migration health summary for deploy verification."""
	legacy_custom_fields = []
	for doctype, fields in PAYMENTS_CUSTOM_FIELDS.items():
		legacy_custom_fields.extend(
			frappe.get_all(
				"Custom Field",
				filters={
					"dt": doctype,
					"fieldname": ["in", [field["fieldname"] for field in fields]],
				},
				pluck="name",
			)
		)

	return {
		"legacy_custom_fields": legacy_custom_fields,
		"payment_requests": frappe.db.count("Payment Request"),
		"tasks": frappe.db.count("Task"),
		"workflow": frappe.db.exists("Workflow", "Payments: погодження запиту на оплату"),
		"core_task_field": bool(frappe.get_meta("Task").get_field("custom_payment_status")),
		"core_receipt_field": bool(frappe.get_meta("Payment Entry").get_field("custom_fiscal_receipt")),
	}


def _ensure_roles():
	for role_name in PAYMENTS_ROLES:
		if frappe.db.exists("Role", role_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 1,
				"is_custom": 1,
			}
		).insert(ignore_permissions=True)


def sync_payment_request_list_fields():
	"""Show the workflow stage alongside Payment Request's standard payment status."""
	_ensure_property_setter(
		fieldname="workflow_state",
		property_name="label",
		value="Approval Stage",
		property_type="Data",
	)
	_ensure_property_setter(
		fieldname="workflow_state",
		property_name="in_list_view",
		value="1",
		property_type="Check",
	)


def sync_payment_entry_list_fields():
	"""Keep the fiscal receipt status visible in the standard Payment Entry list."""
	fields = [
		{"fieldname": "title", "label": "Title"},
		{"fieldname": "status_field", "label": "Status", "type": "Status"},
		{"fieldname": "payment_type", "label": "Payment Type"},
		{"fieldname": "posting_date", "label": "Posting Date"},
		{"fieldname": "mode_of_payment", "label": "Mode of Payment"},
		{"fieldname": "name", "label": "ID"},
		{
			"fieldname": "custom_fiscal_receipt_status",
			"label": "Fiscal Receipt Availability",
		},
	]

	if frappe.db.exists("List View Settings", "Payment Entry"):
		doc = frappe.get_doc("List View Settings", "Payment Entry")
	else:
		doc = frappe.new_doc("List View Settings")
		doc.name = "Payment Entry"

	doc.fields = json.dumps(fields)
	doc.total_fields = "8"
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)


def sync_todo_list_fields():
	"""Show the assigned document directly in the standard ToDo list."""
	_ensure_property_setter(
		fieldname="reference_name",
		property_name="label",
		value="Document",
		property_type="Data",
		doc_type="ToDo",
	)
	_ensure_property_setter(
		fieldname="reference_name",
		property_name="in_list_view",
		value="1",
		property_type="Check",
		doc_type="ToDo",
	)


def _ensure_property_setter(
	fieldname,
	property_name,
	value,
	property_type,
	doc_type="Payment Request",
):
	filters = {
		"doc_type": doc_type,
		"field_name": fieldname,
		"property": property_name,
	}
	name = frappe.db.exists("Property Setter", filters)
	if name:
		doc = frappe.get_doc("Property Setter", name)
		doc.value = value
		doc.property_type = property_type
		doc.is_system_generated = 1
		doc.save(ignore_permissions=True)
		return

	make_property_setter(
		doc_type,
		fieldname,
		property_name,
		value,
		property_type,
	)
