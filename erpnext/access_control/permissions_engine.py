from operator import itemgetter

import frappe
from frappe import _
from frappe.core.doctype.permission_type.permission_type import get_doctype_ptype_map
from frappe.model.workflow import get_workflow_name
from frappe.permissions import (
	_pop_debug_log,
	has_controller_permissions,
	has_permission,
	has_user_permission,
	std_rights,
)

from erpnext.access_control import permission_rules as rules

MANAGER_ROLES = ("Access Manager", "System Manager")
SHAREABLE_RIGHTS = ("read", "write", "share", "submit", "email", "print")


def is_access_manager(user: str | None = None) -> bool:
	return bool(set(frappe.get_roles(user)) & set(MANAGER_ROLES))


def _require_manager():
	if not is_access_manager():
		frappe.throw(_("Only Access Manager or System Manager can do this"), frappe.PermissionError)


def _rights(doctype: str, ptype_map: dict | None = None) -> list[str]:
	return list(std_rights) + list(
		(ptype_map if ptype_map is not None else get_doctype_ptype_map()).get(doctype, [])
	)


def doctype_rights(doctype: str) -> list[str]:
	meta = frappe.get_meta(doctype)
	return rules.applicable_rights(_rights(doctype), bool(meta.is_submittable), bool(meta.allow_import))


def doctype_rows(doctype: str) -> tuple:
	data = _effective_rows_by_doctype(doctypes=[doctype]).get(doctype)
	return data["rows"] if data else ()


def _custom_parents() -> frozenset[str]:
	return frozenset(frappe.get_all("Custom DocPerm", pluck="parent", distinct=True))


def _raw_rows(table: str, filters: dict) -> list[dict]:
	return frappe.get_all(table, filters={"docstatus": 0, **filters}, fields=["*"], order_by="idx asc")


def _effective_rows_by_doctype(doctypes=None, roles=None) -> dict[str, dict]:
	if doctypes is not None and not doctypes:
		return {}
	ptype_map = get_doctype_ptype_map()
	custom_parents = _custom_parents()
	filters = {
		**({"parent": ["in", list(doctypes)]} if doctypes is not None else {}),
		**({"role": ["in", list(roles)]} if roles is not None else {}),
	}
	raw = [
		*(row for row in _raw_rows("DocPerm", filters) if row.parent not in custom_parents),
		*_raw_rows("Custom DocPerm", filters),
	]
	parents = tuple(dict.fromkeys(row.parent for row in raw))
	return {
		parent: {
			"source": "custom" if parent in custom_parents else "standard",
			"rights": _rights(parent, ptype_map),
			"rows": rules.normalize_rows(
				(row for row in raw if row.parent == parent), _rights(parent, ptype_map)
			),
		}
		for parent in parents
	}


def _row_json(row: dict, rights: list[str]) -> dict:
	return {
		"role": row["role"],
		"permlevel": row["permlevel"],
		"if_owner": row["if_owner"],
		"rights": [right for right in rights if right in row["rights"]],
	}


def _access_json(access: dict) -> list[dict]:
	return [{"permlevel": level, "rights": by_right} for level, by_right in sorted(access.items())]


def _level_fields(doctype: str, levels) -> dict[int, list[str]]:
	wanted = {level for level in levels if level > 0}
	if not wanted:
		return {}
	meta = frappe.get_meta(doctype)
	return {
		level: [
			_(field.label or field.fieldname)
			for field in meta.fields
			if field.permlevel == level and field.label
		]
		for level in sorted(wanted)
	}


def _doctype_info(doctypes) -> dict[str, dict]:
	if not doctypes:
		return {}
	return {
		row.name: row
		for row in frappe.get_all(
			"DocType",
			filters={"name": ["in", list(doctypes)]},
			fields=["name", "module", "istable", "issingle", "is_submittable"],
		)
	}


