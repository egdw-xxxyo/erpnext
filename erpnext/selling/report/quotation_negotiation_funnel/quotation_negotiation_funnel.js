// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Quotation Negotiation Funnel"] = {
	filters: [
		{
			fieldname: "opportunity",
			label: __("Opportunity"),
			fieldtype: "Link",
			options: "Opportunity",
		},
		{
			fieldname: "quotation",
			label: __("Quotation"),
			fieldtype: "Link",
			options: "Quotation",
		},
	],
};
