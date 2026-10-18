from itertools import islice

import frappe
from frappe import _
from frappe.desk.desk_views import DeskViews
from frappe.utils import escape_html
from frappe.utils.user import UserPermissions

CACHE_KEY = "access_catalog"
CACHE_SECONDS = 300
LIMIT = 20
INDEX = 1
KIND_LABELS = {"doctype": "List", "single": None, "report": "Report", "page": "Page"}


def search(txt: str) -> list[dict]:
	if frappe.get_cached_value("User", frappe.session.user, "user_type") != "System User":
		return []
	words = txt.casefold().split()
	entries = (entry for entry in catalog(frappe.session.user) if matches(entry, words))
	return [option(entry) for entry in islice(entries, LIMIT)]


def matches(entry: dict, words: list[str]) -> bool:
	haystack = f"{_(entry['title'])} {entry['title']}".casefold()
	return bool(words) and all(word in haystack for word in words)


def option(entry: dict) -> dict:
	title = _(entry["title"])
	kind = KIND_LABELS[entry["kind"]]
	suffix = f' <span class="text-muted">{_(kind)}</span>' if kind else ""
	return {
		"label": f'<i class="fa fa-lock text-muted"></i> {escape_html(title)}{suffix}',
		"value": f"{title} · {entry['kind']} · {entry['name']}",
		"description": _("No access. Open to request it"),
		"route": entry["route"],
		"index": INDEX,
	}


def catalog(user: str) -> list[dict]:
	cached = frappe.cache.get_value(CACHE_KEY, user=user)
	if cached is not None:
		return cached
	entries = build_catalog(user)
	frappe.cache.set_value(CACHE_KEY, entries, user=user, expires_in_sec=CACHE_SECONDS)
	return entries


def build_catalog(user: str) -> list[dict]:
	hidden = hidden_modules(user)
	return [
		entry for entry in (*_doctypes(user), *_reports(user), *_pages(user)) if entry["module"] not in hidden
	]


def hidden_modules(user: str) -> set[str]:
	service = frappe.get_all("Module Def", filters={"app_name": "frappe"}, pluck="name")
	blocked = frappe.get_all("Block Module", filters={"parent": user, "parenttype": "User"}, pluck="module")
	return {*service, *blocked}


def _doctypes(user: str) -> list[dict]:
	permissions = UserPermissions(user)
	readable = {*permissions.get_can_read(), *permissions.all_read}
	rows = frappe.get_all(
		"DocType",
		filters={"istable": 0, "read_only": 0},
		fields=["name", "module", "issingle"],
		order_by="name",
	)
	return [
		{
			"kind": "single" if row.issingle else "doctype",
			"name": row.name,
			"title": row.name,
			"module": row.module,
			"route": ["Form", row.name, row.name] if row.issingle else ["List", row.name],
		}
		for row in rows
		if row.name not in readable
	]


def _reports(user: str) -> list[dict]:
	allowed = set(DeskViews.get_allowed_reports(user=user))
	rows = frappe.get_all(
		"Report",
		filters={"disabled": 0},
		fields=["name", "module", "report_type", "ref_doctype"],
		order_by="name",
	)
	return [
		{
			"kind": "report",
			"name": row.name,
			"title": row.name,
			"module": row.module,
			"route": ["List", row.ref_doctype, "Report", row.name]
			if row.report_type == "Report Builder"
			else ["query-report", row.name],
		}
		for row in rows
		if row.name not in allowed
	]


def _pages(user: str) -> list[dict]:
	allowed = set(DeskViews.get_allowed_pages(user=user))
	rows = frappe.get_all("Page", fields=["name", "title", "module"], order_by="name")
	return [
		{
			"kind": "page",
			"name": row.name,
			"title": row.title or row.name,
			"module": row.module,
			"route": [row.name],
		}
		for row in rows
		if row.name not in allowed
	]
