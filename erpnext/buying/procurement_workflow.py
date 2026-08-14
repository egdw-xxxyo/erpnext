import frappe

CONSOLIDATED_PURCHASE_ORDER_DOCTYPE = "Consolidated Purchase Order"
LEGACY_WORKFLOW_NAME = "Закупівлі: погодження замовлення на придбання"
WORKFLOW_NAME = "Закупівлі: погодження зведеного замовлення на придбання"

MATERIAL_REQUEST_INITIATOR_ROLE = "Закупівлі: Ініціатор замовлень матеріалів"
BUYER_ROLE = "Закупівельник"
PAYMENT_INITIATOR_ROLE = "Payments: Ініціатор"
DEPARTMENT_HEAD_ROLE = "Payments: Керівник підрозділу"
FINAL_APPROVER_ROLE = "Payments: Фінальний погоджувач"

ROLE_PROFILES = {
	"Закупівлі: профіль ініціатора замовлень матеріалів": (
		MATERIAL_REQUEST_INITIATOR_ROLE,
		"Stock User",
		"Employee",
	),
	"Закупівлі: профіль закупівельника": (
		BUYER_ROLE,
		PAYMENT_INITIATOR_ROLE,
		"Purchase User",
		"Stock User",
		"Employee",
	),
}

WORKFLOW_STATES = (
	("Чернетка", "Primary"),
	("Перевірка підрозділу", "Warning"),
	("Фінальне погодження", "Warning"),
	("Потребує доопрацювання", "Danger"),
	("Погоджено", "Success"),
	("Проведено", "Success"),
	("Відхилено", "Danger"),
)

WORKFLOW_ACTIONS = (
	"Подати на перевірку підрозділу",
	"Погодити",
	"Повернути на доопрацювання",
	"Відхилити",
	"Подати повторно",
	"Провести",
)

WORKFLOW_DOCUMENT_STATES = (
	{"state": "Чернетка", "doc_status": "0", "allow_edit": BUYER_ROLE},
	{"state": "Перевірка підрозділу", "doc_status": "0", "allow_edit": DEPARTMENT_HEAD_ROLE},
	{"state": "Фінальне погодження", "doc_status": "0", "allow_edit": FINAL_APPROVER_ROLE},
	{"state": "Потребує доопрацювання", "doc_status": "0", "allow_edit": BUYER_ROLE},
	{"state": "Погоджено", "doc_status": "0", "allow_edit": BUYER_ROLE},
	{"state": "Проведено", "doc_status": "1", "allow_edit": BUYER_ROLE},
	{"state": "Відхилено", "doc_status": "0", "allow_edit": "System Manager"},
)

WORKFLOW_TRANSITIONS = (
	{
		"state": "Чернетка",
		"action": "Подати на перевірку підрозділу",
		"next_state": "Перевірка підрозділу",
		"allowed": BUYER_ROLE,
		"allow_self_approval": 1,
	},
	{
		"state": "Потребує доопрацювання",
		"action": "Подати повторно",
		"next_state": "Перевірка підрозділу",
		"allowed": BUYER_ROLE,
		"allow_self_approval": 1,
	},
	{
		"state": "Перевірка підрозділу",
		"action": "Погодити",
		"next_state": "Фінальне погодження",
		"allowed": DEPARTMENT_HEAD_ROLE,
		"allow_self_approval": 0,
	},
	{
		"state": "Перевірка підрозділу",
		"action": "Повернути на доопрацювання",
		"next_state": "Потребує доопрацювання",
		"allowed": DEPARTMENT_HEAD_ROLE,
		"allow_self_approval": 0,
	},
	{
		"state": "Перевірка підрозділу",
		"action": "Відхилити",
		"next_state": "Відхилено",
		"allowed": DEPARTMENT_HEAD_ROLE,
		"allow_self_approval": 0,
	},
	{
		"state": "Фінальне погодження",
		"action": "Погодити",
		"next_state": "Погоджено",
		"allowed": FINAL_APPROVER_ROLE,
		"allow_self_approval": 0,
	},
	{
		"state": "Фінальне погодження",
		"action": "Повернути на доопрацювання",
		"next_state": "Потребує доопрацювання",
		"allowed": FINAL_APPROVER_ROLE,
		"allow_self_approval": 0,
	},
	{
		"state": "Фінальне погодження",
		"action": "Відхилити",
		"next_state": "Відхилено",
		"allowed": FINAL_APPROVER_ROLE,
		"allow_self_approval": 0,
	},
	{
		"state": "Погоджено",
		"action": "Провести",
		"next_state": "Проведено",
		"allowed": BUYER_ROLE,
		"allow_self_approval": 1,
	},
)

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

