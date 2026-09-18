// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
// For license information, please see license.txt

frappe.query_reports["Technical Documentation Completeness"] = {
	filters: [
		{
			fieldname: "section",
			label: __("Section"),
			fieldtype: "Link",
			options: "Technical Document Section",
		},
		{
			fieldname: "document_type",
			label: __("Document Type"),
			fieldtype: "Link",
			options: "Technical Document Type",
			get_query: () => ({ filters: { requires_completeness: 1 } }),
		},
		{
			fieldname: "responsible",
			label: __("Responsible"),
			fieldtype: "Link",
			options: "User",
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: [""],
		},
		{
			fieldname: "only_incomplete",
			label: __("Incomplete only"),
			fieldtype: "Check",
			default: 0,
		},
	],

	onload(report) {
		frappe.model.with_doctype("Technical Document", () => {
			const filter = report.get_filter("status");
			const field = frappe.meta.get_docfield("Technical Document", "status");
			filter.df.options = [""].concat(field.options.split("\n"));
			filter.refresh();
		});
	},

	formatter(value, row, column, data, default_formatter) {
		const formatted = default_formatter(value, row, column, data);

		if (column.fieldname === "completeness") {
			const colour = data.completeness >= 100 ? "green" : data.completeness ? "orange" : "red";
			return `<span class="indicator-pill ${colour}">${formatted}</span>`;
		}

		return formatted;
	},
};