def _doctype_entry(doctype: str, info: dict | None, source: str, access: dict) -> dict:
	module = info.module if info else None
	return {
		"doctype": doctype,
		"label": _(doctype),
		"module": module,
		"is_table": bool(info and info.istable),
		"source": source,
		"access": _access_json(access),
		"fields_by_level": _level_fields(doctype, access),
		"sensitive": rules.is_sensitive(doctype, module),
		"risky_rights": list(rules.risky_rights(access)),
		"field_levels": rules.has_field_levels(access),
	}


def effective_perms(doctype: str) -> dict:
	rights = _rights(doctype)
	standard = rules.normalize_rows(_raw_rows("DocPerm", {"parent": doctype}), rights)
	custom = rules.normalize_rows(_raw_rows("Custom DocPerm", {"parent": doctype}), rights)
	source, rows = rules.effective_rows(standard, custom)
	return {
		"doctype": doctype,
		"source": source,
		"rights": rights,
		"rows": [_row_json(row, rights) for row in rows],
		"inert_roles": list(rules.inert_roles(standard, custom)),
	}


def _inert_doctypes(role: str) -> list[str]:
	custom_parents = _custom_parents()
	standard_parents = {
		row.parent
		for row in _raw_rows("DocPerm", {"role": role})
		if row.parent in custom_parents and any(rules.is_set(row.get(right)) for right in std_rights)
	}
	custom_with_role = set(frappe.get_all("Custom DocPerm", filters={"role": role}, pluck="parent"))
	return sorted(standard_parents - custom_with_role)


def _custom_role_map(field: str) -> dict[str, list[str]]:
	custom = frappe.get_all("Custom Role", filters={field: ["is", "set"]}, fields=["name", field])
	roles = frappe.get_all(
		"Has Role",
		filters={"parenttype": "Custom Role", "parent": ["in", [row.name for row in custom] or [""]]},
		fields=["parent", "role"],
	)
	return {
		row[field]: [entry.role for entry in roles if entry.parent == row.name]
		for row in custom
		if row[field]
	}


def _standard_role_map(parenttype: str) -> dict[str, list[str]]:
	rows = frappe.get_all("Has Role", filters={"parenttype": parenttype}, fields=["parent", "role"])
	return {
		parent: [row.role for row in rows if row.parent == parent]
		for parent in dict.fromkeys(row.parent for row in rows)
	}


def _pages_for_roles(roles) -> list[dict]:
	role_set = set(roles)
	standard = _standard_role_map("Page")
	custom = _custom_role_map("page")
	names = [
		name
		for name in sorted(set(standard) | set(custom))
		if rules.page_roles(standard.get(name, ()), custom.get(name, ())) & role_set
	]
	titles = {
		row.name: row.title
		for row in frappe.get_all("Page", filters={"name": ["in", names or [""]]}, fields=["name", "title"])
	}
	return [{"name": name, "title": _(titles.get(name) or name)} for name in names if name in titles]


def _reports_for_roles(roles) -> list[dict]:
	role_set = set(roles)
	standard = _standard_role_map("Report")
	custom = _custom_role_map("report")
	names = [
		name
		for name in sorted(set(standard) | set(custom))
		if rules.report_roles(standard.get(name, ()), custom.get(name, ())) & role_set
	]
	return [
		{
			"name": row.name,
			"label": _(row.name),
			"ref_doctype": row.ref_doctype,
			"report_type": row.report_type,
		}
		for row in frappe.get_all(
			"Report",
			filters={"name": ["in", names or [""]], "disabled": 0},
			fields=["name", "ref_doctype", "report_type"],
			order_by="name asc",
		)
	]


def _workspaces_for_roles(roles) -> list[dict]:
	names = sorted(
		set(
			frappe.get_all(
				"Has Role", filters={"parenttype": "Workspace", "role": ["in", list(roles)]}, pluck="parent"
			)
		)
	)
	return [{"name": name, "label": _(name)} for name in names]