DOCTYPE_PERMISSIONS = {
	"Material Request": {
		MATERIAL_REQUEST_INITIATOR_ROLE: (
			"select",
			"read",
			"write",
			"create",
			"delete",
			"submit",
			"report",
			"print",
		),
		BUYER_ROLE: ("select", "read", "report", "print"),
	},
	CONSOLIDATED_PURCHASE_ORDER_DOCTYPE: {
		BUYER_ROLE: (
			"select",
			"read",
			"write",
			"create",
			"delete",
			"submit",
			"cancel",
			"amend",
			"report",
			"print",
		),
		DEPARTMENT_HEAD_ROLE: ("select", "read", "write", "report", "print"),
		FINAL_APPROVER_ROLE: ("select", "read", "write", "report", "print"),
	},
	"Purchase Invoice": {
		BUYER_ROLE: ("select", "read", "write", "create", "report", "print"),
	},
}


def sync_procurement_workflow():
	_ensure_roles()
	_ensure_role_profiles()
	_ensure_permissions()
	_ensure_workflow_states()
	_ensure_workflow_actions()
	_ensure_workflow()
	# Role and Custom DocPerm changes also affect user-level permission caches.
	# Clearing only DocType metadata can leave approvers without access until the
	# next process/cache restart.
	frappe.clear_cache()
	frappe.clear_cache(doctype="Material Request")
	frappe.clear_cache(doctype=CONSOLIDATED_PURCHASE_ORDER_DOCTYPE)


def _ensure_roles():
	for role_name in (MATERIAL_REQUEST_INITIATOR_ROLE, BUYER_ROLE):
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


def _ensure_role_profiles():
	for profile_name, roles in ROLE_PROFILES.items():
		if frappe.db.exists("Role Profile", profile_name):
			doc = frappe.get_doc("Role Profile", profile_name)
		else:
			doc = frappe.new_doc("Role Profile")
			doc.role_profile = profile_name
		doc.set("roles", [{"role": role} for role in roles])
		_save(doc)


def _ensure_permissions():
	for doctype, role_permissions in DOCTYPE_PERMISSIONS.items():
		for role, enabled_permissions in role_permissions.items():
			filters = {"parent": doctype, "role": role, "permlevel": 0}
			name = frappe.db.get_value("Custom DocPerm", filters, "name")
			if name:
				doc = frappe.get_doc("Custom DocPerm", name)
			else:
				doc = frappe.new_doc("Custom DocPerm")
				doc.parent = doctype
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
		doc = frappe.new_doc("Workflow Action Master")
		doc.workflow_action_name = action_name
		doc.insert(ignore_permissions=True)


def _ensure_workflow():
	if frappe.db.exists("Workflow", LEGACY_WORKFLOW_NAME):
		legacy_workflow = frappe.get_doc("Workflow", LEGACY_WORKFLOW_NAME)
		legacy_workflow.is_active = 0
		_save(legacy_workflow)

	if frappe.db.exists("Workflow", WORKFLOW_NAME):
		doc = frappe.get_doc("Workflow", WORKFLOW_NAME)
	else:
		doc = frappe.new_doc("Workflow")
		doc.workflow_name = WORKFLOW_NAME

	doc.document_type = CONSOLIDATED_PURCHASE_ORDER_DOCTYPE
	doc.is_active = 1
	doc.override_status = 0
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
