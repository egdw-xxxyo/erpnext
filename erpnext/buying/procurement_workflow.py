import frappe

CONSOLIDATED_PURCHASE_ORDER_DOCTYPE = "Consolidated Purchase Order"
LEGACY_WORKFLOW_NAME = "Закупівлі: погодження замовлення на придбання"
WORKFLOW_NAME = "Закупівлі: погодження зведеного замовлення на придбання"

MATERIAL_REQUEST_INITIATOR_ROLE = "Закупівлі: Ініціатор замовлень матеріалів"
BUYER_ROLE = "Закупівельник"
BUYER_ROLE_PROFILE = "Закупівлі: профіль закупівельника"
PAYMENT_INITIATOR_ROLE = "Payments: Ініціатор"
DEPARTMENT_HEAD_ROLE = "Payments: Керівник підрозділу"
FINAL_APPROVER_ROLE = "Payments: Фінальний погоджувач"
TREASURER_ROLE = "Payments: Казначей"
WAREHOUSE_MANAGER_ROLE = "Stock Manager"
WAREHOUSE_MANAGER_ROLE_PROFILE = "Закупівлі: профіль начальника складу"
LEGACY_WAREHOUSE_ASSIGNMENT_RULE_NAME = "Закупівлі: надходження замовлення на придбання"
PURCHASE_ORDER_BUYER_ASSIGNMENT_RULE_NAME = "Закупівлі: створення прихідної накладної"
PURCHASE_RECEIPT_WAREHOUSE_ASSIGNMENT_RULE_NAME = "Закупівлі: приймання прихідної накладної"
MATERIAL_REQUEST_BUYER_ASSIGNMENT_RULE_NAME = "Закупівлі: опрацювання замовлення матеріалів"
CONSOLIDATED_BUYER_ASSIGNMENT_RULE_NAME = "Закупівлі: завдання закупівельнику"
CONSOLIDATED_DEPARTMENT_ASSIGNMENT_RULE_NAME = "Закупівлі: завдання керівнику підрозділу"
CONSOLIDATED_FINAL_ASSIGNMENT_RULE_NAME = "Закупівлі: завдання фінальному погоджувачу"
ALL_ASSIGNMENT_DAYS = (
	"Monday",
	"Tuesday",
	"Wednesday",
	"Thursday",
	"Friday",
	"Saturday",
	"Sunday",
)

PROCUREMENT_ASSIGNMENT_RULES = (
	{
		"name": MATERIAL_REQUEST_BUYER_ASSIGNMENT_RULE_NAME,
		"document_type": "Material Request",
		"priority": 40,
		"condition": "docstatus == 1 and material_request_type == 'Purchase'",
		"unassign_condition": "docstatus != 1 or material_request_type != 'Purchase'",
		"close_condition": "docstatus == 2",
		"role": BUYER_ROLE,
		"role_profile": BUYER_ROLE_PROFILE,
		"description": "Опрацювати замовлення матеріалів {{ name }}.",
	},
	{
		"name": CONSOLIDATED_BUYER_ASSIGNMENT_RULE_NAME,
		"document_type": CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
		"priority": 30,
		"condition": (
			"docstatus == 0 and workflow_state in "
			"('Чернетка', 'Потребує доопрацювання', 'Погоджено')"
		),
		"unassign_condition": (
			"docstatus != 0 or workflow_state not in "
			"('Чернетка', 'Потребує доопрацювання', 'Погоджено')"
		),
		"close_condition": "docstatus == 1 or docstatus == 2 or workflow_state == 'Відхилено'",
		"rule": "Based on Field",
		"field": "initiator_user",
		"description": "Опрацювати зведене замовлення на придбання {{ name }}.",
	},
	{
		"name": CONSOLIDATED_DEPARTMENT_ASSIGNMENT_RULE_NAME,
		"document_type": CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
		"priority": 20,
		"condition": "docstatus == 0 and workflow_state == 'Перевірка підрозділу'",
		"unassign_condition": "docstatus != 0 or workflow_state != 'Перевірка підрозділу'",
		"close_condition": "docstatus == 2 or workflow_state == 'Відхилено'",
		"role": DEPARTMENT_HEAD_ROLE,
		"description": "Перевірити зведене замовлення на придбання {{ name }} від підрозділу.",
	},
	{
		"name": CONSOLIDATED_FINAL_ASSIGNMENT_RULE_NAME,
		"document_type": CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
		"priority": 10,
		"condition": "docstatus == 0 and workflow_state == 'Фінальне погодження'",
		"unassign_condition": "docstatus != 0 or workflow_state != 'Фінальне погодження'",
		"close_condition": "docstatus == 2 or workflow_state == 'Відхилено'",
		"role": FINAL_APPROVER_ROLE,
		"description": "Виконати фінальне погодження зведеного замовлення {{ name }}.",
	},
)

