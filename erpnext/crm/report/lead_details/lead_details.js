// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Lead Details"] = {
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
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -12),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: [
				{ value: "New Request", label: __("New Request") },
				{ value: "Contacted", label: __("Contacted") },
				{ value: "Requirement Gathering", label: __("Requirement Gathering") },
				{ value: "Awaiting Response", label: __("Awaiting Response") },
				{ value: "Postponed", label: __("Postponed") },
				{ value: "Converted to Opportunity", label: __("Converted to Opportunity") },
				{ value: "Not Relevant", label: __("Not Relevant") },
				{ value: "Lost", label: __("Lost") },
			],
		},
		{
			fieldname: "territory",
			label: __("Territory"),
			fieldtype: "Link",
			options: "Territory",
		},
	],
};
