import frappe

PAYMENTS_INITIATOR_ROLE = "Payments: Ініціатор"
PAYMENTS_DEPARTMENT_HEAD_ROLE = "Payments: Керівник підрозділу"
BUYER_ROLE = "Закупівельник"
PAYMENTS_FULL_VISIBILITY_ROLES = {
	PAYMENTS_DEPARTMENT_HEAD_ROLE,
	"Payments: Казначей",
	"Payments: Фінальний погоджувач",
	"Payments: Аудитор",
}


def get_permission_query_conditions(user=None, doctype=None):
	"""Restrict Payment Request lists to documents relevant to the current user."""
	user = user or frappe.session.user
	if user == "Administrator":
		return ""

	roles = set(frappe.get_roles(user))
	if roles & PAYMENTS_FULL_VISIBILITY_ROLES:
		return ""

	conditions = []
	if PAYMENTS_INITIATOR_ROLE in roles or BUYER_ROLE in roles:
		conditions.extend((_owner_condition(user), _open_assignment_condition(user)))

	if not conditions:
		return "1=0"

	return f"({' or '.join(dict.fromkeys(conditions))})"


def has_permission(doc, ptype=None, user=None, debug=False):
	"""Apply the same visibility rules when a Payment Request is opened directly."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True

	roles = set(frappe.get_roles(user))
	if roles & PAYMENTS_FULL_VISIBILITY_ROLES:
		return True

	if PAYMENTS_INITIATOR_ROLE not in roles and BUYER_ROLE not in roles:
		return False

	if doc.owner == user or _is_openly_assigned(doc.name, user):
		return True

	return False


def _owner_condition(user):
	return f"`tabPayment Request`.`owner` = {frappe.db.escape(user)}"


def _open_assignment_condition(user):
	escaped_user = frappe.db.escape(user)
	return f"""exists (
		select 1 from `tabToDo`
		where `tabToDo`.`reference_type` = 'Payment Request'
			and `tabToDo`.`reference_name` = `tabPayment Request`.`name`
			and `tabToDo`.`allocated_to` = {escaped_user}
			and `tabToDo`.`status` = 'Open'
	)"""


def _is_openly_assigned(payment_request, user):
	return bool(
		frappe.db.exists(
			"ToDo",
			{
				"reference_type": "Payment Request",
				"reference_name": payment_request,
				"allocated_to": user,
				"status": "Open",
			},
		)
	)
