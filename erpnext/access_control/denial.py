import json

import frappe
from frappe import _
from frappe.permissions import has_permission
from frappe.utils import strip_html

from erpnext.access_control import denial_rules
from erpnext.access_control import permission_rules as rules
from erpnext.access_control.permissions_engine import (
	_public_explanation,
	doctype_rights,
	explain,
	is_access_manager,
)

PSEUDO_ROLES = ("All", "Guest", "Desk User")


def visible_roles(roles) -> list[str]:
	return [role for role in roles if role not in PSEUDO_ROLES]


def _resolve_slug(slug: str) -> dict | None:
	if frappe.db.exists("Page", slug):
		return {"kind": "page", "page": slug}
	doctype = frappe.db.get_value("DocType", {"name": denial_rules.slug_to_name(slug), "istable": 0}, "name")
	return denial_rules.doctype_context(doctype, None, "read")


def _resolve_report(report: str) -> dict | None:
	if not frappe.db.exists("Report", report):
		return None
	doc = frappe.get_doc("Report", report)
	if (
		doc.is_permitted()
		and doc.ref_doctype
		and not has_permission(doc.ref_doctype, "report", print_logs=False)
	):
		return denial_rules.doctype_context(doc.ref_doctype, None, "report")
	return {"kind": "report", "report": report}


def _resolve_doctype(context: dict) -> dict | None:
	istable = frappe.db.get_value("DocType", context["doctype"], "istable")
	if istable is None or istable:
		return None
	if context["name"] and not frappe.db.exists(context["doctype"], context["name"]):
		return {**context, "name": None}
	return context


def resolve(context: dict | None) -> dict | None:
	if not context:
		return None
	resolvers = {
		"page_or_doctype": lambda: _resolve_slug(context["slug"]),
		"page": lambda: context if frappe.db.exists("Page", context["page"]) else None,
		"report": lambda: _resolve_report(context["report"]),
		"doctype": lambda: _resolve_doctype(context),
	}
	resolved = resolvers[context["kind"]]() if context["kind"] in resolvers else None
	return {**(resolved or {"kind": "other"}), "method": context.get("method")}


def _raised_denial() -> dict | None:
	denial = frappe.flags.get("permission_denial")
	return denial and denial_rules.doctype_context(denial["doctype"], denial["name"], denial["ptype"])


def attach_denial_context(response=None, request=None):
	if response is None or request is None or response.status_code != 403:
		return
	if response.mimetype != "application/json" or frappe.session.user in (None, "Guest"):
		return
	body = json.loads(response.get_data(as_text=True) or "{}")
	if not isinstance(body, dict):
		return
	requested = denial_rules.denial_context(request.path, request.method, frappe.local.form_dict)
	context = resolve(denial_rules.with_raised(requested, _raised_denial()))
	response.set_data(json.dumps({**body, "_access_denied": context or {"kind": "other"}}, default=str))


def _object_roles(parenttype: str, field: str, name: str) -> tuple[list[str], list[str]]:
	standard = frappe.get_all("Has Role", filters={"parenttype": parenttype, "parent": name}, pluck="role")
	custom_name = frappe.db.get_value("Custom Role", {field: name})
	custom = (
		frappe.get_all("Has Role", filters={"parenttype": "Custom Role", "parent": custom_name}, pluck="role")
		if custom_name
		else []
	)
	return standard, custom


def _role_denial(granting: frozenset, roles, title: str) -> dict:
	allowed = not granting or bool(granting & set(roles))
	return {
		"title": title,
		"granting_roles": {role: rules.ALL for role in sorted(granting)},
		"allowed": allowed,
		"blockers": [] if allowed else ["no_role"],
	}


def _page_denial(page: str, roles) -> dict:
	title = _(frappe.db.get_value("Page", page, "title") or page)
	return _role_denial(rules.page_roles(*_object_roles("Page", "page", page)), roles, title)


