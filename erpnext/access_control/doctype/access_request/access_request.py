import json

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
from frappe.model.document import Document
from frappe.permissions import get_user_permissions, setup_custom_perms
from frappe.share import add_docshare
from frappe.utils import file_lock, now_datetime

from erpnext.access_control import permission_rules as rules
from erpnext.access_control.denial import access_managers, describe, visible_roles
from erpnext.access_control.permissions_engine import (
	PSEUDO_ROLES,
	_raw_rows,
	_require_manager,
	_role_holders,
	doctype_rights,
	doctype_rows,
	explain,
	is_access_manager,
	role_delta,
	roles_delta,
)

KEY_FIELDS = ("request_type", "reference_doctype", "reference_name", "ptype", "page", "report")
MAX_CANDIDATES = 15


def as_json(value) -> str:
	return json.dumps(value, default=str, ensure_ascii=False, indent=1)


class AccessRequest(Document):
	def context(self) -> dict:
		contexts = {
			"Document Type": {
				"kind": "doctype",
				"doctype": self.reference_doctype,
				"name": self.reference_name or None,
				"ptype": self.ptype or "read",
			},
			"Page": {"kind": "page", "page": self.page},
			"Report": {"kind": "report", "report": self.report},
		}
		return contexts.get(self.request_type, {"kind": "other"})

	def rights(self) -> list[str]:
		return [right for right in (self.ptypes or "").split(",") if right] or [self.ptype or "read"]

	def before_insert(self):
		self.user = frappe.session.user
		self.status = "Pending"

	def onload(self):
		self.set_onload(
			"revocable", self.status == "Approved" and rules.is_revocable(self.resolution, _grant_log(self))
		)

	def validate(self):
		self.title = self.make_title()
		if self.status == "Pending":
			self.ensure_unique()

	def after_insert(self):
		self.db_set("diagnosis", as_json(diagnose_request(self)), update_modified=False)
		notify(
			access_managers(exclude=self.user),
			self,
			_("{0} requests access: {1}").format(self.user_full_name or self.user, self.title),
		)

	def make_title(self) -> str:
		titles = {
			"Document Type": lambda: " ".join(
				filter(
					None,
					(
						_(self.reference_doctype),
						self.reference_name,
						"· " + ", ".join(_(right_label(right)) for right in self.rights()),
					),
				)
			),
			"Page": lambda: _("Page {0}").format(
				_(frappe.db.get_value("Page", self.page, "title") or self.page)
			),
			"Report": lambda: _("Report {0}").format(_(self.report)),
		}
		return titles.get(self.request_type, lambda: _("Other access"))()

	def ensure_unique(self):
		if self.request_type == "Other":
			return
		filters = {
			"user": self.user,
			"status": "Pending",
			"name": ("!=", self.name or ""),
			**{field: self.get(field) or ("is", "not set") for field in KEY_FIELDS},
		}
		if existing := frappe.db.get_value("Access Request", filters):
			frappe.throw(_("You already have a pending request {0} for this access").format(existing))


def right_label(ptype: str | None) -> str:
	return (ptype or "read").replace("_", " ").title()


def diagnose_request(doc) -> dict:
	context = doc.context()
	roles = visible_roles(frappe.get_roles(doc.user))
	if context["kind"] != "doctype":
		return {"user_roles": roles, **describe(context, doc.user)}
	result = explain(context["doctype"], context["ptype"], context["name"], doc.user)
	return {key: value for key, value in result.items() if key != "debug_log"}


def notify(users: list[str], doc, subject: str):
	if not users:
		return
	enqueue_create_notification(
		users,
		{
			"type": "Alert",
			"document_type": "Access Request",
			"document_name": doc.name,
			"subject": subject,
			"from_user": frappe.session.user,
		},
	)


def notify_requester(doc):
	subjects = {
		"Approved": _("Access granted: {0}. Reload the page to use it"),
		"Rejected": _("Access request rejected: {0}"),
		"Revoked": _("Access revoked: {0}"),
	}
	notify([doc.user], doc, subjects[doc.status].format(doc.title))
	frappe.publish_realtime(
		"access_request_decided",
		{"name": doc.name, "status": doc.status, "title": doc.title, "note": doc.decision_note},
		user=doc.user,
		after_commit=True,
	)


