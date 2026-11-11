// Заробіток по місяцях на картці працівника: що нараховано й виплачено, і з чого рахується середня.
// Сервер: `erpnext.payroll_ua.earnings_history.get_earnings`.

frappe.ui.form.on("Employee", {
	refresh(frm) {
		if (frm.is_new() || erpnext.sensitive_data.masked_here(frm).length) return;
		if (!frappe.model.can_read("Payroll Sheet")) return;

		frm.add_custom_button(__("Earnings by Month"), () => show_earnings(frm), __("View"));
		frm.add_custom_button(
			__("Enforcement Orders"),
			() => frappe.set_route("List", "Enforcement Order", { employee: frm.doc.name }),
			__("View")
		);
	},
});

function show_earnings(frm) {
	frappe
		.call({
			method: "erpnext.payroll_ua.earnings_history.get_earnings",
			args: { employee: frm.doc.name },
			freeze: true,
		})
		.then(({ message }) => render_earnings(frm, message || []));
}

function render_earnings(frm, rows) {
	const money = (value) =>
		flt(value) ? format_currency(flt(value), frappe.defaults.get_default("currency"), 2) : "";
	const days = (value) => (flt(value) ? __("{0} d", [flt(value)]) : "");
	const source = { ERP: __("ERP"), "Before ERP": __("Before ERP") };
	const month = (value) => moment(value).format("MM.YYYY");

	const body = rows
		.map(
			(row) => `<tr${row.source ? "" : ' class="text-muted"'}>
				<td>${month(row.month)}</td>
				<td>${source[row.source] || "—"}</td>
				<td class="text-right">${money(row.official)}</td>
				<td class="text-right">${money(row.official_paid)}</td>
				<td class="text-right">${money(row.cash)}</td>
				<td class="text-right">${money(row.cash_paid)}</td>
				<td class="text-right">${money(row.vacation_pay)} ${days(row.vacation_days)}</td>
				<td class="text-right">${money(row.sick_employer)} ${days(row.sick_days)}</td>
				<td class="text-right">${money(row.sick_fund)}</td>
				<td class="text-right">${days(row.unpaid_days)}</td>
				<td class="text-right"><b>${money(row.for_average)}</b></td>
			</tr>`
		)
		.join("");

	const dialog = new frappe.ui.Dialog({
		title: __("Earnings by Month: {0}", [frm.doc.employee_name || frm.doc.name]),
		size: "extra-large",
		fields: [{ fieldtype: "HTML", fieldname: "table" }],
	});

	dialog.fields_dict.table.$wrapper.html(`
		<p class="text-muted">${__(
			"Built from the paid payroll, management, vacation sheets and sick leave cases; months before ERP come from the Earnings Before ERP table on this card."
		)}</p>
		<div style="overflow-x: auto">
		<table class="table table-bordered table-sm">
			<thead><tr>
				<th>${__("Month")}</th>
				<th>${__("Source")}</th>
				<th class="text-right">${__("Official Accrued")}</th>
				<th class="text-right">${__("Official Paid to Card")}</th>
				<th class="text-right">${__("Cash Accrued")}</th>
				<th class="text-right">${__("Cash Paid")}</th>
				<th class="text-right">${__("Vacation Pay")}</th>
				<th class="text-right">${__("Sick Pay (Employer)")}</th>
				<th class="text-right">${__("Sick Pay (Fund)")}</th>
				<th class="text-right">${__("Unpaid Leave")}</th>
				<th class="text-right">${__("For the Average")}</th>
			</tr></thead>
			<tbody>${body || `<tr><td colspan="11" class="text-muted">${__("No months yet.")}</td></tr>`}</tbody>
		</table></div>`);
	dialog.show();
}
