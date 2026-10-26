from collections.abc import Iterable, Mapping

from erpnext.access_control.permission_rules import is_top_manager

MANAGER_ROLES = frozenset({"Access Manager"})
TOP_ROLES = frozenset({"System Manager", "Administrator"})
SERVICE_USERS = frozenset({"Administrator", "Guest"})
METHOD_PREFIXES = ("/api/method/", "/api/v2/method/")
SCOPE_FIELDS = {"Employee": "name", "Company": "company", "Department": "department", "Branch": "branch"}


def is_top_viewer(viewer: str, viewer_roles) -> bool:
	return viewer == "Administrator" or is_top_manager(viewer_roles)


def view_refusal(
	viewer: str,
	viewer_roles,
	target: str,
	target_roles,
	target_enabled: bool,
	target_type: str | None,
	viewing: bool = False,
	in_scope: bool = True,
) -> str | None:
	checks = (
		("viewing", viewing),
		("not_manager", viewer != "Administrator" and not set(viewer_roles) & MANAGER_ROLES),
		("self", viewer == target),
		("out_of_scope", not in_scope),
		("service_user", target in SERVICE_USERS),
		("disabled", not target_enabled),
		("not_desk_user", target_type != "System User"),
		("top_role", bool(set(target_roles) & TOP_ROLES) and not is_top_viewer(viewer, viewer_roles)),
	)
	return next((code for code, failed in checks if failed), None)


def manage_refusal(
	manager: str, manager_roles, target: str, target_roles, target_enabled: bool, in_scope: bool = True
) -> str | None:
	checks = (
		("not_manager", manager != "Administrator" and not set(manager_roles) & MANAGER_ROLES),
		("self", manager == target),
		("out_of_scope", not in_scope),
		("service_user", target in SERVICE_USERS),
		("disabled", not target_enabled),
		("top_role", bool(set(target_roles) & TOP_ROLES) and not is_top_viewer(manager, manager_roles)),
	)
	return next((code for code, failed in checks if failed), None)


def manager_scope(is_top: bool, allowed: Mapping[str, Iterable[str]]) -> dict[str, frozenset] | None:
	if is_top:
		return None
	scope = {
		SCOPE_FIELDS[doctype]: frozenset(values)
		for doctype, values in allowed.items()
		if doctype in SCOPE_FIELDS and values
	}
	return scope or None


def in_scope(scope: Mapping[str, frozenset] | None, employee: Mapping | None) -> bool:
	if scope is None:
		return True
	if not employee:
		return False
	return all(employee.get(field) in values for field, values in scope.items())


def requested_method(path: str | None, cmd: str | None) -> str | None:
	prefix = next((p for p in METHOD_PREFIXES if (path or "").startswith(p)), None)
	return path[len(prefix) :].strip("/") if prefix else cmd or None


def allowed_while_viewing(method: str | None, allowed) -> bool:
	return bool(method) and method in allowed