def _load_pending(name: str):
	_require_manager()
	doc = frappe.get_doc("Access Request", name)
	if doc.status != "Pending":
		frappe.throw(_("Request {0} is already {1}").format(name, _(doc.status)))
	return doc


def _reference_doc(doc):
	if doc.request_type != "Document Type" or not doc.reference_name:
		return None
	if not frappe.db.exists(doc.reference_doctype, doc.reference_name):
		return None
	return frappe.get_doc(doc.reference_doctype, doc.reference_name)


def _situation(doc) -> dict:
	context = doc.context()
	if context["kind"] == "doctype" and context["name"] and not _reference_doc(doc):
		context = {**context, "name": None}
	if context["kind"] == "doctype":
		return {
			key: value
			for key, value in explain(context["doctype"], context["ptype"], context["name"], doc.user).items()
			if key not in ("debug_log", "user_roles")
		}
	return describe(context, doc.user)


def _rights_context(doc, chosen: list | None = None) -> dict | None:
	if doc.request_type != "Document Type" or not doc.reference_doctype:
		return None
	rights = doctype_rights(doc.reference_doctype)
	return {
		"rights": rights,
		"requested": rules.chosen_rights(rights, chosen, doc.rights()),
		"rows": doctype_rows(doc.reference_doctype),
	}


def _granting(situation: dict, context: dict | None) -> dict:
	if not context:
		return situation.get("granting_roles") or {}
	return rules.merge_granting(
		rules.granting_roles(context["rows"], right) for right in context["requested"]
	)


def _with_pseudo(roles, current) -> list[str]:
	return [*roles, *(role for role in current if role in PSEUDO_ROLES)]


def _coverage_fields(context: dict | None, roles) -> dict:
	if not context:
		return {}
	covered = rules.coverage(context["rows"], roles, context["rights"])
	return {"coverage": covered, "missing": rules.missing_rights(covered, context["requested"])}


def _role_candidates(doc, granting: dict, roles, context: dict | None) -> dict:
	held = set(roles)
	pool = [role for role in granting if rules.is_grantable(role) and role not in held]
	covered = {role: _coverage_fields(context, [*roles, role]) for role in pool}
	offered = sorted(pool, key=lambda role: len(covered[role].get("missing") or ()))
	candidates = [
		{
			"role": role,
			"scope": granting[role],
			"size": rules.delta_size(delta),
			"users": delta["users"],
			"role_profiles": delta["role_profiles"],
			**covered[role],
		}
		for role in offered[:MAX_CANDIDATES]
		for delta in (role_delta(doc.user, role),)
	]
	return {
		"candidates": rules.rank_candidates(candidates),
		"never_granted": [role for role in granting if not rules.is_grantable(role)],
	}


def _open_role_candidates(roles) -> dict:
	held = set(roles)
	holders = dict(
		frappe.db.sql(
			"""select hr.role, count(distinct hr.parent) from `tabHas Role` hr join tabUser u on u.name = hr.parent
			where hr.parenttype = 'User' and u.enabled = 1 group by hr.role"""
		)
	)
	offered = sorted(
		frappe.get_all("Role", filters={"disabled": 0, "desk_access": 1}, pluck="name"),
		key=lambda role: _(role).casefold(),
	)
	return {
		"candidates": [
			{"role": role, "scope": None, "size": None, "users": holders.get(role, 0), "role_profiles": []}
			for role in offered
			if rules.is_grantable(role) and role not in held
		],
		"never_granted": [],
	}


def _candidates(doc, granting: dict, roles, context: dict | None) -> dict:
	if doc.request_type == "Other":
		return _open_role_candidates(roles)
	return _role_candidates(doc, granting, roles, context)


def _link_values(row) -> list[tuple[str, str]]:
	return [
		(field.options, row.get(field.fieldname))
		for field in frappe.get_meta(row.doctype).get_link_fields()
		if field.options and not field.ignore_user_permissions
	]


