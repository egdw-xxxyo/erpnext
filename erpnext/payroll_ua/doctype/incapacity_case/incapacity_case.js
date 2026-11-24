frappe.ui.form.on("Incapacity Case", {
	refresh(frm) {
		if (frm.is_new()) return;

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
			const body = rows
				.map(
					(row) => `<tr>
						<td><a href="/desk/sick-leave-case/${encodeURIComponent(row.name)}">${frappe.utils.escape_html(
						row.name
					)}</a></td>
						<td>${frappe.utils.escape_html(row.eln_number || "—")}</td>
						<td>${date(row.start_date)} – ${date(row.end_date)}</td>
						<td class="text-right">${cint(row.calendar_days)}</td>
						<td class="text-right">${cint(row.employer_days)} / ${cint(row.fund_days)}</td>
						<td class="text-right">${flt(row.percent)}%</td>
						<td class="text-right">${money(row.average_daily)}</td>
						<td class="text-right">${money(flt(row.employer_gross) + flt(row.fund_gross))}</td>
						<td><span class="indicator-pill ${CASE_COLORS[row.status] || "gray"}">${__(row.status)}</span></td>
					</tr>`
				)
				.join("");

			field.$wrapper.html(`
				<div style="overflow-x:auto">
				<table class="table table-bordered table-sm">
					<tr>
						<th>${__("Case")}</th>
						<th>${__("Certificate Number (ЕЛН)")}</th>
						<th>${__("Period")}</th>
						<th class="text-right">${__("Calendar Days")}</th>
						<th class="text-right">${__("Employer / Fund Days")}</th>
						<th class="text-right">${__("Pay Percent")}</th>
						<th class="text-right">${__("Average Daily Wage Used")}</th>
						<th class="text-right">${__("Accrued")}</th>
						<th>${__("Status")}</th>
					</tr>
					${body}
					<tr>
						<td colspan="3"><b>${__("Total")}</b></td>
						<td class="text-right"><b>${sum("calendar_days")}</b></td>
						<td class="text-right"><b>${sum("employer_days")} / ${sum("fund_days")}</b></td>
						<td></td>
						<td></td>
						<td class="text-right"><b>${money(sum("employer_gross") + sum("fund_gross"))}</b></td>
						<td></td>
					</tr>
				</table></div>`);
		});
}