ROLE_PROFILES = {
	"Закупівлі: профіль ініціатора замовлень матеріалів": (
		MATERIAL_REQUEST_INITIATOR_ROLE,
		"Stock User",
		"Employee",
	),
	BUYER_ROLE_PROFILE: (
		BUYER_ROLE,
		PAYMENT_INITIATOR_ROLE,
		"Purchase User",
		"Stock User",
		"Employee",
	),
	WAREHOUSE_MANAGER_ROLE_PROFILE: (
		WAREHOUSE_MANAGER_ROLE,
		"Stock User",
		"Purchase User",
		"Quality Manager",
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
	{"state": "Перевірка підрозділу", "doc_status": "0", "allow_edit": "System Manager"},
	{"state": "Фінальне погодження", "doc_status": "0", "allow_edit": "System Manager"},
	{"state": "Потребує доопрацювання", "doc_status": "0", "allow_edit": BUYER_ROLE},
	{"state": "Погоджено", "doc_status": "0", "allow_edit": "System Manager"},
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
		"condition": "(doc.grand_total or 0) >= (doc.ceo_approval_threshold or 15000)",
	},
	{
		"state": "Перевірка підрозділу",
		"action": "Погодити",
		"next_state": "Погоджено",
		"allowed": DEPARTMENT_HEAD_ROLE,
		"allow_self_approval": 0,
		"condition": "(doc.grand_total or 0) < (doc.ceo_approval_threshold or 15000)",
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
		WAREHOUSE_MANAGER_ROLE: ("select", "read", "report", "print"),
	},
	"Purchase Invoice": {
		BUYER_ROLE: ("select", "read", "write", "create", "submit", "report", "print"),
		TREASURER_ROLE: ("select", "read", "report", "print"),
	},
}


def sync_procurement_workflow():
	_ensure_roles()
	_ensure_role_profiles()
	_ensure_permissions()
	_ensure_procurement_assignment_rules()
	_ensure_receipt_assignment_rules()
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
		existing_roles = {row.role for row in doc.get("roles") or []}
		for role in roles:
			if role not in existing_roles:
				doc.append("roles", {"role": role})
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