def _user_permission_inputs(doc) -> tuple[list, dict]:
	target = _reference_doc(doc)
	if not target:
		return [], {}
	allowed = {
		allow: rules.allowed_values(entries, doc.reference_doctype)
		for allow, entries in get_user_permissions(doc.user).items()
	}
	links = [
		(doc.reference_doctype, target.name),
		*_link_values(target),
		*(link for row in target.get_all_children() for link in _link_values(row)),
	]
	return links, {allow: values for allow, values in allowed.items() if values}


def _user_permission_candidates(doc) -> list[dict]:
	return rules.user_permission_candidates(*_user_permission_inputs(doc))


def _unavailable(doc) -> dict:
	has_document = bool(_reference_doc(doc))
	reasons = {
		"Document Share": rules.share_unavailable(has_document, doc.ptype or "read"),
		"User Permission": rules.user_permission_unavailable(has_document, *_user_permission_inputs(doc)),
	}
	return {resolution: reason for resolution, reason in reasons.items() if reason}


def _current_profiles(user: str) -> list[str]:
	return frappe.get_all(
		"User Role Profile",
		filters={"parenttype": "User", "parent": user},
		pluck="role_profile",
		order_by="idx",
	)


def _roles_by_profile() -> dict[str, list[str]]:
	rows = frappe.get_all("Has Role", filters={"parenttype": "Role Profile"}, fields=["parent", "role"])
	return {
		profile: sorted(row.role for row in rows if row.parent == profile)
		for profile in sorted({row.parent for row in rows})
	}


def _roles_after_profile(
	user: str, profiles: list[str], mode: str, by_profile: dict | None = None
) -> list[str]:
	by_profile = by_profile or _roles_by_profile()
	current = [by_profile.get(name, []) for name in _current_profiles(user)]
	chosen = [role for profile in profiles for role in by_profile.get(profile, [])]
	return rules.roles_after_profile(mode, current, chosen)


def _profile_delta(user: str, profiles: list[str], mode: str, by_profile: dict | None = None) -> dict:
	return roles_delta(user, _roles_after_profile(user, profiles, mode, by_profile))


def _profile_candidates(doc, granting: dict, context: dict | None) -> list[dict]:
	by_profile = _roles_by_profile()
	current = set(_current_profiles(doc.user))
	current_roles = frappe.get_roles(doc.user)
	offered = [
		profile
		for profile, roles in by_profile.items()
		if profile not in current and rules.is_offerable_profile(roles, granting)
	]
	return rules.rank_profiles(
		{
			"profile": profile,
			"roles": by_profile[profile],
			"size": rules.delta_size(delta),
			"lost_roles": delta["lost_roles"],
			"users": frappe.db.count("User Role Profile", {"parenttype": "User", "role_profile": profile}),
			**_coverage_fields(
				context,
				_with_pseudo(_roles_after_profile(doc.user, [profile], "add", by_profile), current_roles),
			),
		}
		for profile in offered[:MAX_CANDIDATES]
		for delta in (_profile_delta(doc.user, [profile], "add", by_profile),)
	)


def _user_profiles(user: str) -> list[dict]:
	profiles = frappe.get_all(
		"User Role Profile", filters={"parenttype": "User", "parent": user}, pluck="role_profile"
	)
	return [
		{
			"name": profile,
			"users": frappe.db.count("User Role Profile", {"parenttype": "User", "role_profile": profile}),
		}
		for profile in profiles
	]


