import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from erpnext.access_control import impersonation_rules
from erpnext.access_control import permission_rules as rules
from erpnext.access_control.doctype.access_request.access_request import (
	_assign_profiles,
	_chosen,
	_current_profiles,
	_grant_role,
	_remove_roles,
	_roles_after_profile,
	_roles_by_profile,
	decision_messages,
	ensure_can_expire,
	parse_valid_till,
)
from erpnext.access_control.permissions_engine import (
	_require_manager,
	doctype_rights,
	doctype_rows,
	roles_delta,
)
from erpnext.access_control.scope import user_in_scope

ACTIONS = ("grant", "remove", "profile")


def refusal_messages() -> dict[str, str]:
	return {
		"not_manager": _("Only Access Manager or Administrator can do this"),
		"self": _("You cannot change your own access"),
		"service_user": _("The access of this account cannot be changed"),
		"disabled": _("The user is disabled"),
		**decision_messages(),
	}


def manage_refusal(user: str, enabled: bool, roles, in_scope: bool = True) -> str | None:
	code = impersonation_rules.manage_refusal(
		frappe.session.user, frappe.get_roles(), user, roles, enabled, in_scope
	)
	return refusal_messages().get(code) if code else None


def _require_target(user: str):
	_require_manager()
	enabled = frappe.db.get_value("User", user, "enabled")
	if enabled is None:
		frappe.throw(_("User {0} not found").format(user), frappe.DoesNotExistError)
	if refusal := manage_refusal(user, bool(enabled), frappe.get_roles(user), user_in_scope(user)):
		frappe.throw(refusal, frappe.PermissionError)


def _holders(table: str, field: str) -> dict[str, int]:
	rows = frappe.db.sql(
		f"""select t.{field} as name, count(*) as users from `tab{table}` t
		join tabUser u on u.name = t.parent
		where t.parenttype = 'User' and u.enabled = 1 group by t.{field}""",
		as_dict=True,
	)
	return {row.name: row.users for row in rows}


def _grantable_roles(held) -> list[dict]:
	holders = _holders("Has Role", "role")
	roles = frappe.get_all("Role", filters={"disabled": 0, "desk_access": 1}, pluck="name", order_by="name")
	return [
		{"role": role, "users": holders.get(role, 0)}
		for role in roles
		if rules.is_grantable(role) and role not in held
	]


def _profiles(current: list[str]) -> list[dict]:
	holders = _holders("User Role Profile", "role_profile")
	return [
		{
			"name": profile,
			"roles": roles,
			"users": holders.get(profile, 0),
			"current": profile in current,
			"privileged": bool(set(roles) & rules.PRIVILEGED_ROLES),
		}
		for profile, roles in _roles_by_profile().items()
	]


@frappe.whitelist()
def get_change_options(user: str) -> dict:
	_require_target(user)
	held = frappe.get_roles(user)
	current = _current_profiles(user)
	return {
		"user": user,
		"roles": [role for role in held if rules.is_grantable(role)],
		"grantable": _grantable_roles(held),
		"current_profiles": current,
		"profiles": _profiles(current),
	}


def _roles_after(user: str, action: str, roles, profiles, profile_mode: str | None) -> list[str]:
	held = frappe.get_roles(user)
	after = {
		"grant": lambda: [*held, *_chosen(roles)],
		"remove": lambda: rules.roles_after_removal(held, _chosen(roles)),
		"profile": lambda: _roles_after_profile(
			user, _chosen(profiles), profile_mode if _current_profiles(user) else "add"
		),
	}
	if action not in after:
		frappe.throw(_("Choose what to change"))
	if action == "profile" and (profile_mode or "add") not in rules.PROFILE_MODES:
		frappe.throw(_("Choose what to do with the user's current role profiles"))
	return after[action]()


