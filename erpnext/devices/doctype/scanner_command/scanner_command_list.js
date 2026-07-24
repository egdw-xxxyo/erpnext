frappe.listview_settings["Scanner Command"] = {
	onload: function (listview) {
		listview.page.add_action_item(__("Print Labels"), () => {
			const checked = listview.get_checked_items();
			if (!checked.length) {
				frappe.msgprint(__("Please select at least one Scanner Command"));
				return;
			}
			erpnext.utils.open_bulk_label_print_dialog({
				doctype: "Scanner Command",
				names: checked.map((d) => d.name),
			});
		});
	},
};