@frappe.whitelist()
def get_approval_options(name: str) -> dict:
	doc = _load_pending(name)
	roles = frappe.get_roles(doc.user)
	situation = _situation(doc)
	context = _rights_context(doc)
	granting = _granting(situation, context)
	share_rights = rules.share_rights_for(doc.ptype or "read") if _reference_doc(doc) else None
	profile_candidates = _profile_candidates(doc, granting, context)
	right_roles = [] if _role_right_unavailable(doc, context) else _right_roles(roles)
	role_right = _role_right_unavailable(doc, context) or (None if right_roles else "no_right_roles")
	unavailable = {
		**_unavailable(doc),
		**({} if profile_candidates else {"Role Profile": "no_profile_grants"}),
		**({"Role Right": role_right} if role_right else {}),
	}
	return {
		"name": doc.name,
		"user": doc.user,
		"full_name": doc.user_full_name,
		"user_enabled": bool(frappe.db.get_value("User", doc.user, "enabled")),
		"own_request": doc.user == frappe.session.user,
		"user_roles": visible_roles(roles),
		"situation": situation,
		**_candidates(doc, granting, roles, context),
		"rights": context["rights"] if context else [],
		"requested_rights": context["requested"] if context else [],
		"current_coverage": _coverage_fields(context, roles).get("coverage", {}),
		"share_rights": list(share_rights) if share_rights else None,
		"user_permissions": _user_permission_candidates(doc),
		"profile_candidates": profile_candidates,
		"unavailable": unavailable,
		"role_profiles": _user_profiles(doc.user),
		"right_roles": right_roles,
	}


def _save_role_profile(profile_doc, roles: list[str]):
	signature = profile_doc.get_signature()
	if profile_doc.is_locked:
		frappe.throw(
			_("Role profile {0} is still being applied to its users. Try again in a few minutes").format(
				profile_doc.name
			)
		)
	profile_doc.set("roles", [{"role": role} for role in roles])
	profile_doc.save(ignore_permissions=True)
	frappe.db.after_rollback.add(lambda: file_lock.delete_lock(signature))


def _apply_roles(user, roles: list[str], profile_action: str | None) -> str | None:
	profiles = [row.role_profile for row in user.role_profiles]
	user.flags.ignore_permissions = True
	if not profiles:
		user.add_roles(*roles)
		return None
	if profile_action == "unlink":
		user.role_profiles = []
		user.role_profile_name = None
		for role in roles:
			user.append("roles", {"role": role})
		user.save(ignore_permissions=True)
		return _("Role profiles {0} were unlinked, the user keeps their roles directly").format(
			", ".join(profiles)
		)
	profile = (profile_action or "").removeprefix("profile:")
	if not profile_action or profile not in profiles:
		frappe.throw(_("Choose what to do with the user's role profile"))
	profile_doc = frappe.get_doc("Role Profile", profile)
	_save_role_profile(profile_doc, [*(row.role for row in profile_doc.roles), *roles])
	user.reload()
	user.save(ignore_permissions=True)
	holders = frappe.db.count("User Role Profile", {"parenttype": "User", "role_profile": profile})
	return _("Roles {0} were added to role profile {1}, users with this profile: {2}").format(
		", ".join(map(_, roles)), profile, holders
	)


def _chosen(values) -> list:
	parsed = frappe.parse_json(values) if isinstance(values, str) else values
	if not isinstance(parsed, list):
		return []
	return [value for index, value in enumerate(parsed) if value not in parsed[:index]]


def _grant_role(doc, roles=None, profile_action: str | None = None, **_kwargs) -> dict:
	roles = _chosen(roles)
	if not roles:
		frappe.throw(_("Choose at least one role"))
	held = frappe.get_roles(doc.user)
	for role in roles:
		if not rules.is_grantable(role):
			frappe.throw(_("Role {0} cannot be granted through an access request").format(role))
		if not frappe.db.exists("Role", {"name": role, "disabled": 0}):
			frappe.throw(_("Role {0} not found").format(role))
		if role in held:
			frappe.throw(_("User {0} already has role {1}").format(doc.user, role))
	impact = roles_delta(doc.user, [*held, *roles])
	user = frappe.get_doc("User", doc.user)
	log = rules.role_grant_log(roles, [row.role_profile for row in user.role_profiles], profile_action)
	profile_change = _apply_roles(user, roles, profile_action)
	saved = set(frappe.get_all("Has Role", filters={"parenttype": "User", "parent": doc.user}, pluck="role"))
	if missing := [role for role in roles if role not in saved]:
		frappe.throw(_("Roles {0} were not saved for user {1}").format(", ".join(missing), doc.user))
	return {
		"granted_roles": ", ".join(roles),
		"role_profile_change": profile_change,
		"impact": as_json(impact),
		"grant_log": as_json(log),
	}


