"""Production lines in the stock Manufacturing sidebar. See `erpnext.setup.sidebar_links`."""

from erpnext.setup.sidebar_links import add_links

SIDEBAR = "Manufacturing"
INSERT_AFTER = "Job Card"
LINKS = (
	{"label": "Production Line", "link_to": "Production Line", "link_type": "DocType", "icon": "workflow"},
	{
		"label": "Production Line Overview",
		"link_to": "production-line-overview",
		"link_type": "Page",
		"icon": "layout-dashboard",
	},
)


def add_production_line_pages():
	add_links(SIDEBAR, INSERT_AFTER, LINKS)
