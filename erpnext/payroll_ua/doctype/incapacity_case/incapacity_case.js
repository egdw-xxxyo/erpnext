frappe.ui.form.on("Incapacity Case", {
	refresh(frm) {
		frm.toggle_display("section_break_cases", !frm.is_new());
		if (frm.is_new()) {
			const field = frm.get_field("sick_leave_cases_html");
			if (field) field.$wrapper.empty();
			return;
		}

		frm.page.set_indicator(__(frm.doc.status), frm.doc.status === "Closed" ? "blue" : "orange");
		frm.add_custom_button(__("New Sick Leave Case"), () => {
			frappe.new_doc("Sick Leave Case", {
				incapacity_case: frm.doc.name,
				employee: frm.doc.employee,
				company: frm.doc.company,
				case_type: frm.doc.case_type,
				start_date: frm.doc.end_date ? frappe.datetime.add_days(frm.doc.end_date, 1) : null,
			});
		});
		render_sick_leave_cases(frm);
	},
});

const CASE_COLORS = {
	Open: "orange",
	Closed: "blue",
	"Employer Paid": "yellow",
	"Fund Received": "purple",
	Paid: "green",
	Cancelled: "red",
};

function render_sick_leave_cases(frm) {
	const field = frm.get_field("sick_leave_cases_html");
	if (!field) return;

	frappe.db
		.get_list("Sick Leave Case", {
			filters: { incapacity_case: frm.doc.name, docstatus: ["<", 2] },
			fields: [
				"name",
				"eln_number",
				"start_date",
				"end_date",
				"calendar_days",
				"status",
				"percent",
				"average_daily",
				"employer_days",
				"fund_days",
				"employer_gross",
				"fund_gross",
			],
			order_by: "start_date asc",
			limit: 100,
		})
		.then((rows) => {
			if (!rows.length) {
				field.$wrapper.html(`<p class="text-muted">${__("No sick leave cases yet.")}</p>`);
				return;
			}

			const money = (value) => format_currency(flt(value), frappe.defaults.get_default("currency"));
			const sum = (key) => rows.reduce((total, row) => total + flt(row[key]), 0);
			const date = (value) => (value ? frappe.datetime.str_to_user(value) : "");
			const esc = frappe.utils.escape_html;

			new erpnext.DataTable({
				parent: field.$wrapper,
				storage_key: "incapacity-sick-cases",
				max_height: "420px",
				rows,
				columns: [
					{
						key: "name",
						label: __("Case"),
						pin: true,
						nowrap: true,
						html: (row) => `<a href="/desk/sick-leave-case/${encodeURIComponent(row.name)}">${esc(row.name)}</a>`,
						footer: __("Total"),
					},
					{
						key: "eln_number",
						label: __("Certificate Number (ЕЛН)"),
						nowrap: true,
						html: (row) => esc(row.eln_number || "—"),
					},
					{
						key: "start_date",
						label: __("Period"),
						nowrap: true,
						html: (row) => `${date(row.start_date)} – ${date(row.end_date)}`,
					},
					{
						key: "calendar_days",
						label: __("Calendar Days"),
						align: "right",
						value: (row) => flt(row.calendar_days),
						html: (row) => cint(row.calendar_days),
						footer: sum("calendar_days"),
					},
					{
						key: "employer_days",
						label: __("Employer / Fund Days"),
						align: "right",
						value: (row) => flt(row.employer_days),
						html: (row) => `${cint(row.employer_days)} / ${cint(row.fund_days)}`,
						footer: `${sum("employer_days")} / ${sum("fund_days")}`,
					},
					{
						key: "percent",
						label: __("Pay Percent"),
						align: "right",
						value: (row) => flt(row.percent),
						html: (row) => `${flt(row.percent)}%`,
					},
					{
						key: "average_daily",
						label: __("Average Daily Wage Used"),
						align: "right",
						value: (row) => flt(row.average_daily),
						html: (row) => money(row.average_daily),
					},
					{
						key: "gross",
						label: __("Accrued"),
						align: "right",
						value: (row) => flt(row.employer_gross) + flt(row.fund_gross),
						html: (row) => money(flt(row.employer_gross) + flt(row.fund_gross)),
						footer: money(sum("employer_gross") + sum("fund_gross")),
					},
					{
						key: "status",
						label: __("Status"),
						value: (row) => __(row.status),
						html: (row) =>
							`<span class="indicator-pill ${CASE_COLORS[row.status] || "gray"}">${__(row.status)}</span>`,
					},
				],
			});
		});
}
