// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Operation", {
	setup: function (frm) {
		frm.set_query("operation", "sub_operations", function () {
			return {
				filters: {
					name: ["not in", [frm.doc.name]],
				},
			};
		});
	},
});

frappe.ui.form.on("Operation Field", {
	link_scan_filters: function (frm, cdt, cdn) {
		// When user clicks/focuses the JSON field, open filter dialog instead
	},

	edit_filters: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (!row.link_doctype) {
			frappe.msgprint(__("Please select a Link DocType first"));
			return;
		}
		open_filter_dialog(frm, cdt, cdn, row);
	},

	link_doctype: function (frm, cdt, cdn) {
		// Clear filters when doctype changes
		frappe.model.set_value(cdt, cdn, "link_scan_filters", "");
	},
});

function open_filter_dialog(frm, cdt, cdn, row) {
	let doctype = row.link_doctype;

	// Parse existing filters
	let saved_filters = [];
	if (row.link_scan_filters) {
		try {
			let parsed = JSON.parse(row.link_scan_filters);
			if (Array.isArray(parsed) && parsed.length === 3 && typeof parsed[0] === "string") {
				// Single tuple: ["field", "op", "value"]
				saved_filters = [[doctype, ...parsed]];
			} else if (Array.isArray(parsed)) {
				// Array of tuples
				saved_filters = parsed.map((f) => [doctype, ...f]);
			} else if (parsed.and) {
				saved_filters = parsed.and.map((f) => [doctype, ...f]);
			}
		} catch (e) {
			// Invalid JSON, start fresh
		}
	}

	frappe.model.with_doctype(doctype, () => {
		let d = new frappe.ui.Dialog({
			title: __("Configure Filters for {0}", [doctype]),
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "filter_area",
				},
			],
			primary_action_label: __("Apply"),
			primary_action: () => {
				let filters = filter_group.get_filters().map((f) => [f[1], f[2], f[3]]);

				let value = "";
				if (filters.length === 1) {
					value = JSON.stringify(filters[0]);
				} else if (filters.length > 1) {
					value = JSON.stringify({ and: filters });
				}
				frappe.model.set_value(cdt, cdn, "link_scan_filters", value);
				d.hide();
				frm.dirty();
			},
		});

		let filter_group = new frappe.ui.FilterGroup({
			parent: d.fields_dict.filter_area.$wrapper,
			doctype: doctype,
			on_change: () => {},
		});

		if (saved_filters.length) {
			filter_group.add_filters_to_filter_group(saved_filters);
		}

		d.show();
	});
}

frappe.tour["Operation"] = [
	{
		fieldname: "__newname",
		title: "Operation Name",
		description: __("Enter a name for the Operation, for example, Cutting."),
	},
	{
		fieldname: "workstation",
		title: "Default Workstation",
		description: __(
			"Select the Default Workstation where the Operation will be performed. This will be fetched in BOMs and Work Orders."
		),
	},
	{
		fieldname: "sub_operations",
		title: "Sub Operations",
		description: __("If an operation is divided into sub operations, they can be added here."),
	},
];
