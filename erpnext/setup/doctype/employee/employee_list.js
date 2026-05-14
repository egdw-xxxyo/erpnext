frappe.listview_settings["Employee"] = {
	add_fields: ["status", "branch", "department", "designation", "image"],
	filters: [["status", "=", "Active"]],
	get_indicator: function (doc) {
		return [
			__(doc.status, null, "Employee"),
			{ Active: "green", Inactive: "red", Left: "gray", Suspended: "orange" }[doc.status],
			"status,=," + doc.status,
		];
	},
	onload: function (listview) {
		listview.page.add_action_item(__("Print Labels"), () => {
			const checked = listview.get_checked_items();
			if (!checked.length) {
				frappe.msgprint(__("Please select at least one Employee"));
				return;
			}
			erpnext.utils.open_bulk_label_print_dialog({
				doctype: "Employee",
				names: checked.map((d) => d.name),
			});
		});
	},
};
