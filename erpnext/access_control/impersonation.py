from itertools import groupby
from operator import itemgetter

import frappe
from frappe import _
from frappe.sessions import delete_session
from frappe.utils import now_datetime

from erpnext.access_control import impersonation_rules as rules
from erpnext.access_control import permission_rules
from erpnext.access_control.console import manage_refusal, temporary_roles
from erpnext.access_control.doctype.access_request.access_request import _roles_by_profile
from erpnext.access_control.permissions_engine import _require_manager
from erpnext.access_control.scope import employees_by_user, manager_scope, user_in_scope

SESSION_KEY = "access_view"
SIMULATE_METHOD = "erpnext.access_control.dry_run.simulate"
ALLOWED_WHILE_VIEWING = frozenset({"erpnext.access_control.impersonation.end_view", "logout"})
LOGIN_METADATA = ("last_login", "last_ip", "last_active")


def refusal_messages() -> dict[str, str]:
	return {
		"viewing": _("Finish the current view session first"),
		"not_manager": _("Only Access Manager or Administrator can do this"),
		"self": _("You cannot view as yourself"),
		"out_of_scope": _("The user is outside the companies or employees you may manage"),
		"service_user": _("This account cannot be viewed as"),
		"disabled": _("The user is disabled"),
		"not_desk_user": _("Only desk users can be viewed as"),
		"top_role": _(
			"Only Administrator or a user with both System Manager and Access Manager roles can view as users with System Manager role"
		),
	}


def view_session() -> dict | None:
	session = getattr(frappe.local, "session", None)
	return (session.data or {}).get(SESSION_KEY) if session else None


def _roles_by_user(users: list[str]) -> dict[str, list[str]]:
	rows = frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "parent": ["in", users]},
		fields=["parent", "role"],
		order_by="parent, role",
	)
	return {user: [row.role for row in group] for user, group in groupby(rows, key=itemgetter("parent"))}


def _profiles_by_user(users: list[str]) -> dict[str, list[str]]:
	rows = frappe.get_all(
		"User Role Profile",
		filters={"parenttype": "User", "parent": ["in", users]},
		fields=["parent", "role_profile"],
		order_by="parent, idx",
	)
	return {
		user: [row.role_profile for row in group] for user, group in groupby(rows, key=itemgetter("parent"))
	}


def _refusal(user: str, target: dict | None, target_roles, in_scope: bool = True) -> str | None:
	return rules.view_refusal(
		frappe.session.user,
		frappe.get_roles(),
		user,
		target_roles,
		bool(target and target.enabled),
		target.user_type if target else None,
		viewing=bool(view_session()),
		in_scope=in_scope,
	)


def _pending_requests(users: list[str]) -> dict[str, int]:
	rows = frappe.get_all(
		"Access Request",
		filters={"status": "Pending", "user": ["in", users]},
		fields=["user", {"COUNT": "*", "as": "requests"}],
		group_by="user",
	)
	return {row.user: row.requests for row in rows}


@frappe.whitelist()
def get_users() -> list[dict]:
	_require_manager()
	users = frappe.get_all(
		"User",
		filters={"enabled": 1, "user_type": "System User", "name": ["not in", list(rules.SERVICE_USERS)]},
		fields=["name", "full_name", "user_image", "last_login", "enabled", "user_type"],
		order_by="full_name",
	)
	scope = manager_scope()
	employees = employees_by_user([user.name for user in users])
	users = [user for user in users if rules.in_scope(scope, employees.get(user.name))]
	names = [user.name for user in users]
	roles = _roles_by_user(names)
	profiles = _profiles_by_user(names)
	temporary = temporary_roles(names)
	pending = _pending_requests(names)
	by_profile = _roles_by_profile()
	messages = refusal_messages()
	return [
		{
			"user": user.name,
			"full_name": user.full_name,
			"user_image": user.user_image,
			"last_login": user.last_login,
			"roles": roles.get(user.name, []),
			"profiles": profiles.get(user.name, []),
			"role_sources": permission_rules.role_sources(by_profile, profiles.get(user.name, [])),
			"refusal": messages.get(_refusal(user.name, user, roles.get(user.name, []))),
			"manage_refusal": manage_refusal(user.name, bool(user.enabled), roles.get(user.name, [])),
			"temporary": temporary.get(user.name, {}),
			"pending": pending.get(user.name, 0),
			"employee": _employee_json(employees.get(user.name)),
		}
		for user in users
	]


