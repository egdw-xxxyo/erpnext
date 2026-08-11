import frappe


WORKFLOW_NAME = "Payments: погодження запиту на оплату"

WORKFLOW_STATES = (
	("Чернетка", "Primary"),
	("Перевірка підрозділу", "Warning"),
	("Фінальне погодження", "Warning"),
	("Перевірка казначейства", "Info"),
	("Потребує доопрацювання", "Danger"),
	("Погоджено", "Success"),
	("Відхилено", "Danger"),
)

WORKFLOW_ACTIONS = (
	"Подати на перевірку підрозділу",
	"Погодити",
	"Повернути на доопрацювання",
	"Відхилити",
	"Подати повторно",
)

ROLE_PROFILES = {
	"Payments: профіль ініціатора": (
		"Payments: Ініціатор",
		"Accounts User",
		"Purchase User",
		"Stock User",
		"Employee",
	),
	"Payments: профіль керівника підрозділу": (
		"Payments: Керівник підрозділу",
		"Accounts User",
		"Employee",
	),
	"Payments: профіль фінального погоджувача": (
		"Payments: Фінальний погоджувач",
		"Accounts User",
		"Employee",
	),
	"Payments: профіль казначея": (
		"Payments: Казначей",
		"Accounts Manager",
		"Employee",
	),
	"Payments: профіль аудитора": (
		"Payments: Аудитор",
		"Auditor",
		"Accounts User",
		"Employee",
	),
}

CREATOR_TRANSITION_CONDITION = "doc.owner == frappe.session.user"


PAYMENT_REQUEST_PERMISSIONS = {
	"Payments: Ініціатор": ("select", "read", "write", "create", "delete", "report", "print"),
	"Payments: Керівник підрозділу": (
		"select", "read", "write", "create", "report", "print"
	),
	"Payments: Фінальний погоджувач": (
		"select", "read", "write", "create", "report", "print"
	),
	"Payments: Казначей": (
		"select",
		"read",
		"write",
		"submit",
		"report",
		"export",
		"print",
	),
	"Payments: Аудитор": ("select", "read", "report", "export", "print"),
}

PERMISSION_FIELDS = (
	"select",
	"read",
	"write",
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"report",
	"export",
	"import",
	"share",
	"print",
	"email",
)

WORKFLOW_DOCUMENT_STATES = (
	{"state": "Чернетка", "doc_status": "0", "allow_edit": "Payments: Ініціатор"},
	{
		"state": "Перевірка підрозділу",
		"doc_status": "0",
		"allow_edit": "Payments: Керівник підрозділу",
	},
	{"state": "Фінальне погодження", "doc_status": "0", "allow_edit": "Payments: Фінальний погоджувач"},
	{"state": "Перевірка казначейства", "doc_status": "0", "allow_edit": "Payments: Казначей"},
	{"state": "Потребує доопрацювання", "doc_status": "0", "allow_edit": "Payments: Ініціатор"},
	{"state": "Погоджено", "doc_status": "1", "allow_edit": "Payments: Казначей"},
	{"state": "Відхилено", "doc_status": "0", "allow_edit": "System Manager"},
)

