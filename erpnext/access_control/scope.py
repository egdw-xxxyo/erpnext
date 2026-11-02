import frappe
from frappe.permissions import get_user_permissions

from erpnext.access_control import impersonation_rules as rules
from erpnext.access_control import permission_rules

EMPLOYEE_FIELDS = ("name", "employee_name", "user_id", "company", "department", "branch")


def manager_scope(user: str | None = None) -> dict | None:
	user = user or frappe.session.user
	allowed = {
		doctype: permission_rules.allowed_values(entries, "Employee")
		for doctype, entries in get_user_permissions(user).items()
	}
	return rules.manager_scope(rules.is_top_viewer(user, frappe.get_roles(user)), allowed)


def employees_by_user(users: list[str]) -> dict[str, dict]:
	if not users:
		return {}
	rows = frappe.get_all(
		"Employee",
		filters={"user_id": ["in", users]},
		fields=list(EMPLOYEE_FIELDS),
		order_by="status asc, modified desc",
	)
	return {user: next(row for row in rows if row.user_id == user) for user in {row.user_id for row in rows}}


def user_in_scope(user: str) -> bool:
	scope = manager_scope()
	return rules.in_scope(scope, employees_by_user([user]).get(user) if scope else None)
