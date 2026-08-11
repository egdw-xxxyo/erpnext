import frappe

from frappe.custom.doctype.property_setter.property_setter import make_property_setter


PAYMENTS_CUSTOM_FIELDS = {
	"Payment Request": [
		{
			"fieldname": "custom_task",
			"fieldtype": "Link",
			"label": "Завдання",
			"options": "Task",
			"read_only": 1,
			"in_standard_filter": 1,
			"insert_after": "reference_name",
		},
		{
			"fieldname": "custom_short_description",
			"fieldtype": "Data",
			"label": "Короткий опис",
			"length": 255,
			"insert_after": "custom_task",
		},
		{
			"fieldname": "custom_payments_approval_section",
			"fieldtype": "Section Break",
			"label": "Деталі погодження платежу",
			"insert_after": "custom_short_description",
		},
		{
			"fieldname": "custom_department",
			"fieldtype": "Link",
			"label": "Підрозділ",
			"options": "Department",
			"insert_after": "custom_payments_approval_section",
			"in_standard_filter": 1,
		},
		{
			"fieldname": "custom_initiator_user",
			"fieldtype": "Link",
			"label": "Користувач-ініціатор",
			"options": "User",
			"default": "__user",
			"read_only": 1,
			"insert_after": "custom_department",
		},
		{
			"fieldname": "custom_initiator_employee",
			"fieldtype": "Link",
			"label": "Працівник-ініціатор",
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
			"label": "Призначення платежу",
			"insert_after": "custom_payments_approval_column",
		},
		{
			"fieldname": "custom_priority",
			"fieldtype": "Select",
			"label": "Пріоритет",
			"options": "Звичайний\nТерміновий",
			"default": "Звичайний",
			"insert_after": "custom_payment_purpose",
			"in_standard_filter": 1,
		},
		{
			"fieldname": "custom_requested_payment_date",
			"fieldtype": "Date",
			"label": "Бажана дата оплати",
			"insert_after": "custom_priority",
		},
		{
			"fieldname": "custom_planned_payment_date",
			"fieldtype": "Date",
			"label": "Планова дата оплати",
			"insert_after": "custom_requested_payment_date",
		},
		{
			"fieldname": "custom_workflow_action_reason",
			"fieldtype": "Small Text",
			"label": "Причина дії погодження",
			"hidden": 1,
			"no_copy": 1,
			"insert_after": "custom_planned_payment_date",
		},
		{
			"fieldname": "custom_fiscal_receipt_status",
			"fieldtype": "Select",
			"label": "Фіскальний чек",
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
			"label": "Фіскальний чек",
			"insert_after": "reference_date",
		},
		{
			"fieldname": "custom_fiscal_receipt",
			"fieldtype": "Attach",
			"label": "Фіскальний чек (файл)",
			"allow_on_submit": 1,
			"no_copy": 1,
			"insert_after": "custom_fiscal_receipt_section",
		},
		{
			"fieldname": "custom_fiscal_receipt_status",
			"fieldtype": "Select",
			"label": "Наявність фіскального чека",
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
			"label": "Завдання",
			"options": "Task",
			"in_standard_filter": 1,
			"insert_after": "project",
		},
	],
	"Material Request": [
		{
			"fieldname": "custom_task",
			"fieldtype": "Link",
			"label": "Завдання",
			"options": "Task",
			"in_standard_filter": 1,
			"insert_after": "material_request_type",
		},
	],
	"Task": [
		{
			"fieldname": "custom_payments_section",
			"fieldtype": "Section Break",
			"label": "Оплати за завданням",
			"insert_after": "total_billing_amount",
		},
		{
			"fieldname": "custom_payment_request_count",
			"fieldtype": "Int",
			"label": "Кількість запитів на оплату",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "custom_payments_section",
		},
		{
			"fieldname": "custom_payment_request_total",
			"fieldtype": "Currency",
			"label": "Витрати за запитами",
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
			"label": "Стан оплати",
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
			"label": "Валюта витрат",
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
			"label": "Запити на оплату",
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
			"label": "Замовлення матеріалів",
			"insert_after": "custom_material_requests_section",
		},
	],
	"Task Depends On": [
		{
			"fieldname": "custom_payment_request_total",
			"fieldtype": "Currency",
			"label": "Витрати",
			"read_only": 1,
			"no_copy": 1,
			"in_list_view": 1,
			"insert_after": "subject",
		},
		{
			"fieldname": "custom_payment_status",
			"fieldtype": "Select",
			"label": "Стан оплати",
			"options": "Немає запитів на оплату\nЄ неоплачені запити\nОплачено",
			"default": "Немає запитів на оплату",
			"read_only": 1,
			"no_copy": 1,
			"in_list_view": 1,
			"insert_after": "custom_payment_request_total",
		},
	]
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
		value="Етап погодження",
		property_type="Data",
	)
	_ensure_property_setter(
		fieldname="workflow_state",
		property_name="in_list_view",
		value="1",
		property_type="Check",
	)


def sync_todo_list_fields():
	"""Show the assigned document directly in the standard ToDo list."""
	_ensure_property_setter(
		fieldname="reference_name",
		property_name="label",
		value="Документ",
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
