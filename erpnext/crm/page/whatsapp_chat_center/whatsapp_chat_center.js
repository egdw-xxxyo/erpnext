// WhatsApp Chat: the shared chat screen (erpnext/public/js/chat/chat_view.js) over the
// WhatsApp source (erpnext/public/js/chat/sources/whatsapp.js).

frappe.pages["whatsapp-chat-center"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("WhatsApp Chat"),
		single_column: true,
	});
	if (frappe.boot.whatsapp_manager) {
		page.add_menu_item(__("WhatsApp Overview"), () => frappe.set_route("whatsapp-overview"));
	}
	if ((frappe.boot.whatsapp_watch || []).length) {
		page.add_menu_item(__("WhatsApp Chat Monitor"), () => frappe.set_route("whatsapp-chat-monitor"));
	}
	wrapper.chat_view = new erpnext.chat_view.ChatView(page, new erpnext.chat_sources.WhatsApp());
};

// Deep links into an already open page (?chat=… / ?phone=…).
frappe.pages["whatsapp-chat-center"].on_page_show = function (wrapper) {
	const view = wrapper.chat_view;
	if (!view) return;
	view.fit_height();
	const ro = frappe.route_options || {};
	const arg = (key) => ro[key] || frappe.utils.get_url_arg(key);
	if (arg("chat") || arg("phone") || arg("number")) {
		frappe.route_options = null;
		view.route_to(ro);
	}
};