def _report_denial(report: str, roles) -> dict:
	return _role_denial(rules.report_roles(*_object_roles("Report", "report", report)), roles, _(report))


def _doctype_denial(context: dict, user: str) -> dict:
	result = explain(context["doctype"], context.get("ptype") or "read", context.get("name"), user)
	public = result if is_access_manager(user) else _public_explanation(result)
	title = " ".join(part for part in (_(context["doctype"]), context.get("name")) if part)
	return {
		"title": title,
		**{key: value for key, value in public.items() if key not in ("debug_log", "facts", "user_roles")},
	}


def describe(context: dict, user: str) -> dict:
	roles = frappe.get_roles(user)
	kind = context.get("kind")
	if kind == "doctype":
		return _doctype_denial(context, user)
	if kind == "page":
		return _page_denial(context["page"], roles)
	if kind == "report":
		return _report_denial(context["report"], roles)
	return {"title": None, "granting_roles": {}, "allowed": False, "blockers": []}


def request_fields(context: dict) -> dict:
	kind = context.get("kind")
	if kind == "doctype":
		return {
			"request_type": "Document Type",
			"reference_doctype": context["doctype"],
			"reference_name": context.get("name"),
			"ptype": context.get("ptype") or "read",
		}
	if kind == "page":
		return {"request_type": "Page", "page": context["page"]}
	if kind == "report":
		return {"request_type": "Report", "report": context["report"]}
	return {"request_type": "Other"}


def pending_request(user: str, context: dict) -> dict | None:
	fields = request_fields(context)
	if fields["request_type"] == "Other":
		return None
	filters = {
		"user": user,
		"status": "Pending",
		**{key: value or ("is", "not set") for key, value in fields.items()},
	}
	return frappe.db.get_value("Access Request", filters, ["name", "creation"], as_dict=True)


def access_managers(exclude: str | None = None) -> list[str]:
	users = frappe.db.sql(
		"""select distinct hr.parent from `tabHas Role` hr join tabUser u on u.name = hr.parent
		where hr.parenttype = 'User' and hr.role = 'Access Manager' and u.enabled = 1
		and u.name not in ('Administrator', 'Guest')""",
		pluck=True,
	)
	return [user for user in users if user != exclude]


def _context(value) -> dict:
	context = frappe.parse_json(value) if value else {}
	if not isinstance(context, dict):
		frappe.throw(_("Invalid access context"))
	return resolve(context) or {"kind": "other"}


REQUESTER_HIDDEN = ("granting_roles", "user_roles", "source", "workflow")


@frappe.whitelist()
def get_denial(context: str | dict | None = None) -> dict:
	context = _context(context)
	user = frappe.session.user
	return {
		"context": context,
		"pending": pending_request(user, context),
		"has_managers": bool(access_managers(exclude=user)),
		"can_request": user != "Administrator",
		"rights": doctype_rights(context["doctype"]) if context.get("kind") == "doctype" else [],
		**{key: value for key, value in describe(context, user).items() if key not in REQUESTER_HIDDEN},
	}


def _requested_rights(context: dict, rights) -> str | None:
	if context.get("kind") != "doctype":
		return None
	extra = frappe.parse_json(rights) if rights else []
	if not isinstance(extra, list):
		frappe.throw(_("Invalid list of rights"))
	return ",".join(rules.requested_rights(context.get("ptype"), extra, doctype_rights(context["doctype"])))


@frappe.whitelist()
def create_request(
	context: str | dict | None = None,
	reason: str | None = None,
	route: str | None = None,
	message: str | None = None,
	rights: str | list | None = None,
):
	context = _context(context)
	doc = frappe.get_doc(
		{
			"doctype": "Access Request",
			**request_fields(context),
			"ptypes": _requested_rights(context, rights),
			"reason": (reason or "").strip() or None,
			"route": (route or "")[:1000],
			"method": (context.get("method") or "")[:140],
			"message": strip_html(message or "")[:2000],
		}
	)
	doc.insert()
	return {"name": doc.name}
