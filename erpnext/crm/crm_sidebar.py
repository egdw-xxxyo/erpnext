"""Our chat pages (and the WhatsApp overview / access pages) in the stock CRM sidebar. See `erpnext.setup.sidebar_links`."""

from erpnext.setup.sidebar_links import add_links

SIDEBAR = "CRM"
INSERT_AFTER = "Customer"
LINKS = (
	{"label": "Employee Chat", "link_to": "employee-chat", "link_type": "Page", "icon": "messages-square"},
	{
		"label": "WhatsApp Chat",
		"link_to": "whatsapp-chat-center",
		"link_type": "Page",
		"icon": "message-circle",
	},
	{
		"label": "WhatsApp Overview",
		"link_to": "whatsapp-overview",
		"link_type": "Page",
		"icon": "layout-dashboard",
	},
	{
		"label": "WhatsApp Access",
		"link_to": "whatsapp-access",
		"link_type": "Page",
		"icon": "users",
	},
)


def add_chat_pages():
	add_links(SIDEBAR, INSERT_AFTER, LINKS)