WORKFLOW_TRANSITIONS = (
	{
		"state": "Чернетка",
		"action": "Подати на перевірку підрозділу",
		"next_state": "Перевірка підрозділу",
		"allowed": "Payments: Ініціатор",
		"allow_self_approval": 1,
	},
	{
		"state": "Чернетка",
		"action": "Подати на перевірку підрозділу",
		"next_state": "Перевірка підрозділу",
		"allowed": "Payments: Керівник підрозділу",
		"allow_self_approval": 1,
		"condition": CREATOR_TRANSITION_CONDITION,
	},
	{
		"state": "Чернетка",
		"action": "Подати на перевірку підрозділу",
		"next_state": "Перевірка підрозділу",
		"allowed": "Payments: Фінальний погоджувач",
		"allow_self_approval": 1,
		"condition": CREATOR_TRANSITION_CONDITION,
	},
	{
		"state": "Потребує доопрацювання",
		"action": "Подати повторно",
		"next_state": "Перевірка підрозділу",
		"allowed": "Payments: Ініціатор",
		"allow_self_approval": 1,
	},
	{
		"state": "Потребує доопрацювання",
		"action": "Подати повторно",
		"next_state": "Перевірка підрозділу",
		"allowed": "Payments: Керівник підрозділу",
		"allow_self_approval": 1,
		"condition": CREATOR_TRANSITION_CONDITION,
	},
	{
		"state": "Потребує доопрацювання",
		"action": "Подати повторно",
		"next_state": "Перевірка підрозділу",
		"allowed": "Payments: Фінальний погоджувач",
		"allow_self_approval": 1,
		"condition": CREATOR_TRANSITION_CONDITION,
	},
	{
		"state": "Перевірка підрозділу",
		"action": "Погодити",
		"next_state": "Фінальне погодження",
		"allowed": "Payments: Керівник підрозділу",
		"allow_self_approval": 1,
	},
	{
		"state": "Перевірка підрозділу",
		"action": "Погодити",
		"next_state": "Фінальне погодження",
		"allowed": "Payments: Фінальний погоджувач",
		"allow_self_approval": 1,
		"condition": CREATOR_TRANSITION_CONDITION,
	},
	{
		"state": "Перевірка підрозділу",
		"action": "Повернути на доопрацювання",
		"next_state": "Потребує доопрацювання",
		"allowed": "Payments: Керівник підрозділу",
		"allow_self_approval": 0,
	},
	{
		"state": "Перевірка підрозділу",
		"action": "Відхилити",
		"next_state": "Відхилено",
		"allowed": "Payments: Керівник підрозділу",
		"allow_self_approval": 0,
	},
	{
		"state": "Фінальне погодження",
		"action": "Погодити",
		"next_state": "Перевірка казначейства",
		"allowed": "Payments: Фінальний погоджувач",
		"allow_self_approval": 1,
	},
	{
		"state": "Фінальне погодження",
		"action": "Повернути на доопрацювання",
		"next_state": "Потребує доопрацювання",
		"allowed": "Payments: Фінальний погоджувач",
		"allow_self_approval": 0,
	},
	{
		"state": "Фінальне погодження",
		"action": "Відхилити",
		"next_state": "Відхилено",
		"allowed": "Payments: Фінальний погоджувач",
		"allow_self_approval": 0,
	},
	{
		"state": "Перевірка казначейства",
		"action": "Погодити",
		"next_state": "Погоджено",
		"allowed": "Payments: Казначей",
		"allow_self_approval": 0,
	},
	{
		"state": "Перевірка казначейства",
		"action": "Повернути на доопрацювання",
		"next_state": "Потребує доопрацювання",
		"allowed": "Payments: Казначей",
		"allow_self_approval": 0,
	},
	{
		"state": "Перевірка казначейства",
		"action": "Відхилити",
		"next_state": "Відхилено",
		"allowed": "Payments: Казначей",
		"allow_self_approval": 0,
	},
)


def sync_workflow_configuration():
	_ensure_role_profiles()
	_ensure_payment_request_permissions()
	_ensure_workflow_states()
	_ensure_workflow_actions()
	_ensure_workflow()
	frappe.clear_cache(doctype="Payment Request")


def _ensure_role_profiles():
	for profile_name, roles in ROLE_PROFILES.items():
		if frappe.db.exists("Role Profile", profile_name):
			doc = frappe.get_doc("Role Profile", profile_name)
		else:
			doc = frappe.new_doc("Role Profile")
			doc.role_profile = profile_name

		doc.set("roles", [{"role": role} for role in roles])
		_save(doc)


def _ensure_payment_request_permissions():
	for role, enabled_permissions in PAYMENT_REQUEST_PERMISSIONS.items():
		filters = {
			"parent": "Payment Request",
			"role": role,
			"permlevel": 0,
		}
		name = frappe.db.get_value("Custom DocPerm", filters, "name")
		if name:
			doc = frappe.get_doc("Custom DocPerm", name)
		else:
			doc = frappe.new_doc("Custom DocPerm")
			doc.parent = "Payment Request"
			doc.role = role
			doc.permlevel = 0

		doc.if_owner = 0
		for permission in PERMISSION_FIELDS:
			doc.set(permission, int(permission in enabled_permissions))
		_save(doc)


def _ensure_workflow_states():
	for state_name, style in WORKFLOW_STATES:
		if frappe.db.exists("Workflow State", state_name):
			doc = frappe.get_doc("Workflow State", state_name)
		else:
			doc = frappe.new_doc("Workflow State")
			doc.workflow_state_name = state_name
		doc.style = style
		_save(doc)


def _ensure_workflow_actions():
	for action_name in WORKFLOW_ACTIONS:
		if frappe.db.exists("Workflow Action Master", action_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Workflow Action Master",
				"workflow_action_name": action_name,
			}
		).insert(ignore_permissions=True)


def _ensure_workflow():
	if frappe.db.exists("Workflow", WORKFLOW_NAME):
		doc = frappe.get_doc("Workflow", WORKFLOW_NAME)
	else:
		doc = frappe.new_doc("Workflow")
		doc.workflow_name = WORKFLOW_NAME

	doc.document_type = "Payment Request"
	doc.is_active = 1
	# Keep ERPNext's payment status as the primary list indicator. The workflow
	# stage is shown separately through the workflow_state list-view property.
	doc.override_status = 1
	doc.send_email_alert = 0
	doc.workflow_state_field = "workflow_state"
	doc.set("states", list(WORKFLOW_DOCUMENT_STATES))
	doc.set("transitions", list(WORKFLOW_TRANSITIONS))
	_save(doc)


def _save(doc):
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)