def _grant_profile(doc, profiles=None, profile_mode: str | None = None, **_kwargs) -> dict:
	profiles = _chosen(profiles)
	if not profiles:
		frappe.throw(_("Choose at least one role profile"))
	context = _rights_context(doc)
	offered = {
		candidate["profile"]
		for candidate in _profile_candidates(doc, _granting(_situation(doc), context), context)
	}
	for profile in profiles:
		if profile not in offered:
			frappe.throw(_("Role profile {0} cannot be assigned through this request").format(profile))
	current = _current_profiles(doc.user)
	mode = profile_mode if current else "add"
	if mode not in rules.PROFILE_MODES:
		frappe.throw(_("Choose what to do with the user's current role profiles"))
	impact = _profile_delta(doc.user, profiles, mode)
	user = frappe.get_doc("User", doc.user)
	log = {
		"profiles": profiles,
		"mode": mode,
		"previous_profiles": current,
		"previous_roles": [row.role for row in user.roles],
	}
	user.role_profile_name = None
	if mode == "replace":
		user.role_profiles = []
	for profile in profiles:
		user.append("role_profiles", {"role_profile": profile})
	user.save(ignore_permissions=True)
	held = set(frappe.get_all("Has Role", filters={"parenttype": "User", "parent": doc.user}, pluck="role"))
	by_profile = _roles_by_profile()
	if missing := [profile for profile in profiles if not set(by_profile.get(profile, [])) <= held]:
		frappe.throw(_("Role profiles {0} were not applied to user {1}").format(", ".join(missing), doc.user))
	change = [
		_("Replaced role profiles: {0}").format(", ".join(current))
		if mode == "replace" and current
		else None,
		_("Removed roles: {0}").format(", ".join(map(_, impact["lost_roles"])))
		if impact["lost_roles"]
		else None,
	]
	return {
		"granted_role_profiles": ", ".join(profiles),
		"role_profile_change": "\n".join(filter(None, change)) or None,
		"impact": as_json(impact),
		"grant_log": as_json(log),
	}


def _grant_share(doc, share_rights=None, **_kwargs) -> dict:
	allowed = rules.share_rights_for(doc.ptype or "read") if _reference_doc(doc) else None
	if not allowed:
		frappe.throw(_("This access cannot be given by sharing the document"))
	chosen = [right for right in (frappe.parse_json(share_rights) or allowed) if right in rules.SHARE_RIGHTS]
	rights = list(dict.fromkeys(("read", *chosen)))
	key = {"share_doctype": doc.reference_doctype, "share_name": doc.reference_name, "user": doc.user}
	previous = frappe.db.get_value("DocShare", key, list(rules.SHARE_RIGHTS), as_dict=True)
	add_docshare(
		doc.reference_doctype,
		doc.reference_name,
		doc.user,
		**{right: 1 for right in rights},
		flags={"ignore_share_permission": True},
	)
	log = {"share": frappe.db.get_value("DocShare", key), "previous": previous}
	return {
		"share_rights": ", ".join(rights),
		"impact": as_json({"share": rights}),
		"grant_log": as_json(log),
	}


def _grant_user_permission(doc, user_permissions=None, **_kwargs) -> dict:
	chosen = [
		{"allow": entry.get("allow"), "for_value": entry.get("for_value")}
		for entry in _chosen(user_permissions)
		if isinstance(entry, dict)
	]
	if not chosen:
		frappe.throw(_("Choose at least one value to allow"))
	offered = _user_permission_candidates(doc)
	if any(entry not in offered for entry in chosen):
		frappe.throw(_("This User Permission does not widen the user's existing restrictions"))
	granted = [
		{
			**entry,
			"user_permission": frappe.get_doc(
				{"doctype": "User Permission", "user": doc.user, "apply_to_all_doctypes": 1, **entry}
			)
			.insert(ignore_permissions=True)
			.name,
		}
		for entry in chosen
	]
	return {
		"granted_values": "\n".join(f"{_(entry['allow'])}: {entry['for_value']}" for entry in chosen),
		"impact": as_json({"user_permissions": chosen}),
		"grant_log": as_json({"user_permissions": granted}),
	}


