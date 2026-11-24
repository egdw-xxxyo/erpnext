import json

import frappe
from frappe import _

from erpnext.access_control import company_access_rules as rules
from erpnext.access_control.permissions_engine import _require_manager

ACCESS_DOCTYPE = "User Company Access"
SCOPE_DOCTYPE = "Company Access Scope"
MARKER = "company_access"


def company_doctypes() -> dict[str, str]:
	if "company_access_doctypes" not in frappe.local.flags:
		frappe.local.flags.company_access_doctypes = _load_company_doctypes()
	return frappe.local.flags.company_access_doctypes


def _load_company_doctypes() -> dict[str, str]:
	standard = frappe.db.sql(
		"""select distinct dt.name, dt.module from `tabDocField` df
		join `tabDocType` dt on dt.name = df.parent
		where df.parenttype = 'DocType' and df.fieldtype = 'Link' and df.options = 'Company'
			and ifnull(df.ignore_user_permissions, 0) = 0
			and dt.istable = 0 and dt.issingle = 0 and ifnull(dt.is_virtual, 0) = 0""",
		as_dict=True,
	)
	custom = frappe.db.sql(
		"""select distinct dt.name, dt.module from `tabCustom Field` cf
		join `tabDocType` dt on dt.name = cf.dt
		where cf.fieldtype = 'Link' and cf.options = 'Company'
			and ifnull(cf.ignore_user_permissions, 0) = 0
			and dt.istable = 0 and dt.issingle = 0 and ifnull(dt.is_virtual, 0) = 0""",
		as_dict=True,
	)
	return {row.name: row.module for row in [*standard, *custom]}


def _names(rows, field: str) -> list[str]:
	return [row.get(field) if isinstance(row, dict) else getattr(row, field) for row in rows or []]


def scope_doctypes_of(scope) -> list[str]:
	return rules.scope_doctypes(
		company_doctypes(),
		_names(scope.get("modules"), "module"),
		_names(scope.get("include_doctypes"), "document_type"),
		_names(scope.get("exclude_doctypes"), "document_type"),
	)


def _company_rows(user: str) -> list[dict]:
	return [
		{**row, "managed": row.get(MARKER)}
		for row in frappe.get_all(
			"User Permission",
			filters={"user": user, "allow": rules.ALLOW},
			fields=["name", "for_value", "applicable_for", "apply_to_all_doctypes", MARKER],
		)
	]


def _grants(access) -> list[tuple[str, str]]:
	return [(row.get("company"), row.get("scope")) for row in (access.get("grants") if access else []) or []]


def _doctypes_by_scope(scopes) -> dict[str, list[str]]:
	return {
		scope: scope_doctypes_of(frappe.get_cached_doc(SCOPE_DOCTYPE, scope))
		for scope in set(scopes)
		if frappe.db.exists(SCOPE_DOCTYPE, scope)
	}


def plan(user: str, grants: list[tuple[str, str]]) -> dict:
	rows = _company_rows(user)
	already_global = rules.global_companies(rows)
	desired = rules.desired_pairs(grants, _doctypes_by_scope(scope for _c, scope in grants), already_global)
	to_add, to_remove = rules.permission_delta(desired, rows)
	return {
		"rows": rows,
		"global": sorted(already_global),
		"desired": desired,
		"to_add": to_add,
		"to_remove": to_remove,
	}


def sync_user(user: str) -> dict:
	access = _access_of(user)
	result = apply(user, _grants(access), access.name if access else None)
	refresh_summary(user)
	return result


def refresh_summary(user: str):
	access = _access_of(user)
	if not access:
		return
	grants = _grants(access)
	result = plan(user, grants)
	frappe.db.set_value(
		ACCESS_DOCTYPE,
		user,
		{
			"main_companies": "\n".join(result["global"]),
			"extra_companies": rules.grant_lines(grants),
			"access_status": rules.access_status(
				bool(frappe.db.get_value("User", user, "enabled")), result["global"], result["desired"]
			),
		},
		update_modified=False,
	)


def on_user_permission_change(doc, method=None):
	if doc.allow == rules.ALLOW and not frappe.flags.company_access_syncing:
		refresh_summary(doc.user)


def on_user_update(doc, method=None):
	if doc.has_value_changed("enabled"):
		refresh_summary(doc.name)


def apply(user: str, grants: list[tuple[str, str]], marker: str | None) -> dict:
	frappe.flags.company_access_syncing = True
	try:
		return _apply(user, grants, marker)
	finally:
		frappe.flags.company_access_syncing = False


