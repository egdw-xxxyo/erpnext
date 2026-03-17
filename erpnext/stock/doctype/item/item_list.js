function _show_print_labels_dialog(doctype, names) {
	const dlg = new frappe.ui.Dialog({
		title: __("Print Labels"),
		fields: [
			{
				fieldname: "label_template",
				fieldtype: "Link",
				label: __("Label Template"),
				options: "Label Template",
				reqd: 1,
				get_query: () => ({ filters: { source_field: ["is", "set"] } }),
				change: () => {
					const tmpl = dlg.get_value("label_template");
					if (!tmpl) { dlg.fields_dict.info_html.$wrapper.html(""); return; }
					frappe.call({
						method: "erpnext.manufacturing.doctype.label_printer.label_printer.count_labels",
						args: { source_doctype: doctype, source_names: JSON.stringify(names), label_template: tmpl },
						callback: (r) => {
							if (r.message) {
								dlg.fields_dict.info_html.$wrapper.html(
									`<div class="text-muted">${__("{0} labels from {1} records", [r.message.total, names.length])}</div>`
								);
							}
						},
					});
				},
			},
			{
				fieldname: "printer_name",
				fieldtype: "Link",
				label: __("Printer"),
				options: "Label Printer",
				reqd: 1,
				get_query: () => ({ filters: { is_enabled: 1 } }),
			},
			{ fieldname: "info_html", fieldtype: "HTML" },
		],
		primary_action_label: __("Print"),
		primary_action: (values) => {
			dlg.hide();
			frappe.call({
				method: "erpnext.manufacturing.doctype.label_printer.label_printer.print_labels_batch",
				args: {
					source_doctype: doctype,
					source_names: JSON.stringify(names),
					label_template: values.label_template,
					printer_name: values.printer_name,
				},
				freeze: true,
				freeze_message: __("Creating print jobs..."),
				callback: (r) => {
					if (r.message) {
						frappe.show_alert({ message: __("{0} print jobs created", [r.message.count]), indicator: "green" });
						frappe.set_route("List", "Print Job");
					}
				},
			});
		},
	});
	frappe.call({
		method: "frappe.client.get_list",
		args: { doctype: "Label Template", filters: { source_field: ["is", "set"] }, fields: ["name"], limit_page_length: 2 },
		async: false,
		callback: (r) => { if (r.message && r.message.length === 1) dlg.set_value("label_template", r.message[0].name); },
	});
	frappe.call({
		method: "frappe.client.get_list",
		args: { doctype: "Label Printer", filters: { is_enabled: 1 }, fields: ["name"], limit_page_length: 2 },
		async: false,
		callback: (r) => { if (r.message && r.message.length === 1) dlg.set_value("printer_name", r.message[0].name); },
	});
	dlg.show();
}

frappe.listview_settings["Item"] = {
	add_fields: [
		"item_name",
		"stock_uom",
		"item_group",
		"image",
		"has_variants",
		"end_of_life",
		"disabled",
		"variant_of",
	],
	filters: [["disabled", "=", "0"]],

	get_indicator: function (doc) {
		if (doc.disabled) {
			return [__("Disabled"), "grey", "disabled,=,Yes"];
		} else if (doc.end_of_life && doc.end_of_life < frappe.datetime.get_today()) {
			return [__("Expired"), "grey", "end_of_life,<,Today"];
		} else if (doc.has_variants) {
			return [__("Template"), "orange", "has_variants,=,Yes"];
		} else if (doc.variant_of) {
			return [__("Variant"), "green", "variant_of,=," + doc.variant_of];
		}
	},

	onload: function (listview) {
		listview.page.add_action_item(__("Print Labels"), () => {
			const checked = listview.get_checked_items();
			if (!checked.length) {
				frappe.msgprint(__("Please select at least one Item"));
				return;
			}
			_show_print_labels_dialog("Item", checked.map((d) => d.name));
		});
	},

	reports: [
		{
			name: "Stock Summary",
			route: "/app/stock-balance",
		},
		{
			name: "Stock Ledger",
			report_type: "Script Report",
		},
		{
			name: "Stock Balance",
			report_type: "Script Report",
		},
		{
			name: "Stock Projected Qty",
			report_type: "Script Report",
		},
	],
};

frappe.help.youtube_id["Item"] = "qXaEwld4_Ps";
