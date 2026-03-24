frappe.query_reports["Component Stock Balance"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "mode",
			label: __("Mode"),
			fieldtype: "Select",
			options: "By Item Groups\nBy Product BOM",
			default: "By Item Groups",
			reqd: 1,
			on_change: function () {
				let mode = frappe.query_report.get_filter_value("mode");
				let is_group = mode === "By Item Groups";
				frappe.query_report.toggle_filter_display("item_groups", !is_group);
				frappe.query_report.toggle_filter_display("include_subgroups", !is_group);
				frappe.query_report.toggle_filter_display("bom", is_group);
				frappe.query_report.toggle_filter_display("qty_to_produce", is_group);
				if (is_group) {
					frappe.query_report.set_filter_value("bom", "");
				} else {
					frappe.query_report.set_filter_value("item_groups", []);
				}
			},
		},
		{
			fieldname: "item_groups",
			label: __("Item Groups"),
			fieldtype: "MultiSelectList",
			get_data: function (txt) {
				return frappe.db.get_link_options("Item Group", txt);
			},
		},
		{
			fieldname: "include_subgroups",
			label: __("Include Sub-groups"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "bom",
			label: __("Product BOM"),
			fieldtype: "Link",
			options: "BOM",
			hidden: 1,
			get_query: function () {
				return {
					filters: { docstatus: 1, is_active: 1 },
				};
			},
		},
		{
			fieldname: "qty_to_produce",
			label: __("Qty to Produce"),
			fieldtype: "Float",
			default: 1,
			hidden: 1,
		},
		{
			fieldname: "warehouse",
			label: __("Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
		},
		{
			fieldname: "show_value",
			label: __("Show Value"),
			fieldtype: "Check",
			default: 0,
		},
	],
	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (data && column.id === "item_code" && data.required_qty !== undefined) {
			if (data.actual_qty >= data.required_qty) {
				value = `<a style='color:green' href="/app/item/${data.item_code}" data-doctype="Item">${data.item_code}</a>`;
			} else {
				value = `<a style='color:red' href="/app/item/${data.item_code}" data-doctype="Item">${data.item_code}</a>`;
			}
		}
		return value;
	},
};