def _role_right_unavailable(doc, context: dict | None) -> str | None:
	module = frappe.db.get_value("DocType", doc.reference_doctype, "module") if context else None
	return rules.role_right_unavailable(bool(context), doc.reference_doctype, module)


def _right_roles(roles) -> list[dict]:
	approver = frappe.get_roles()
	return [
		{"role": role, **_role_holders(role)}
		for role in visible_roles(roles)
		if not rules.role_right_refusal(role, approver)
	]


def _role_right_plan(doc, role: str | None, rights) -> dict:
	context = _rights_context(doc, _parse_rights(rights))
	reason = _role_right_unavailable(doc, context)
	if reason:
		frappe.throw(_("Rights of this document type cannot be changed through an access request"))
	if role not in frappe.get_roles(doc.user):
		frappe.throw(_("User {0} does not have role {1}").format(doc.user, role))
	editable = [right for right in context["requested"] if right in _right_fields()]
	return {
		"context": context,
		"refusal": rules.role_right_refusal(role, frappe.get_roles()),
		"add": rules.rights_to_add(context["rows"], role, editable),
	}


ROLE_RIGHT_REFUSALS = {
	"never_granted": lambda role: _("Rights of role {0} cannot be changed through an access request").format(
		role
	),
	"own_role": lambda role: _(
		"You have role {0} yourself, so only a System Manager can change its rights"
	).format(role),
}


@frappe.whitelist()
def get_role_right_preview(name: str, role: str, rights: str | list | None = None) -> dict:
	doc = _load_pending(name)
	plan = _role_right_plan(doc, role, rights)
	context = plan["context"]
	after = rules.rows_with_rights(context["rows"], role, plan["add"])
	return {
		"role": role,
		"refusal": plan["refusal"],
		"refusal_text": ROLE_RIGHT_REFUSALS[plan["refusal"]](role) if plan["refusal"] else None,
		"add": plan["add"],
		"custom": bool(frappe.db.exists("Custom DocPerm", {"parent": doc.reference_doctype})),
		"coverage": rules.coverage(after, frappe.get_roles(doc.user), context["rights"]),
		**_role_holders(role),
	}


def _right_fields() -> list[str]:
	return [
		field.fieldname
		for field in frappe.get_meta("Custom DocPerm").fields
		if field.fieldtype == "Check" and field.fieldname != "if_owner"
	]


def _custom_names(doctype: str) -> list[str]:
	return frappe.get_all("Custom DocPerm", filters={"parent": doctype}, pluck="name", order_by="name")


def _add_role_rights(doctype: str, role: str, rights: list[str]) -> dict:
	before = set(_custom_names(doctype))
	setup_custom_perms(doctype)
	restored = sorted(set(_custom_names(doctype)) - before)
	key = {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}
	existing = frappe.db.get_value("Custom DocPerm", key)
	row = (
		frappe.get_doc("Custom DocPerm", existing)
		if existing
		else frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parenttype": "DocType",
				"parentfield": "permissions",
				**key,
				**dict.fromkeys(_right_fields(), 0),
			}
		)
	)
	row.update({right: 1 for right in rights})
	row.save(ignore_permissions=True)
	return {
		"doctype": doctype,
		"role": role,
		"row": row.name,
		"created": not existing,
		"added": rights,
		"restored": restored,
	}


def _grant_role_right(doc, role: str | None = None, rights=None, **_kwargs) -> dict:
	plan = _role_right_plan(doc, role, rights)
	if plan["refusal"]:
		frappe.throw(ROLE_RIGHT_REFUSALS[plan["refusal"]](role), frappe.PermissionError)
	if not plan["add"]:
		frappe.throw(_("Role {0} already gives these rights on {1}").format(role, _(doc.reference_doctype)))
	holders = _role_holders(role)
	change = _add_role_rights(doc.reference_doctype, role, plan["add"])
	return {
		"granted_roles": role,
		"grant_log": as_json(change),
		"impact": as_json({**change, **holders}),
	}


