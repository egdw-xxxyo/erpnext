const OPPORTUNITY_FINAL_STATUSES = ["Converted to Quotation", "Lost"];

const OPPORTUNITY_STATUS_COLOURS = {
	New: "blue",
	"Converted to Quotation": "green",
	Lost: "red",
};

frappe.listview_settings["Opportunity"] = {
	add_fields: [
		"customer_name",
		"opportunity_type",
		"opportunity_from",
		"status",
		"opportunity_owner",
		"sales_stage",
		"next_action_type",
		"next_action_date",
		"next_action_overdue",
	],
	// Closed Opportunities stay out of the way until someone asks for them explicitly.
	filters: [["status", "not in", OPPORTUNITY_FINAL_STATUSES]],
	// Plain ASC would float Opportunities without a date above the urgent ones, so park them last.
	order_by: "ifnull(`tabOpportunity`.next_action_date, '2999-12-31') asc",
	get_indicator: function (doc) {
		if (doc.next_action_overdue && !OPPORTUNITY_FINAL_STATUSES.includes(doc.status)) {
			return [__("Overdue"), "red", "next_action_overdue,=,1"];
		}
		return [
			__(doc.status),
			OPPORTUNITY_STATUS_COLOURS[doc.status] || frappe.utils.guess_colour(doc.status),
			"status,=," + doc.status,
		];
	},
	formatters: {
		opportunity_owner: function (value) {
			if (!value) return "";
			const full_name = frappe.user_info(value).fullname || value;
			return `<span class="filterable ellipsis" data-filter="opportunity_owner,=,${value}">${full_name}</span>`;
		},
	},
	onload: function (listview) {
		const apply_preset = (filters) => {
			listview.filter_area.clear().then(() => {
				listview.filter_area.add(filters).then(() => listview.refresh());
			});
		};

		listview.page.add_inner_button(
			__("My Opportunities"),
			() => apply_preset([["Opportunity", "opportunity_owner", "=", frappe.session.user]]),
			__("Filters")
		);
		listview.page.add_inner_button(
			__("Active Opportunities"),
			() => apply_preset([["Opportunity", "status", "not in", OPPORTUNITY_FINAL_STATUSES]]),
			__("Filters")
		);
		listview.page.add_inner_button(
			__("Overdue Next Action"),
			() => apply_preset([["Opportunity", "next_action_overdue", "=", 1]]),
			__("Filters")
		);

		if (listview.page.fields_dict.opportunity_from) {
			listview.page.fields_dict.opportunity_from.get_query = function () {
				return {
					filters: {
						name: ["in", ["Customer", "Lead", "Prospect"]],
					},
				};
			};
		}
	},
};
