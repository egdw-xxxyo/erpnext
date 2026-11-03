"""Access pages in the stock Users sidebar. See `erpnext.setup.sidebar_links`."""

from erpnext.setup.sidebar_links import add_links

SIDEBAR = "Users"
MODULE_SIDEBAR = "access control"
INSERT_AFTER = "Role"
LINKS = (
	{"label": "Access Management", "link_to": "access-console", "link_type": "Page", "icon": "shield"},
	{"label": "Access Request", "link_to": "Access Request", "link_type": "DocType", "icon": "key"},
	{
		"label": "Sensitive Data Monitor",
		"link_to": "sensitive-data-monitor",
		"link_type": "Page",
		"icon": "lock",
	},
)


def add_access_links():
	add_links(SIDEBAR, INSERT_AFTER, LINKS)


def hide_module_sidebar(bootinfo):
	(bootinfo.get("workspace_sidebar_item") or {}).pop(MODULE_SIDEBAR, None)
