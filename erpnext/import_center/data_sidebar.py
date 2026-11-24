"""The Import Center page in the stock Data sidebar. See `erpnext.setup.sidebar_links`."""

from erpnext.setup.sidebar_links import add_links

SIDEBAR = "Data"
INSERT_AFTER = "Data Import"
LINKS = (
	{
		"label": "Import Center",
		"link_to": "data-import-center",
		"link_type": "Page",
		"icon": "import",
	},
)


def add_data_links():
	add_links(SIDEBAR, INSERT_AFTER, LINKS)