def _apply(user: str, grants: list[tuple[str, str]], marker: str | None) -> dict:
	result = plan(user, grants)
	for name in result["to_remove"]:
		frappe.delete_doc("User Permission", name, ignore_permissions=True, force=True)
	for company, doctype in result["to_add"]:
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user,
				"allow": rules.ALLOW,
				"for_value": company,
				"apply_to_all_doctypes": 0,
				"applicable_for": doctype,
				MARKER: marker,
			}
		).insert(ignore_permissions=True)
	return {"added": len(result["to_add"]), "removed": len(result["to_remove"])}


def _access_of(user: str):
	return frappe.get_doc(ACCESS_DOCTYPE, user) if frappe.db.exists(ACCESS_DOCTYPE, user) else None


def users_of_scope(scope: str) -> list[str]:
	return frappe.get_all(
		"User Company Access Grant",
		filters={"parenttype": ACCESS_DOCTYPE, "scope": scope},
		pluck="parent",
		distinct=True,
	)


def sync_scope(scope: str) -> dict:
	frappe.clear_document_cache(SCOPE_DOCTYPE, scope)
	return _sum(sync_user(user) for user in users_of_scope(scope))


def sync_all():
	if not frappe.db.table_exists(ACCESS_DOCTYPE) or not frappe.db.has_column("User Permission", MARKER):
		return
	frappe.local.flags.pop("company_access_doctypes", None)
	managed = frappe.get_all("User Permission", filters={MARKER: ["is", "set"]}, pluck="user", distinct=True)
	users = set(frappe.get_all(ACCESS_DOCTYPE, pluck="name")) | set(managed)
	for user in sorted(users):
		sync_user(user)


def _sum(results) -> dict:
	results = list(results)
	return {
		"users": len(results),
		"added": sum(r["added"] for r in results),
		"removed": sum(r["removed"] for r in results),
	}


def _loads(value):
	return json.loads(value) if isinstance(value, str) else value or []


@frappe.whitelist()
def preview_scope(
	modules: str | list | None = None, include: str | list | None = None, exclude: str | list | None = None
) -> dict:
	_require_manager()
	candidates = company_doctypes()
	include = _loads(include)
	doctypes = rules.scope_doctypes(candidates, _loads(modules), include, _loads(exclude))
	return {
		"by_module": rules.by_module(doctypes, candidates),
		"count": len(doctypes),
		"unusable": rules.unusable_doctypes(candidates, include),
	}


@frappe.whitelist()
def preview_access(user: str, grants: str | list | None = None) -> dict:
	_require_manager()
	if not user:
		return {"global": [], "companies": {}, "narrows": False}
	pairs = [
		(g.get("company"), g.get("scope")) for g in _loads(grants) if g.get("company") and g.get("scope")
	]
	result = plan(user, pairs)
	candidates = company_doctypes()
	companies = sorted({company for company, _doctype in result["desired"]})
	return {
		"global": result["global"],
		"companies": {
			company: rules.by_module([d for c, d in result["desired"] if c == company], candidates)
			for company in companies
		},
		"skipped": sorted({company for company, _scope in pairs if company in result["global"]}),
		"narrows": bool(pairs) and not result["global"],
	}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def doctype_query(doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict | str):
	_require_manager()
	filters = _loads(filters) or {}
	candidates = company_doctypes()
	modules = _loads(filters.get("modules"))
	choices = (
		rules.exclude_choices(candidates, modules, _loads(filters.get("include")))
		if filters.get("mode") == "exclude"
		else rules.include_choices(candidates, modules)
	)
	needle = (txt or "").lower()
	matches = [d for d in choices if needle in d.lower() or needle in _(d).lower()]
	return [(d, _(candidates[d])) for d in matches[int(start) : int(start) + int(page_len)]]


def validate_scope(doc):
	modules = _names(doc.modules, "module")
	include = _names(doc.include_doctypes, "document_type")
	kept = set(
		rules.kept_excludes(
			company_doctypes(), modules, include, _names(doc.exclude_doctypes, "document_type")
		)
	)
	doc.exclude_doctypes = [row for row in doc.exclude_doctypes if row.document_type in kept]
	unusable = rules.unusable_doctypes(company_doctypes(), _names(doc.include_doctypes, "document_type"))
	if unusable:
		frappe.throw(
			_(
				"These document types have no Company field, so a company cannot be opened in them: {0}"
			).format(", ".join(_(d) for d in unusable))
		)


def validate_access(doc):
	duplicates = rules.duplicate_grants(_grants(doc))
	if duplicates:
		frappe.throw(_("Repeated rows: {0}").format("; ".join(f"{_(c)} / {_(s)}" for c, s in duplicates)))


def report_sync(result: dict):
	if result["added"] or result["removed"]:
		frappe.msgprint(
			_("User Permissions updated: {0} added, {1} removed").format(result["added"], result["removed"]),
			alert=True,
			indicator="green",
		)
