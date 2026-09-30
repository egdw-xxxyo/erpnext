// Employee Chat: the shared chat screen (erpnext/public/js/chat/chat_view.js) over the
// Employee Chat source (erpnext/public/js/chat/sources/employee.js).

frappe.pages["employee-chat"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Employee Chat"),
		single_column: true,
	});
	const source = new erpnext.chat_sources.Employee();
	page.add_menu_item(__("Secret chats"), () => source.secret_settings_dialog());
	// Archiving policy lives in the Chat Settings form; only the roles that may change it
	// get the shortcut.
	if (frappe.user.has_role(["Chat Manager", "System Manager"])) {
		page.add_menu_item(__("Chat Settings"), () => frappe.set_route("Form", "Chat Settings"));
	}
	wrapper.chat_view = new erpnext.chat_view.ChatView(page, source);
};

// Deep links into an already open page (?thread=…).
frappe.pages["employee-chat"].on_page_show = function (wrapper) {
	const view = wrapper.chat_view;
	if (!view) return;
	const ro = frappe.route_options || {};
	if (ro.thread || frappe.utils.get_url_arg("thread")) {
		frappe.route_options = null;
		view.route_to(ro);
	}
};
