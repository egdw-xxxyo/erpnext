frappe.listview_settings["Sidebar Menu Item"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Drag and Drop View"), () => frappe.set_route("global-menu"));
	},
};
