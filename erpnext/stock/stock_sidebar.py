"""Package overview in the stock Stock sidebar. See `erpnext.setup.sidebar_links`."""

import frappe

from erpnext.setup.sidebar_links import add_links

SIDEBAR = "Stock"
INSERT_AFTER = "Delivery Note"
LINKS = (
	{
		"label": "Package Overview",
		"link_to": "package-overview",
		"link_type": "Page",
		"icon": "package",
	},
)
PAGE = "package-overview"


def add_stock_links():
	add_links(SIDEBAR, INSERT_AFTER, LINKS)
	sync_page_roles()


def sync_page_roles():
	"""Give the package overview the roles a desk Custom Role adds to its access report.

	The page's own roles are the report's standard ones; a Custom Role set on the report in
	the desk extends them per site, and is copied onto the page here.
	"""
	from frappe.core.doctype.custom_role.custom_role import get_custom_allowed_roles

	from erpnext.stock.page.package_overview.package_overview import ACCESS_REPORT

	roles = get_custom_allowed_roles("report", ACCESS_REPORT)
	name = frappe.db.get_value("Custom Role", {"page": PAGE}, "name")
	if not roles:
		if name:
			frappe.delete_doc("Custom Role", name, ignore_permissions=True)
		return
	doc = frappe.get_doc("Custom Role", name) if name else frappe.new_doc("Custom Role")
	if name and sorted(r.role for r in doc.roles) == sorted(roles):
		return
	doc.page = PAGE
	doc.set("roles", [{"role": role} for role in roles])
	doc.flags.ignore_permissions = True
	doc.save()
