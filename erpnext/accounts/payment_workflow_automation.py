import frappe


PAYMENT_REQUEST_DOCTYPE = "Payment Request"
ALL_ASSIGNMENT_DAYS = (
	"Monday",
	"Tuesday",
	"Wednesday",
	"Thursday",
	"Friday",
	"Saturday",
	"Sunday",
)

ASSIGNMENT_RULES = (
	{
		"name": "Payments: завдання ініціатору",
		"priority": 40,
		"condition": "workflow_state in ('Чернетка', 'Потребує доопрацювання')",
		"unassign_condition": "workflow_state not in ('Чернетка', 'Потребує доопрацювання')",
		"rule": "Based on Field",
		"field": "custom_initiator_user",
		"description": "Опрацювати запит на оплату {{ name }} на етапі «{{ workflow_state }}».",
	},
	{
		"name": "Payments: завдання керівнику підрозділу",
		"priority": 30,
		"condition": "workflow_state == 'Перевірка підрозділу'",
		"unassign_condition": "workflow_state != 'Перевірка підрозділу'",
		"user": "payments.department.head@example.invalid",
		"description": "Перевірити запит на оплату {{ name }} від підрозділу.",
	},
	{
		"name": "Payments: завдання фінальному погоджувачу",
		"priority": 20,
		"condition": "workflow_state == 'Фінальне погодження'",
		"unassign_condition": "workflow_state != 'Фінальне погодження'",
		"user": "payments.final.approver@example.invalid",
		"description": "Виконати фінальне погодження запиту на оплату {{ name }}.",
	},
	{
		"name": "Payments: завдання казначею",
		"priority": 10,
		"condition": "workflow_state == 'Перевірка казначейства'",
		"unassign_condition": "workflow_state != 'Перевірка казначейства'",
		"user": "payments.treasury@example.invalid",
		"description": "Перевірити та запланувати оплату за запитом {{ name }}.",
	},
)

NOTIFICATION_NAME = "Payments: сповіщення про етап погодження"
DEMO_NOTIFICATION_USERS = tuple(
	sorted(
		{rule["user"] for rule in ASSIGNMENT_RULES if rule.get("user")}
		| {"payments.auditor@example.invalid"}
	)
)


def sync_automation_configuration():
	"""Synchronize production-safe automation without demo assignees."""
	_ensure_notification()
	frappe.clear_cache(doctype=PAYMENT_REQUEST_DOCTYPE)


def sync_demo_automation_configuration():
	"""Create local demo assignments after the demo users have been seeded."""
	for rule in ASSIGNMENT_RULES:
		_ensure_assignment_rule(rule)
	_ensure_notification()
	_ensure_demo_notification_settings()
	frappe.clear_cache(doctype=PAYMENT_REQUEST_DOCTYPE)


def apply_rules_to_existing_requests():
	"""Apply the standard Assignment Rules to active requests created before setup."""
	from frappe.automation.doctype.assignment_rule.assignment_rule import apply

	requests = frappe.get_all(
		PAYMENT_REQUEST_DOCTYPE,
		filters={"docstatus": ["<", 2]},
		pluck="name",
	)
	for name in requests:
		apply(doctype=PAYMENT_REQUEST_DOCTYPE, name=name)
	frappe.db.commit()
	return requests


def _ensure_assignment_rule(spec):
	if frappe.db.exists("Assignment Rule", spec["name"]):
		doc = frappe.get_doc("Assignment Rule", spec["name"])
	else:
		doc = frappe.new_doc("Assignment Rule")
		doc.name = spec["name"]

	doc.document_type = PAYMENT_REQUEST_DOCTYPE
	doc.priority = spec["priority"]
	doc.disabled = 0
	doc.description = spec["description"]
	doc.assign_condition = spec["condition"]
	doc.unassign_condition = spec["unassign_condition"]
	doc.close_condition = "workflow_state in ('Погоджено', 'Відхилено')"
	doc.rule = spec.get("rule", "Round Robin")
	doc.field = spec.get("field")
	doc.due_date_based_on = "custom_requested_payment_date"
	doc.set("users", [{"user": spec["user"]}] if spec.get("user") else [])
	doc.set("assignment_days", [{"day": day} for day in ALL_ASSIGNMENT_DAYS])
	_save(doc)


def _ensure_notification():
	if frappe.db.exists("Notification", NOTIFICATION_NAME):
		doc = frappe.get_doc("Notification", NOTIFICATION_NAME)
	else:
		doc = frappe.new_doc("Notification")
		doc.name = NOTIFICATION_NAME

	doc.enabled = 1
	doc.channel = "System Notification"
	doc.document_type = PAYMENT_REQUEST_DOCTYPE
	doc.event = "Value Change"
	doc.value_changed = "workflow_state"
	doc.condition = (
		"doc.workflow_state in ('Перевірка підрозділу', 'Фінальне погодження', "
		"'Перевірка казначейства', 'Потребує доопрацювання')"
	)
	doc.send_to_all_assignees = 1
	doc.subject = "Запит {{ doc.name }}: {{ doc.workflow_state }}"
	doc.message = (
		"Запит на оплату <b>{{ doc.name }}</b> перейшов на етап "
		"<b>{{ doc.workflow_state }}</b>."
	)
	doc.set("recipients", [])
	_save(doc)


def _ensure_demo_notification_settings():
	"""Keep Desk notifications enabled without requiring outgoing email locally."""
	for user in DEMO_NOTIFICATION_USERS:
		if frappe.db.exists("Notification Settings", user):
			doc = frappe.get_doc("Notification Settings", user)
		else:
			doc = frappe.new_doc("Notification Settings")
			doc.name = user

		doc.user = user
		doc.enabled = 1
		doc.enable_email_notifications = 0
		_save(doc)


def _save(doc):
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)
