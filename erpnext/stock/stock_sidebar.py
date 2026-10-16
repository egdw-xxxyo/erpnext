"""Package overview in the stock Stock sidebar. See `erpnext.setup.sidebar_links`."""

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


def add_stock_links():
	add_links(SIDEBAR, INSERT_AFTER, LINKS)