def _revert_role_rights(change: dict):
	doctype = change["doctype"]
	if frappe.db.exists("Custom DocPerm", change["row"]):
		row = frappe.get_doc("Custom DocPerm", change["row"])
		row.update({right: 0 for right in change["added"]})
		if change["created"] and not any(row.get(field) for field in _right_fields()):
			frappe.delete_doc("Custom DocPerm", row.name, ignore_permissions=True, force=True)
		else:
			row.save(ignore_permissions=True)
	if change["restored"] and _matches_standard(doctype):
		for name in _custom_names(doctype):
			frappe.delete_doc("Custom DocPerm", name, ignore_permissions=True, force=True)
	frappe.clear_cache(doctype=doctype)


def _matches_standard(doctype: str) -> bool:
	rights = doctype_rights(doctype)
	return rules.same_rows(
		rules.normalize_rows(_raw_rows("DocPerm", {"parent": doctype}), rights),
		rules.normalize_rows(_raw_rows("Custom DocPerm", {"parent": doctype}), rights),
	)


GRANTS = {
	"Role": _grant_role,
	"Role Right": _grant_role_right,
	"Role Profile": _grant_profile,
	"Document Share": _grant_share,
	"User Permission": _grant_user_permission,
}


def _decide(doc, status: str, note: str | None, changes: dict | None = None):
	doc.update(
		{
			"status": status,
			"decided_by": frappe.session.user,
			"decided_on": now_datetime(),
			"decision_note": (note or "").strip() or None,
			**(changes or {}),
		}
	)
	doc.flags.ignore_permissions = True
	doc.save()


@frappe.whitelist()
def approve(
	name: str,
	resolution: str,
	role: str | None = None,
	roles=None,
	profile_action: str | None = None,
	share_rights=None,
	user_permissions=None,
	note: str | None = None,
	profiles=None,
	profile_mode: str | None = None,
	rights=None,
):
	doc = _load_pending(name)
	if doc.user == frappe.session.user:
		frappe.throw(_("You cannot approve your own access request"), frappe.PermissionError)
	if not frappe.db.get_value("User", doc.user, "enabled"):
		frappe.throw(_("User {0} is disabled").format(doc.user))
	if resolution not in GRANTS:
		frappe.throw(_("Choose how to grant access"))
	changes = GRANTS[resolution](
		doc,
		role=role,
		roles=roles,
		profile_action=profile_action,
		profiles=profiles,
		profile_mode=profile_mode,
		share_rights=share_rights,
		user_permissions=user_permissions,
		rights=rights,
	)
	_decide(
		doc,
		"Approved",
		note,
		{"resolution": resolution, "approved_rights": _approved_rights(doc, rights), **changes},
	)
	frappe.clear_cache(user=doc.user)
	notify_requester(doc)
	return {"name": doc.name, "status": doc.status}


def _parse_rights(rights) -> list | None:
	chosen = frappe.parse_json(rights) if rights else None
	return chosen if isinstance(chosen, list) else None


def _approved_rights(doc, rights) -> str | None:
	context = _rights_context(doc)
	chosen = _parse_rights(rights)
	if not context or chosen is None:
		return None
	return ",".join(right for right in context["rights"] if right in chosen) or None


@frappe.whitelist()
def get_candidates(name: str, rights: str | list | None = None) -> dict:
	doc = _load_pending(name)
	context = _rights_context(doc, _parse_rights(rights))
	granting = _granting(_situation(doc), context)
	return {
		**_candidates(doc, granting, frappe.get_roles(doc.user), context),
		"profile_candidates": _profile_candidates(doc, granting, context),
	}


@frappe.whitelist()
def get_coverage(name: str, roles=None, profiles=None, mode: str = "add") -> dict:
	doc = _load_pending(name)
	context = _rights_context(doc)
	if not context:
		return {}
	if mode not in rules.PROFILE_MODES:
		frappe.throw(_("Choose what to do with the user's current role profiles"))
	current = frappe.get_roles(doc.user)
	profiles = _chosen(profiles)
	after = (
		_with_pseudo(_roles_after_profile(doc.user, profiles, mode), current)
		if profiles
		else [*current, *_chosen(roles)]
	)
	return rules.coverage(context["rows"], after, context["rights"])


