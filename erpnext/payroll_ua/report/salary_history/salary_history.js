frappe.query_reports["Salary History"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "employee",
			label: __("Employee"),
			fieldtype: "Link",
			options: "Employee",
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
		},
	],

	// The future rows are the point of the report: they must be visible at a glance.
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (data && data.period === __("Future")) {
			value = `<span style="color: var(--blue-600);">${value}</span>`;
		} else if (data && data.period === __("Current")) {
			value = `<b>${value}</b>`;
		}

		return value;
	},
};