def _active_workflows() -> dict[str, str]:
	return {
		row.name: row.document_type
		for row in frappe.get_all("Workflow", filters={"is_active": 1}, fields=["name", "document_type"])
	}


def _workflow_for_roles(roles) -> dict[str, list[dict]]:
	workflows = _active_workflows()
	if not workflows:
		return {"transitions": [], "editable_states": []}
	role_filter = {"parent": ["in", list(workflows)], "parenttype": "Workflow"}
	transitions = frappe.get_all(
		"Workflow Transition",
		filters={**role_filter, "allowed": ["in", list(roles)]},
		fields=["parent", "state", "action", "next_state", "allowed", "condition"],
		order_by="parent asc, idx asc",
	)
	states = frappe.get_all(
		"Workflow Document State",
		filters={**role_filter, "allow_edit": ["in", list(roles)]},
		fields=["parent", "state", "allow_edit"],
		order_by="parent asc, idx asc",
	)
	return {
		"transitions": [
			{
				"workflow": row.parent,
				"doctype": workflows[row.parent],
				"state": _(row.state),
				"action": _(row.action),
				"next_state": _(row.next_state),
				"role": row.allowed,
				"has_condition": bool(row.condition),
			}
			for row in transitions
		],
		"editable_states": [
			{
				"workflow": row.parent,
				"doctype": workflows[row.parent],
				"state": _(row.state),
				"role": row.allow_edit,
			}
			for row in states
		],
	}


def _notifications_for_roles(roles) -> list[dict]:
	names = set(
		frappe.get_all(
			"Notification Recipient",
			filters={"parenttype": "Notification", "receiver_by_role": ["in", list(roles)]},
			pluck="parent",
		)
	)
	return [
		{
			"name": row.name,
			"doctype": row.document_type,
			"event": _(row.event),
			"channel": _(row.channel),
		}
		for row in frappe.get_all(
			"Notification",
			filters={"name": ["in", list(names) or [""]], "enabled": 1},
			fields=["name", "document_type", "event", "channel"],
			order_by="name asc",
		)
	]


def _role_holders(role: str) -> dict:
	users = frappe.db.sql(
		"""select hr.parent from `tabHas Role` hr join tabUser u on u.name = hr.parent
		where hr.parenttype = 'User' and hr.role = %s and u.enabled = 1""",
		role,
		pluck=True,
	)
	profiles = frappe.get_all(
		"Has Role", filters={"parenttype": "Role Profile", "role": role}, pluck="parent"
	)
	return {"users": len(users), "role_profiles": sorted(set(profiles))}


def role_grants(role: str) -> dict:
	by_doctype = _effective_rows_by_doctype(roles=[role])
	info = _doctype_info(by_doctype)
	doctypes = [
		_doctype_entry(
			doctype,
			info.get(doctype),
			data["source"],
			rules.access_map(data["rows"], [role], data["rights"]),
		)
		for doctype, data in sorted(by_doctype.items())
	]
	return {
		"role": role,
		"doctypes": [entry for entry in doctypes if entry["access"]],
		"inert_doctypes": _inert_doctypes(role),
		"pages": _pages_for_roles([role]),
		"reports": _reports_for_roles([role]),
		"workspaces": _workspaces_for_roles([role]),
		"workflow": _workflow_for_roles([role]),
		"notifications": _notifications_for_roles([role]),
		**_role_holders(role),
	}


def _minus(items: list[dict], existing: list[dict], key) -> list[dict]:
	seen = {key(item) for item in existing}
	return [item for item in items if key(item) not in seen]


def _report_usable(reports: list[dict], roles) -> list[dict]:
	ref_doctypes = {report["ref_doctype"] for report in reports if report["ref_doctype"]}
	by_doctype = _effective_rows_by_doctype(doctypes=ref_doctypes, roles=roles)
	usable = {
		doctype
		for doctype, data in by_doctype.items()
		if rules.access_map(data["rows"], roles, data["rights"]).get(0, {}).get("report")
	}
	return [
		{**report, "usable": not report["ref_doctype"] or report["ref_doctype"] in usable}
		for report in reports
	]


