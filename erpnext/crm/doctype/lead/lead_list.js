const LEAD_FINAL_STATUSES = ["Converted to Opportunity", "Not Relevant", "Lost"];

const LEAD_STATUS_COLOURS = {
	"New Request": "blue",
	Contacted: "orange",
	"Requirement Gathering": "purple",
	"Awaiting Response": "yellow",
	"Result of Processing": "cyan",
	Postponed: "gray",
	"Converted to Opportunity": "green",
	"Not Relevant": "gray",
	Lost: "red",
};

frappe.listview_settings["Lead"] = {
	// The ID carries no meaning for sales — the unit, the organization and the contact do.
	hide_name_column: true,
	add_fields: [
		"status",
		"lead_owner",
		"military_unit",
		"company_name",
		"contact_person",
		"contact_display",
		"next_action_date",
		"next_action_overdue",
		"required_month",
	],
	// Closed Leads stay out of the way until someone asks for them explicitly.
	filters: [["status", "not in", LEAD_FINAL_STATUSES]],
	// Plain ASC would float Leads without a date above the urgent ones, so park them last.
	order_by: "ifnull(`tabLead`.next_action_date, '2999-12-31') asc",
	get_indicator: function (doc) {
		if (doc.next_action_overdue && !LEAD_FINAL_STATUSES.includes(doc.status)) {
			return [__("Overdue"), "red", "next_action_overdue,=,1"];
		}
		return [
			__(doc.status),
			LEAD_STATUS_COLOURS[doc.status] || frappe.utils.guess_colour(doc.status),
			"status,=," + doc.status,
		];
	},
	formatters: {
		required_month: function (value) {
			if (!value) {
				return `<span class="text-muted">${__("Unknown")}</span>`;
			}
			const label = erpnext.utils.month_field.format_month(value);
			return `<span class="filterable ellipsis" data-filter="required_month,=,${value}">${label}</span>`;
		},
		lead_owner: function (value) {
			if (!value) return "";
			// Not frappe.user.full_name — that renders "You" for your own Leads, and the
			// point of the column is to see whose Lead it is at a glance.
			const full_name = frappe.user_info(value).fullname || value;
			return `<span class="filterable ellipsis" data-filter="lead_owner,=,${value}">${full_name}</span>`;
		},
	},
	onload: function (listview) {
		const apply_preset = (filters) => {
			listview.filter_area.clear().then(() => {
				listview.filter_area.add(filters).then(() => listview.refresh());
			});
		};

		listview.page.add_inner_button(
			__("My Leads"),
			() => apply_preset([["Lead", "owner", "=", frappe.session.user]]),
			__("Filters")
		);
		listview.page.add_inner_button(
			__("Assigned to Me"),
			() => apply_preset([["Lead", "lead_owner", "=", frappe.session.user]]),
			__("Filters")
		);
		listview.page.add_inner_button(
			__("Active Leads"),
			() => apply_preset([["Lead", "status", "not in", LEAD_FINAL_STATUSES]]),
			__("Filters")
		);
		listview.page.add_inner_button(
			__("Overdue Next Action"),
			() => apply_preset([["Lead", "next_action_overdue", "=", 1]]),
			__("Filters")
		);

		if (frappe.boot.user.can_create.includes("Prospect")) {
			listview.page.add_action_item(__("Create Prospect"), function () {
				frappe.model.with_doctype("Prospect", function () {
					let prospect = frappe.model.get_new_doc("Prospect");
					let leads = listview.get_checked_items();
					frappe.db.get_value(
						"Lead",
						leads[0].name,
						[
							"company_name",
							"no_of_employees",
							"industry",
							"market_segment",
							"territory",
							"fax",
							"website",
							"lead_owner",
						],
						(r) => {
							prospect.company_name = r.company_name;
							prospect.no_of_employees = r.no_of_employees;
							prospect.industry = r.industry;
							prospect.market_segment = r.market_segment;
							prospect.territory = r.territory;
							prospect.fax = r.fax;
							prospect.website = r.website;
							prospect.prospect_owner = r.lead_owner;

							leads.forEach(function (lead) {
								let lead_prospect_row = frappe.model.add_child(prospect, "leads");
								lead_prospect_row.lead = lead.name;
							});
							frappe.set_route("Form", "Prospect", prospect.name);
						}
					);
				});
			});
		}
	},
};
