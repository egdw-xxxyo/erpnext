frappe.query_reports["Scanner Scan Logs"] = {
	filters: [
		{
			fieldname: "scanner",
			label: __("Scanner"),
			fieldtype: "Link",
			options: "Scanner",
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: ["", "Processing", "Success", "Error", "Command"],
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Datetime",
			default: frappe.datetime.add_days(frappe.datetime.now_datetime(), -1),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Datetime",
		},
		{
			fieldname: "only_slow",
			label: __("Only Slow Scans"),
			fieldtype: "Check",
		},
		{
			fieldname: "slow_ms",
			label: __("Slower Than (ms)"),
			fieldtype: "Int",
			default: 1000,
			depends_on: "only_slow",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "status" && data) {
			const colors = { Error: "red", Success: "green", Processing: "orange" };
			const color = colors[data.status];
			if (color) {
				value = `<span style="color: var(--text-on-${color}, inherit)">${value}</span>`;
			}
		}
		if (column.fieldname === "total_ms" && data && data.total_ms > 1000) {
			value = `<span style="color: var(--red-500)">${value}</span>`;
		}
		return value;
	},
};