def _ensure_receipt_assignment_rules():
	_specs = (
		{
			"name": PURCHASE_ORDER_BUYER_ASSIGNMENT_RULE_NAME,
			"document_type": "Purchase Order",
			"role": BUYER_ROLE,
			"description": "Створити прихідну накладну для замовлення на придбання {{ name }}.",
			"assign_condition": "custom_procurement_completion_status == 'Очікує надходження'",
			"unassign_condition": "custom_procurement_completion_status != 'Очікує надходження'",
			"close_condition": "custom_procurement_completion_status == 'Завершено' or docstatus == 2",
		},
		{
			"name": PURCHASE_RECEIPT_WAREHOUSE_ASSIGNMENT_RULE_NAME,
			"document_type": "Purchase Receipt",
			"role": WAREHOUSE_MANAGER_ROLE,
			"description": "Прийняти товари за прихідною накладною {{ name }}.",
			"assign_condition": "docstatus == 0",
			"unassign_condition": "docstatus != 0",
			"close_condition": "docstatus != 0",
		},
	)
	for spec in _specs:
		is_new = not frappe.db.exists("Assignment Rule", spec["name"])
		if is_new:
			doc = frappe.new_doc("Assignment Rule")
			doc.name = spec["name"]
		else:
			doc = frappe.get_doc("Assignment Rule", spec["name"])

		doc.document_type = spec["document_type"]
		doc.priority = 10
		# The lifecycle is handled explicitly in procurement_automation. The rule is
		# retained as the Desk-managed source of assignees and assignment copy.
		doc.disabled = 1
		doc.description = spec["description"]
		doc.assign_condition = spec["assign_condition"]
		doc.unassign_condition = spec["unassign_condition"]
		doc.close_condition = spec["close_condition"]
		doc.rule = "Round Robin"
		# Operational assignees are seeded only once. Existing Desk configuration is
		# never overwritten by migrate/deploy.
		if is_new or not doc.get("users"):
			doc.set("users", [{"user": "Administrator"}])
		doc.set("assignment_days", [{"day": day} for day in ALL_ASSIGNMENT_DAYS])
		_save(doc)

	if frappe.db.exists("Assignment Rule", LEGACY_WAREHOUSE_ASSIGNMENT_RULE_NAME):
		from erpnext.buying.procurement_automation import _close_todo_silently

		legacy_rule = frappe.get_doc("Assignment Rule", LEGACY_WAREHOUSE_ASSIGNMENT_RULE_NAME)
		legacy_rule.disabled = 1
		_save(legacy_rule)
		for todo_name in frappe.get_all(
			"ToDo",
			filters={
				"assignment_rule": LEGACY_WAREHOUSE_ASSIGNMENT_RULE_NAME,
				"status": "Open",
			},
			pluck="name",
		):
			_close_todo_silently(todo_name)


def _ensure_procurement_assignment_rules():
	for spec in PROCUREMENT_ASSIGNMENT_RULES:
		is_new = not frappe.db.exists("Assignment Rule", spec["name"])
		if is_new:
			doc = frappe.new_doc("Assignment Rule")
			doc.name = spec["name"]
		else:
			doc = frappe.get_doc("Assignment Rule", spec["name"])

		doc.document_type = spec["document_type"]
		doc.priority = spec["priority"]
		# Assignment lifecycle is handled explicitly so completed stages can close
		# their ToDos without sending a misleading assignment-removal notification.
		doc.disabled = 1
		doc.description = spec["description"]
		doc.assign_condition = spec["condition"]
		doc.unassign_condition = spec["unassign_condition"]
		doc.close_condition = spec["close_condition"]
		doc.rule = spec.get("rule", "Round Robin")
		doc.field = spec.get("field")
		# Assignees configured in Desk are operational data. Seed one valid user only
		# when a rule is first created and never overwrite later administrator changes.
		if is_new and doc.rule == "Round Robin":
			doc.set(
				"users",
				[
					{"user": user}
					for user in _get_default_role_users(
						spec["role"], role_profile=spec.get("role_profile")
					)
				],
			)
		doc.set("assignment_days", [{"day": day} for day in ALL_ASSIGNMENT_DAYS])
		_save(doc)


def _get_default_role_users(role, role_profile=None):
	if role_profile:
		profile_users = frappe.get_all(
			"User",
			filters={"enabled": 1, "role_profile_name": role_profile},
			pluck="name",
			order_by="name asc",
		)
		if profile_users:
			return profile_users

	users = frappe.get_all(
		"Has Role",
		filters={"role": role, "parenttype": "User"},
		pluck="parent",
		order_by="parent asc",
	)
	users = [
		user
		for user in users
		if user not in {"Administrator", "Guest"} and frappe.db.get_value("User", user, "enabled")
	]
	return users or ["Administrator"]


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