def _employee_json(employee: dict | None) -> dict | None:
	if not employee:
		return None
	return {
		field: employee.get(field) for field in ("name", "employee_name", "company", "department", "branch")
	}


def _log(user: str, subject: str):
	frappe.get_doc(
		{
			"doctype": "Activity Log",
			"user": user,
			"status": "Success",
			"subject": subject,
			"operation": "Impersonate",
		}
	).insert(ignore_permissions=True, ignore_links=True)


def _notify(user: str, viewer: str, reason: str):
	notification = frappe.new_doc(
		"Notification Log",
		for_user=user,
		from_user=viewer,
		subject=_("{0} viewed the system on your behalf (view only). Reason: {1}").format(
			frappe.utils.get_fullname(viewer), frappe.utils.escape_html(reason)
		),
	)
	notification.set("type", "Alert")
	notification.insert(ignore_permissions=True)


def _restore_login_metadata(user: str, metadata: dict):
	frappe.db.set_value("User", user, metadata, update_modified=False)
	frappe.flags.read_only = True


@frappe.whitelist(methods=["POST"])
def start_view(user: str, reason: str) -> dict:
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Enter the reason"))
	target = frappe.db.get_value("User", user, ["name", "enabled", "user_type"], as_dict=True)
	refusal = _refusal(user, target, frappe.get_roles(user) if target else [], user_in_scope(user))
	if refusal:
		frappe.throw(refusal_messages()[refusal], frappe.PermissionError)

	viewer = frappe.session.user
	_log(user, _("{0} started viewing as {1}. Reason: {2}").format(viewer, user, reason))
	_notify(user, viewer, reason)
	metadata = frappe.db.get_value("User", user, LOGIN_METADATA, as_dict=True)
	frappe.local.login_manager.impersonate(user)
	session = frappe.local.session_obj
	session.data.data[SESSION_KEY] = {"by": viewer, "reason": reason, "since": str(now_datetime())}
	session.data.data.csrf_token = frappe.generate_hash()
	session.update(force=True)
	_restore_login_metadata(user, metadata)
	return {"route": "/app"}


@frappe.whitelist(methods=["POST"])
def end_view() -> dict:
	view = view_session()
	if not view:
		frappe.throw(_("This is not a view session"), frappe.PermissionError)

	target = frappe.session.user
	mask_sid = frappe.session.sid
	data = frappe.local.session_obj.data.data
	_log(target, _("{0} finished viewing as {1}").format(view["by"], target))
	frappe.local.login_manager.login_as(view["by"], session_end=data.session_end, audit_user=data.audit_user)
	delete_session(mask_sid, user=target, reason="View session finished")
	return {"route": "/app/access-console"}


def enforce_view_mode():
	if not view_session():
		return
	request = getattr(frappe.local, "request", None)
	method = rules.requested_method(request.path if request else None, frappe.form_dict.get("cmd"))
	if rules.allowed_while_viewing(method, ALLOWED_WHILE_VIEWING):
		return
	from frappe.app import setup_read_only_mode

	from erpnext.access_control.dry_run import DryRun, begin

	begin(DryRun())
	if method != SIMULATE_METHOD:
		setup_read_only_mode()


def boot_view(bootinfo):
	view = view_session()
	if not view:
		return
	bootinfo.read_only = False
	bootinfo.change_log = []
	bootinfo.access_view = {
		"by": view["by"],
		"by_name": frappe.utils.get_fullname(view["by"]),
		"reason": view["reason"],
		"since": view["since"],
	}
