import json

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
from frappe.model.document import Document
from frappe.permissions import get_user_permissions
from frappe.share import add_docshare
from frappe.utils import file_lock, now_datetime

from erpnext.access_control import permission_rules as rules
from erpnext.access_control.denial import access_managers, describe, visible_roles
from erpnext.access_control.permissions_engine import (
	_require_manager,
	explain,
	is_access_manager,
	role_delta,
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

	def before_insert(self):
		self.user = frappe.session.user
		self.status = "Pending"

	def validate(self):
		self.title = self.make_title()
		if self.status == "Pending":
			self.ensure_unique()

	def after_insert(self):
		self.db_set("diagnosis", as_json(diagnose_request(self)), update_modified=False)
		notify(
			access_managers(exclude=self.user),
			self,
			_("{0} requests access: {1}").format(self.full_name or self.user, self.title),
		)

	def make_title(self) -> str:
		titles = {
			"Document Type": lambda: " ".join(
				filter(
					None, (_(self.reference_doctype), self.reference_name, f"· {_(right_label(self.ptype))}")
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


def _role_candidates(doc, granting: dict, roles) -> dict:
	held = set(roles)
	offered = [role for role in granting if rules.is_grantable(role) and role not in held]
	candidates = [
		{
			"role": role,
			"scope": granting[role],
			"size": rules.delta_size(delta),
			"users": delta["users"],
			"role_profiles": delta["role_profiles"],
		}
		for role in offered[:MAX_CANDIDATES]
		for delta in (role_delta(doc.user, role),)
	]
	return {
		"candidates": rules.rank_candidates(candidates),
		"never_granted": [role for role in granting if not rules.is_grantable(role)],
	}


def _user_permission_candidates(doc) -> list[dict]:
	target = _reference_doc(doc)
	if not target:
		return []
	allowed = {
		allow: [entry.get("doc") for entry in entries]
		for allow, entries in get_user_permissions(doc.user).items()
	}
	meta = frappe.get_meta(doc.reference_doctype)
	links = [
		(doc.reference_doctype, target.name),
		*((field.options, target.get(field.fieldname)) for field in meta.get_link_fields() if field.options),
	]
	return rules.user_permission_candidates(links, allowed)


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
	share_rights = rules.share_rights_for(doc.ptype or "read") if _reference_doc(doc) else None
	return {
		"user": doc.user,
		"full_name": doc.full_name,
		"user_enabled": bool(frappe.db.get_value("User", doc.user, "enabled")),
		"own_request": doc.user == frappe.session.user,
		"user_roles": visible_roles(roles),
		"situation": situation,
		**_role_candidates(doc, situation.get("granting_roles") or {}, roles),
		"share_rights": list(share_rights) if share_rights else None,
		"user_permissions": _user_permission_candidates(doc),
		"role_profiles": _user_profiles(doc.user),
	}


def _save_role_profile(profile_doc, role: str):
	signature = profile_doc.get_signature()
	if profile_doc.is_locked:
		frappe.throw(
			_("Role profile {0} is still being applied to its users. Try again in a few minutes").format(
				profile_doc.name
			)
		)
	profile_doc.append("roles", {"role": role})
	profile_doc.save(ignore_permissions=True)
	frappe.db.after_rollback.add(lambda: file_lock.delete_lock(signature))


def _apply_role(user, role: str, profile_action: str | None) -> str | None:
	profiles = [row.role_profile for row in user.role_profiles]
	if not profiles:
		user.add_roles(role)
		return None
	if profile_action == "unlink":
		user.role_profiles = []
		user.role_profile_name = None
		user.append("roles", {"role": role})
		user.save(ignore_permissions=True)
		return _("Role profiles {0} were unlinked, the user keeps their roles directly").format(
			", ".join(profiles)
		)
	profile = (profile_action or "").removeprefix("profile:")
	if not profile_action or profile not in profiles:
		frappe.throw(_("Choose what to do with the user's role profile"))
	profile_doc = frappe.get_doc("Role Profile", profile)
	_save_role_profile(profile_doc, role)
	user.reload()
	user.save(ignore_permissions=True)
	holders = frappe.db.count("User Role Profile", {"parenttype": "User", "role_profile": profile})
	return _("Role {0} was added to role profile {1}, users with this profile: {2}").format(
		role, profile, holders
	)


def _grant_role(doc, role: str | None = None, profile_action: str | None = None, **_kwargs) -> dict:
	if not rules.is_grantable(role):
		frappe.throw(_("Role {0} cannot be granted through an access request").format(role))
	if not frappe.db.exists("Role", {"name": role, "disabled": 0}):
		frappe.throw(_("Role {0} not found").format(role))
	if role in frappe.get_roles(doc.user):
		frappe.throw(_("User {0} already has role {1}").format(doc.user, role))
	impact = role_delta(doc.user, role)
	profile_change = _apply_role(frappe.get_doc("User", doc.user), role, profile_action)
	if not frappe.db.exists("Has Role", {"parenttype": "User", "parent": doc.user, "role": role}):
		frappe.throw(_("Role {0} was not saved for user {1}").format(role, doc.user))
	return {"granted_role": role, "role_profile_change": profile_change, "impact": as_json(impact)}


def _grant_share(doc, share_rights=None, **_kwargs) -> dict:
	allowed = rules.share_rights_for(doc.ptype or "read") if _reference_doc(doc) else None
	if not allowed:
		frappe.throw(_("This access cannot be given by sharing the document"))
	chosen = [right for right in (frappe.parse_json(share_rights) or allowed) if right in rules.SHARE_RIGHTS]
	rights = list(dict.fromkeys(("read", *chosen)))
	add_docshare(
		doc.reference_doctype,
		doc.reference_name,
		doc.user,
		**{right: 1 for right in rights},
		flags={"ignore_share_permission": True},
	)
	return {"share_rights": ", ".join(rights), "impact": as_json({"share": rights})}


def _grant_user_permission(doc, allow: str | None = None, for_value: str | None = None, **_kwargs) -> dict:
	if {"allow": allow, "for_value": for_value} not in _user_permission_candidates(doc):
		frappe.throw(_("This User Permission does not widen the user's existing restrictions"))
	permission = frappe.get_doc(
		{
			"doctype": "User Permission",
			"user": doc.user,
			"allow": allow,
			"for_value": for_value,
			"apply_to_all_doctypes": 1,
		}
	).insert(ignore_permissions=True)
	return {
		"user_permission": permission.name,
		"impact": as_json({"user_permission": {"allow": allow, "for_value": for_value}}),
	}


GRANTS = {"Role": _grant_role, "Share": _grant_share, "User Permission": _grant_user_permission}


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
	profile_action: str | None = None,
	share_rights=None,
	allow: str | None = None,
	for_value: str | None = None,
	note: str | None = None,
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
		profile_action=profile_action,
		share_rights=share_rights,
		allow=allow,
		for_value=for_value,
	)
	_decide(doc, "Approved", note, {"resolution": resolution, **changes})
	frappe.clear_cache(user=doc.user)
	notify_requester(doc)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def reject(name: str, note: str | None = None):
	doc = _load_pending(name)
	_decide(doc, "Rejected", note)
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