@frappe.whitelist()
def preview_change(
	user: str,
	action: str,
	roles: str | list | None = None,
	profiles: str | list | None = None,
	profile_mode: str | None = None,
) -> dict:
	_require_target(user)
	return roles_delta(user, _roles_after(user, action, roles, profiles, profile_mode))


def _assign(doc, profiles=None, profile_mode: str | None = None, **_kwargs) -> dict:
	profiles = _chosen(profiles)
	if not profiles:
		frappe.throw(_("Choose at least one role profile"))
	if missing := [profile for profile in profiles if not frappe.db.exists("Role Profile", profile)]:
		frappe.throw(_("Role profile {0} not found").format(", ".join(missing)), frappe.DoesNotExistError)
	delta = roles_delta(doc.user, _roles_after(doc.user, "profile", None, profiles, profile_mode))
	if ungrantable := rules.ungrantable_gains(delta["gained_roles"]):
		frappe.throw(
			_("These role profiles give roles that cannot be granted here: {0}").format(
				", ".join(ungrantable)
			)
		)
	current = _current_profiles(doc.user)
	if profile_mode != "replace" and not set(profiles) - set(current):
		frappe.throw(_("The user already has these role profiles"))
	return _assign_profiles(doc.user, profiles, profile_mode)


CHANGES = {
	"grant": ("Role", _grant_role),
	"remove": ("Role Removal", _remove_roles),
	"profile": ("Role Profile", _assign),
}


@frappe.whitelist(methods=["POST"])
def change_access(
	user: str,
	action: str,
	reason: str | None = None,
	roles: str | list | None = None,
	profile_action: str | None = None,
	profiles: str | list | None = None,
	profile_mode: str | None = None,
	valid_till: str | None = None,
) -> dict:
	reason = (reason or "").strip() or None
	_require_target(user)
	if action not in CHANGES:
		frappe.throw(_("Choose what to change"))
	valid_till = parse_valid_till(valid_till)
	resolution, apply = CHANGES[action]
	doc = frappe.new_doc("Access Request")
	doc.update({"user": user, "source": "Console", "request_type": "Other", "reason": reason})
	changes = apply(
		doc, roles=roles, profile_action=profile_action, profiles=profiles, profile_mode=profile_mode
	)
	ensure_can_expire(valid_till, resolution, json.loads(changes["grant_log"]))
	doc.update(
		{
			"status": "Approved",
			"resolution": resolution,
			"decided_by": frappe.session.user,
			"decided_on": now_datetime(),
			"valid_till": valid_till,
			**changes,
		}
	)
	doc.flags.from_console = True
	doc.flags.ignore_permissions = True
	doc.insert()
	frappe.clear_cache(user=user)
	return {"name": doc.name, "title": doc.title}


def temporary_roles(users: list[str]) -> dict[str, dict[str, str]]:
	rows = frappe.get_all(
		"Access Request",
		filters={
			"status": "Approved",
			"resolution": "Role",
			"user": ["in", users],
			"valid_till": ["is", "set"],
		},
		fields=["user", "grant_log", "valid_till"],
		order_by="valid_till",
	)
	return {
		user: {
			role: str(row.valid_till)
			for row in rows
			if row.user == user
			for role in json.loads(row.grant_log or "{}").get("roles", [])
		}
		for user in {row.user for row in rows}
	}


def _require_doctype(doctype: str):
	if not frappe.db.exists("DocType", {"name": doctype, "istable": 0}):
		frappe.throw(_("Document type {0} not found").format(doctype), frappe.DoesNotExistError)


@frappe.whitelist()
def get_doctype_rights(doctype: str) -> list[str]:
	_require_manager()
	_require_doctype(doctype)
	return doctype_rights(doctype)


@frappe.whitelist()
def who_can(doctype: str, right: str) -> dict[str, str]:
	_require_manager()
	_require_doctype(doctype)
	if right not in doctype_rights(doctype):
		frappe.throw(_("Right {0} does not apply to {1}").format(right, _(doctype)))
	return rules.granting_roles(doctype_rows(doctype), right)