PSEUDO_ROLES = ("All", "Guest", "Desk User")
WORKFLOW_KEYS = {
	"transitions": itemgetter("workflow", "state", "action"),
	"editable_states": itemgetter("workflow", "state"),
}
LISTED_KEYS = ("pages", "reports", "workspaces", "notifications")


def _listed_for_roles(roles) -> dict:
	return {
		"pages": _pages_for_roles(roles),
		"reports": _reports_for_roles(roles),
		"workspaces": _workspaces_for_roles(roles),
		"workflow": _workflow_for_roles(roles),
		"notifications": _notifications_for_roles(roles),
	}


def _listed_gain(before: dict, after: dict) -> dict:
	by_name = itemgetter("name")
	return {
		**{key: _minus(after[key], before[key], by_name) for key in LISTED_KEYS},
		"workflow": {
			key: _minus(after["workflow"][key], before["workflow"][key], getter)
			for key, getter in WORKFLOW_KEYS.items()
		},
	}


def _doctype_changes(by_doctype: dict, info: dict, before, after) -> list[dict]:
	entries = (
		_doctype_entry(
			doctype,
			info.get(doctype),
			data["source"],
			rules.access_delta(
				rules.access_map(data["rows"], before, data["rights"]),
				rules.access_map(data["rows"], after, data["rights"]),
			),
		)
		for doctype, data in sorted(by_doctype.items())
	)
	return [entry for entry in entries if entry["access"]]


def _visible(roles) -> list[str]:
	return [role for role in roles if role not in PSEUDO_ROLES]


def roles_delta(user: str, after_roles) -> dict:
	current = frappe.get_roles(user)
	after = list(dict.fromkeys([*after_roles, *(role for role in current if role in PSEUDO_ROLES)]))
	gained_roles = sorted(set(after) - set(current))
	lost_roles = sorted(set(current) - set(after))
	changed = [*gained_roles, *lost_roles]
	touched = list(_effective_rows_by_doctype(roles=changed)) if changed else []
	by_doctype = _effective_rows_by_doctype(doctypes=touched, roles=sorted({*current, *after}))
	info = _doctype_info(touched)
	listed_now = _listed_for_roles(current)
	listed_after = _listed_for_roles(after)
	gained = _listed_gain(listed_now, listed_after)
	return {
		"user": user,
		"current_roles": _visible(current),
		"gained_roles": _visible(gained_roles),
		"lost_roles": _visible(lost_roles),
		"doctypes": _doctype_changes(by_doctype, info, current, after),
		"inert_doctypes": sorted({doctype for role in gained_roles for doctype in _inert_doctypes(role)}),
		**gained,
		"reports": _report_usable(gained["reports"], after),
		"lost": {
			"doctypes": _doctype_changes(by_doctype, info, after, current),
			**_listed_gain(listed_after, listed_now),
		},
	}


def role_delta(user: str, role: str) -> dict:
	current = frappe.get_roles(user)
	if role in current:
		return {"user": user, "role": role, "already_has": True}
	return {
		**roles_delta(user, [*current, role]),
		"role": role,
		"already_has": False,
		**_role_holders(role),
	}


def _is_shared(doctype: str, ptype: str, user: str, name: str | None) -> bool:
	custom_rights = get_doctype_ptype_map().get(doctype, [])
	if ptype not in (*SHAREABLE_RIGHTS, *custom_rights):
		return False
	right = "read" if ptype in ("email", "print") else ptype
	filters = [["share_name", "=", name]] if name else None
	return bool(frappe.share.get_shared(doctype, user, rights=[right], filters=filters, limit=1))


