"""The attendance sheet in the stock Organization sidebar. See `erpnext.setup.sidebar_links`."""

from erpnext.setup.sidebar_links import add_links

SIDEBAR = "Organization"
INSERT_AFTER = "Company"
LINKS = (
	{
		"label": "Monthly Attendance Sheet",
		"link_to": "Monthly Attendance Sheet",
		"link_type": "Report",
		"icon": "calendar-check",
	},
)


def add_organization_links():
	add_links(SIDEBAR, INSERT_AFTER, LINKS)
