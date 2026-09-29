"""Per-DocType help pages.

A DocType's help page is its stock `documentation` property, set through a Property Setter so no
stock DocType file changes. When the link points at a Wiki page on this site, the desk shows the
page in a popup; any other URL opens in a new tab.
"""

from urllib.parse import unquote, urlparse

import frappe
from frappe import _
from frappe.custom.doctype.property_setter.property_setter import delete_property_setter

HELP_MANAGER_ROLES = {"System Manager", "Wiki Manager"}


def _wiki_installed() -> bool:
	return "wiki" in frappe.get_installed_apps()


def _wiki_route(url: str) -> str | None:
	parsed = urlparse(url)
	if parsed.netloc:
		request = getattr(frappe.local, "request", None)
		if not request or parsed.netloc != request.host:
			return None
	return unquote(parsed.path).strip("/") or None


def _wiki_page_name(route: str) -> str | None:
	from wiki.frappe_wiki.doctype.wiki_document.wiki_document import get_landing_page_for_route

	name = frappe.db.get_value(
		"Wiki Document",
		{"route": route, "is_group": 0, "is_published": 1, "is_external_link": 0},
		"name",
	)
	if name:
		return name
	landing = get_landing_page_for_route(route)
	return landing["name"] if landing else None


@frappe.whitelist()
def get_help(doctype: str) -> dict:
	url = frappe.get_meta(doctype).documentation
	if not url:
		return {}

	route = _wiki_route(url) if _wiki_installed() else None
	if not route or not (
		frappe.db.exists("Wiki Document", {"route": route})
		or frappe.db.exists("Wiki Space", {"route": route.split("/")[0]})
	):
		return {"url": url, "external": True}

	from wiki.frappe_wiki.doctype.wiki_document.wiki_document import get_rendered_content

	name = _wiki_page_name(route)
	if not name:
		return {"url": url, "missing": True}

	doc = frappe.get_cached_doc("Wiki Document", name)
	try:
		doc.check_space_access("read")
		doc.check_published()
	except frappe.DoesNotExistError:
		return {"url": url, "missing": True}

	html, _toc = get_rendered_content(doc.name, doc.content or "")
	return {"url": "/" + doc.route, "title": doc.title, "html": html}


@frappe.whitelist()
def get_wiki_pages() -> list[dict]:
	_check_manager()
	if not _wiki_installed():
		return []
	pages = frappe.get_all(
		"Wiki Document",
		filters={"is_group": 0, "is_external_link": 0},
		fields=["title", "route", "is_published"],
		order_by="lft asc",
	)
	return [
		{
			"value": "/" + page.route,
			"label": page.title if page.is_published else f"{page.title} ({_('Not Published')})",
			"description": "/" + page.route,
		}
		for page in pages
	]


@frappe.whitelist()
def set_help(doctype: str, url: str | None = None) -> None:
	_check_manager()
	frappe.get_meta(doctype)
	url = (url or "").strip()
	if url:
		frappe.make_property_setter(
			{
				"doctype": doctype,
				"doctype_or_field": "DocType",
				"property": "documentation",
				"value": url,
				"property_type": "Data",
			},
			is_system_generated=False,
		)
	else:
		delete_property_setter(doctype, "documentation")
	frappe.clear_cache(doctype=doctype)


def _check_manager() -> None:
	if not HELP_MANAGER_ROLES & set(frappe.get_roles()):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
