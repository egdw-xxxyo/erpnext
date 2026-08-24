import frappe
from frappe import _
from frappe.desk.form.assign_to import _add as add_assignment

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
		"description": _("Process Payment Request {{ name }} at stage “{{ workflow_state }}”."),
	},
	{
		"name": "Payments: завдання керівнику підрозділу",
		"priority": 30,
		"condition": "workflow_state == 'Перевірка підрозділу'",
		"unassign_condition": "workflow_state != 'Перевірка підрозділу'",
		"user": "payments.department.head@example.invalid",
		"description": _("Review Payment Request {{ name }} from the department."),
	},
	{
		"name": "Payments: завдання фінальному погоджувачу",
		"priority": 20,
		"condition": "workflow_state == 'Фінальне погодження'",
		"unassign_condition": "workflow_state != 'Фінальне погодження'",
		"user": "payments.final.approver@example.invalid",
		"description": _("Perform the final approval of Payment Request {{ name }}."),
	},
	{
		"name": "Payments: завдання казначею",
		"priority": 10,
		"condition": "workflow_state == 'Перевірка казначейства'",
		"unassign_condition": "workflow_state != 'Перевірка казначейства'",
		"user": "payments.treasury@example.invalid",
		"description": _("Review and schedule payment for Payment Request {{ name }}."),
	},
)

NOTIFICATION_NAME = "Payments: сповіщення про етап погодження"
DEMO_NOTIFICATION_USERS = tuple(
	sorted(
		{rule["user"] for rule in ASSIGNMENT_RULES if rule.get("user")} | {"payments.auditor@example.invalid"}
	)
)


def sync_automation_configuration():
	"""Synchronize production-safe automation with an Administrator fallback."""
	for rule in ASSIGNMENT_RULES:
		_ensure_assignment_rule(rule, default_user="Administrator")
	_ensure_notification()
	frappe.clear_cache(doctype=PAYMENT_REQUEST_DOCTYPE)


def sync_demo_automation_configuration():
	"""Create local demo assignments after the demo users have been seeded."""
	for rule in ASSIGNMENT_RULES:
		_ensure_assignment_rule(rule, default_user=rule.get("user") or "Administrator")
	_ensure_notification()
	_ensure_demo_notification_settings()
	frappe.clear_cache(doctype=PAYMENT_REQUEST_DOCTYPE)


def apply_rules_to_existing_requests():
	"""Synchronize quiet stage assignments on requests created before setup."""
	requests = frappe.get_all(
		PAYMENT_REQUEST_DOCTYPE,
		filters={"docstatus": ["<", 2]},
		pluck="name",
	)
	for name in requests:
		sync_payment_request_assignment(frappe.get_doc(PAYMENT_REQUEST_DOCTYPE, name))
	frappe.db.commit()
	return requests


def _ensure_assignment_rule(spec, default_user="Administrator"):
	is_new = not frappe.db.exists("Assignment Rule", spec["name"])
	if not is_new:
		doc = frappe.get_doc("Assignment Rule", spec["name"])
	else:
		doc = frappe.new_doc("Assignment Rule")
		doc.name = spec["name"]

	doc.document_type = PAYMENT_REQUEST_DOCTYPE
	doc.priority = spec["priority"]
	# We keep Assignment Rules as Desk-managed routing configuration, but apply them
	# ourselves so leaving a stage closes its ToDo without a misleading cancellation alert.
	doc.disabled = 1
	doc.description = spec["description"]
	doc.assign_condition = spec["condition"]
	doc.unassign_condition = spec["unassign_condition"]
	doc.close_condition = "workflow_state in ('Погоджено', 'Відхилено')"
	doc.rule = spec.get("rule", "Round Robin")
	doc.field = spec.get("field")
	doc.due_date_based_on = "custom_requested_payment_date"
	# Users configured in Desk are production data. Seed a valid fallback only on
	# first creation and never replace administrators' later choices on deploy.
	if is_new:
		doc.set("users", [{"user": default_user}] if spec.get("user") else [])
	doc.set("assignment_days", [{"day": day} for day in ALL_ASSIGNMENT_DAYS])
	_save(doc)


def _ensure_notification():
	if frappe.db.exists("Notification", NOTIFICATION_NAME):
		doc = frappe.get_doc("Notification", NOTIFICATION_NAME)
	else:
		doc = frappe.new_doc("Notification")
		doc.name = NOTIFICATION_NAME

	# A newly created assignment already produces the useful System Notification.
	# The former stage-change notification duplicated it for every assignee.
	doc.enabled = 0
	doc.channel = "System Notification"
	doc.document_type = PAYMENT_REQUEST_DOCTYPE
	doc.event = "Value Change"
	doc.value_changed = "workflow_state"
	doc.condition = (
		"doc.workflow_state in ('Перевірка підрозділу', 'Фінальне погодження', "
		"'Перевірка казначейства', 'Потребує доопрацювання')"
	)
	doc.send_to_all_assignees = 1
	doc.subject = _("Request {{ doc.name }}: {{ doc.workflow_state }}")
	doc.message = _("Payment Request <b>{{ doc.name }}</b> moved to stage <b>{{ doc.workflow_state }}</b>.")
	doc.set("recipients", [])
	_save(doc)


def sync_payment_request_assignment(doc, method=None):
	"""Assign the active payment stage and quietly close the previous stage's ToDo."""
	if doc.doctype != PAYMENT_REQUEST_DOCTYPE:
		return

	matching = next((spec for spec in ASSIGNMENT_RULES if _matches_stage(spec, doc)), None)
	managed_rules = [spec["name"] for spec in ASSIGNMENT_RULES]
	open_todos = frappe.get_all(
		"ToDo",
		filters={
			"reference_type": PAYMENT_REQUEST_DOCTYPE,
			"reference_name": doc.name,
			"assignment_rule": ["in", managed_rules],
			"status": "Open",
		},
		fields=["name", "assignment_rule", "allocated_to"],
	)

	target_user = _get_stage_user(matching, doc) if matching else None
	for todo in open_todos:
		if matching and todo.assignment_rule == matching["name"] and todo.allocated_to == target_user:
			continue
		todo_doc = frappe.get_doc("ToDo", todo.name)
		todo_doc.status = "Closed"
		todo_doc.save(ignore_permissions=True)

	if not matching or not target_user or not frappe.db.get_value("User", target_user, "enabled"):
		return
	if any(
		todo.assignment_rule == matching["name"] and todo.allocated_to == target_user
		for todo in open_todos
	):
		return

	rule = frappe.get_doc("Assignment Rule", matching["name"])
	add_assignment(
		{
			"assign_to": [target_user],
			"doctype": PAYMENT_REQUEST_DOCTYPE,
			"name": doc.name,
			"description": frappe.render_template(rule.description, doc.as_dict()),
			"assignment_rule": rule.name,
			"date": doc.get(rule.due_date_based_on) if rule.due_date_based_on else None,
		},
		ignore_permissions=True,
	)
	if rule.rule == "Round Robin":
		rule.db_set("last_user", target_user)


def _matches_stage(spec, doc):
	return bool(frappe.safe_eval(spec["condition"], None, doc.as_dict()))


def _get_stage_user(spec, doc):
	if not spec:
		return None
	if spec.get("field"):
		return doc.get(spec["field"])
	rule = frappe.get_doc("Assignment Rule", spec["name"])
	return rule.get_user(doc.as_dict())


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