@frappe.whitelist()
def get_roles_delta(name: str, roles=None) -> dict:
	doc = _load_pending(name)
	return roles_delta(doc.user, [*frappe.get_roles(doc.user), *_chosen(roles)])


@frappe.whitelist()
def get_profile_delta(name: str, profiles=None, mode: str = "add") -> dict:
	doc = _load_pending(name)
	if mode not in rules.PROFILE_MODES:
		frappe.throw(_("Choose what to do with the user's current role profiles"))
	profiles = _chosen(profiles)
	if missing := [profile for profile in profiles if not frappe.db.exists("Role Profile", profile)]:
		frappe.throw(_("Role profile {0} not found").format(", ".join(missing)), frappe.DoesNotExistError)
	return _profile_delta(doc.user, profiles, mode)


@frappe.whitelist()
def reject(name: str, note: str | None = None):
	doc = _load_pending(name)
	_decide(doc, "Rejected", note)
	notify_requester(doc)
	return {"name": doc.name, "status": doc.status}


def _revert_role(doc, log: dict):
	user = frappe.get_doc("User", doc.user)
	user.flags.ignore_permissions = True
	user.remove_roles(*log["roles"])


def _revert_share(doc, log: dict):
	if not log.get("share") or not frappe.db.exists("DocShare", log["share"]):
		return
	if not log.get("previous"):
		frappe.delete_doc(
			"DocShare", log["share"], ignore_permissions=True, flags={"ignore_share_permission": True}
		)
		return
	share = frappe.get_doc("DocShare", log["share"])
	share.update(log["previous"])
	share.flags.ignore_share_permission = True
	share.save(ignore_permissions=True)


def _revert_user_permission(doc, log: dict):
	for entry in log["user_permissions"]:
		if frappe.db.exists("User Permission", entry["user_permission"]):
			frappe.delete_doc(
				"User Permission", entry["user_permission"], ignore_permissions=True, force=True
			)


REVERTS = {
	"Role": _revert_role,
	"Role Right": lambda doc, log: _revert_role_rights(log),
	"Document Share": _revert_share,
	"User Permission": _revert_user_permission,
}


def _grant_log(doc) -> dict | None:
	return json.loads(doc.grant_log) if doc.grant_log else None


def _load_revocable(name: str):
	_require_manager()
	doc = frappe.get_doc("Access Request", name)
	if doc.status != "Approved" or not rules.is_revocable(doc.resolution, _grant_log(doc)):
		frappe.throw(_("Request {0} has no change that can be revoked").format(name))
	return doc


@frappe.whitelist()
def get_revoke_preview(name: str) -> dict:
	doc = _load_revocable(name)
	log = _grant_log(doc)
	current = frappe.get_roles(doc.user)
	after = rules.roles_after_revoke(doc.resolution, log, current)
	return {
		"resolution": doc.resolution,
		"log": log,
		"delta": roles_delta(doc.user, _with_pseudo(after, current)) if after is not None else None,
	}


@frappe.whitelist()
def revoke(name: str, note: str | None = None):
	doc = _load_revocable(name)
	REVERTS[doc.resolution](doc, _grant_log(doc))
	doc.update(
		{
			"status": "Revoked",
			"revoked_by": frappe.session.user,
			"revoked_on": now_datetime(),
			"revoke_note": (note or "").strip() or None,
		}
	)
	doc.flags.ignore_permissions = True
	doc.save()
	frappe.clear_cache(user=doc.user)
	notify_requester(doc)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def cancel_request(name: str):
	doc = frappe.get_doc("Access Request", name)
	if doc.user != frappe.session.user and not is_access_manager():
		frappe.throw(_("You can cancel only your own requests"), frappe.PermissionError)
	if doc.status != "Pending":
		frappe.throw(_("Request {0} is already {1}").format(name, _(doc.status)))
	_decide(doc, "Cancelled", None)
	return {"name": doc.name, "status": doc.status}
