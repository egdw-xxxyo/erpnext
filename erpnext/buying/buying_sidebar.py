"""Consolidated purchase orders in the stock Buying sidebar. See `erpnext.setup.sidebar_links`.

The list opens on the user's own work queue (participant, not finished) by itself, see
`erpnext.buying.apply_procurement_work_queue_filters`, so the link carries no filters.
"""

from erpnext.setup.sidebar_links import add_links

SIDEBAR = "Buying"
INSERT_AFTER = "Material Request"
LINKS = (
	{
		"label": "Consolidated Purchase Order",
		"link_to": "Consolidated Purchase Order",
		"link_type": "DocType",
		"icon": "clipboard-list",
	},
)


def add_buying_links():
	add_links(SIDEBAR, INSERT_AFTER, LINKS)
