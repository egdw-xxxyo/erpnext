// WhatsApp Chat Monitor: every chat of the numbers the user follows, read only. Managers
// follow all numbers, spectators the numbers they are set on. Answering happens on the
// WhatsApp Chat page, by whoever is Responsible for the number.

frappe.pages["whatsapp-chat-monitor"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("WhatsApp Chat Monitor"),
		single_column: true,
	});
	if (frappe.boot.whatsapp_manager) {
		page.add_menu_item(__("WhatsApp Overview"), () => frappe.set_route("whatsapp-overview"));
	}
	if ((frappe.boot.whatsapp_accounts || []).length) {
		page.add_menu_item(__("WhatsApp Chat"), () => frappe.set_route("whatsapp-chat-center"));
	}
	wrapper.chat_view = new erpnext.chat_view.ChatView(
		page,
		new erpnext.chat_sources.WhatsApp({ mode: "watch" })
	);
};

// Deep links (?chat=… / ?number=…) from the WhatsApp Overview.
frappe.pages["whatsapp-chat-monitor"].on_page_show = function (wrapper) {
	const view = wrapper.chat_view;
	if (!view) return;
	view.fit_height();
	const ro = frappe.route_options || {};
	const arg = (key) => ro[key] || frappe.utils.get_url_arg(key);
	if (arg("chat") || arg("number")) {
		frappe.route_options = null;
		view.route_to(ro);
	}
};