def _workflow_context(doc, roles) -> dict | None:
	workflow_name = get_workflow_name(doc.doctype)
	if not workflow_name:
		return None
	workflow = frappe.get_doc("Workflow", workflow_name)
	state = doc.get(workflow.workflow_state_field)
	edit_roles = [row.allow_edit for row in workflow.states if row.state == state and row.allow_edit]
	return {
		"workflow": workflow_name,
		"state": state,
		"state_label": _(state) if state else None,
		"edit_roles": edit_roles,
		"user_can_edit": bool(set(edit_roles) & set(roles)),
		"options": rules.workflow_options([row.as_dict() for row in workflow.transitions], state, roles),
	}


def explain(
	doctype: str, ptype: str = "read", name: str | None = None, user: str | None = None, debug=False
) -> dict:
	user = user or frappe.session.user
	meta = frappe.get_meta(doctype)
	if meta.istable:
		frappe.throw(
			_("Check access on the parent document instead of the child table {0}").format(_(doctype))
		)
	name = doctype if meta.issingle else name
	rights = _rights(doctype)
	rows = rules.normalize_rows(meta.permissions, rights)
	roles = frappe.get_roles(user)
	level0 = rules.access_map(rows, roles, rights).get(0, {})
	doc = frappe.get_doc(doctype, name) if name else None
	messages = len(frappe.local.message_log)
	allowed = has_permission(doctype, ptype, doc=doc, user=user, print_logs=False, debug=debug)
	del frappe.local.message_log[messages:]
	debug_log = _pop_debug_log() if debug else []
	facts = {
		"scope": level0.get(ptype),
		"is_owner": ((doc.owner or "").lower() == user.lower()) if doc else None,
		"not_submittable": ptype == "submit" and not meta.is_submittable,
		"not_importable": ptype == "import" and not meta.allow_import,
		"controller_ok": has_controller_permissions(doc, ptype, user=user) if doc else None,
		"user_permission_ok": has_user_permission(doc, user, ptype=ptype) if doc else None,
		"shared": _is_shared(doctype, ptype, user, name),
		"allowed": allowed,
	}
	return {
		"doctype": doctype,
		"doctype_label": _(doctype),
		"name": name,
		"ptype": ptype,
		"user": user,
		"user_roles": [role for role in roles if role not in ("All", "Guest", "Desk User")],
		"source": "custom" if frappe.db.exists("Custom DocPerm", {"parent": doctype}) else "standard",
		"granting_roles": rules.granting_roles(rows, ptype),
		"facts": facts,
		**rules.diagnose(facts),
		"hints": list(
			rules.docstatus_hints(ptype, doc.docstatus if doc else None, bool(meta.is_submittable))
		),
		"workflow": _workflow_context(doc, roles) if doc else None,
		"debug_log": debug_log,
	}


def _public_explanation(result: dict) -> dict:
	can_read = result["allowed"] if result["ptype"] == "read" else None
	return {
		**{key: value for key, value in result.items() if key not in ("debug_log", "facts", "workflow")},
		"workflow": result["workflow"] if can_read is not False else None,
	}


@frappe.whitelist()
def get_effective_perms(doctype: str) -> dict:
	_require_manager()
	return effective_perms(doctype)


@frappe.whitelist()
def get_role_grants(role: str) -> dict:
	_require_manager()
	if not frappe.db.exists("Role", role):
		frappe.throw(_("Role {0} not found").format(role), frappe.DoesNotExistError)
	return role_grants(role)


@frappe.whitelist()
def get_role_delta(user: str, role: str) -> dict:
	_require_manager()
	if not frappe.db.exists("User", user):
		frappe.throw(_("User {0} not found").format(user), frappe.DoesNotExistError)
	return role_delta(user, role)


@frappe.whitelist()
def explain_access(
	doctype: str, ptype: str = "read", name: str | None = None, user: str | None = None
) -> dict:
	target = user or frappe.session.user
	manager = is_access_manager()
	if target != frappe.session.user and not manager:
		frappe.throw(
			_("Only Access Manager or System Manager can check access of other users"), frappe.PermissionError
		)
	result = explain(doctype, ptype, name, target, debug=manager)
	return result if manager else _public_explanation(result)
