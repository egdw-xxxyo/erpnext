frappe.listview_settings["BpAK"] = {
	onload: function (listview) {
		listview.page.add_action_item(__("Print Labels"), () => {
			const checked = listview.get_checked_items();
			if (!checked.length) {
				frappe.msgprint(__("Please select at least one BpAK"));
				return;
			}
			erpnext.utils.open_bulk_label_print_dialog({
				doctype: "BpAK",
				names: checked.map((d) => d.name),
			});
		});
	},
};
