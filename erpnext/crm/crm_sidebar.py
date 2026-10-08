"""Our chat pages (and the WhatsApp overview) in the stock CRM sidebar. See `erpnext.setup.sidebar_links`."""

import frappe

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
		"label": "WhatsApp Chat Monitor",
		"link_to": "whatsapp-chat-monitor",
		"link_type": "Page",
		"icon": "eye",
	},
	{
		"label": "WhatsApp Overview",
		"link_to": "whatsapp-overview",
		"link_type": "Page",
		"icon": "layout-dashboard",
	},
)


MOCK_LINK = {
	"label": "WhatsApp Mock",
	"link_to": "whatsapp-mock",
	"link_type": "Page",
	"icon": "flask-conical",
}


def add_chat_pages():
	links = LINKS if frappe.conf.get("instance_env") == "prod" else (*LINKS, MOCK_LINK)
	add_links(SIDEBAR, INSERT_AFTER, links)
