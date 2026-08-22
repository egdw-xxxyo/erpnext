// Оклади працівника по періодах — прямо на картці, щоб не шукати призначення структури.
// Джерело те саме, що й у звіті «Історія окладів»: подані Salary Structure Assignment.

frappe.ui.form.on("Employee", {
	refresh(frm) {
		if (frm.is_new()) return;

		frappe
			.call({
				method: "erpnext.payroll_ua.salary_history.get_salary_history",
				args: { employee: frm.doc.name },
			})
			.then((response) => render(frm, response.message || []));
	},
});

function render(frm, history) {
	if (!history.length) return;

	const date = (value) => (value ? frappe.format(value, { fieldtype: "Date" }) : "…");
	const money = (value) => format_currency(flt(value), frappe.defaults.get_default("currency"));

	const rows = history
		.slice()
		.reverse()
		.map((row) => {
			const label = { Past: __("Past"), Current: __("Current"), Future: __("Future") }[row.period];
			const style =
				row.period === "Current"
					? "font-weight: bold;"
					: row.period === "Future"
					? "color: var(--blue-600);"
					: "color: var(--text-muted);";

			return `<tr style="${style}">
				<td>${date(row.from_date)} — ${date(row.to_date)}</td>
				<td class="text-right">${money(row.official)}</td>
				<td class="text-right">${money(row.cash)}</td>
				<td class="text-right">${money(row.total)}</td>
				<td class="text-right">${row.change ? money(row.change) : ""}</td>
				<td>${label}</td>
			</tr>`;
		})
		.join("");

	const html = `
		<table class="table table-bordered" style="margin: 0;">
			<thead>
				<tr>
					<th>${__("Period")}</th>
					<th class="text-right">${__("Official Salary")}</th>
					<th class="text-right">${__("Cash Salary")}</th>
					<th class="text-right">${__("Total Salary")}</th>
					<th class="text-right">${__("Change")}</th>
					<th>${__("Status")}</th>
				</tr>
			</thead>
			<tbody>${rows}</tbody>
		</table>`;

	frm.dashboard.add_section(html, __("Salary History"));
}
