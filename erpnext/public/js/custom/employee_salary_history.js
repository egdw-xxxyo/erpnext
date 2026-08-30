// Оклади працівника по періодах — прямо на картці, щоб не шукати призначення структури.
// Джерело те саме, що й у звіті «Історія окладів»: подані Salary Structure Assignment.

frappe.ui.form.on("Employee", {
	// «Нараховано на картку» рахує сервер при збереженні, але правлять оклад тут і зараз —
	// тож поки поле в руках, показуємо результат одразу.
	custom_official_salary(frm) {
		show_card_amount(frm);
	},

	refresh(frm) {
		show_card_amount(frm);

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
					<th class="text-right">${__("Mgmt. Salary")}</th>
					<th class="text-right">${__("Total Salary")}</th>
					<th class="text-right">${__("Change")}</th>
					<th>${__("Status")}</th>
				</tr>
			</thead>
			<tbody>${rows}</tbody>
		</table>`;

	frm.dashboard.add_section(html, __("Salary History"));
}

// Ставки живуть у «Налаштуваннях зарплатних податків» — беремо їх звідти, а не з коду,
// інакше картка почне розходитися з листком наступного ж дня після зміни закону.
function show_card_amount(frm) {
	const gross = flt(frm.doc.custom_official_salary);

	if (!gross) {
		frm.set_value("custom_official_salary_net", 0);
		return;
	}

	withheld_rates().then(([pit, levy]) => {
		const net = flt(gross - flt(gross * pit, 2) - flt(gross * levy, 2), 2);
		frm.set_value("custom_official_salary_net", net);
	});
}

function withheld_rates() {
	if (!withheld_rates.promise) {
		withheld_rates.promise = Promise.all([
			frappe.db.get_single_value("Payroll Tax Settings", "pit_rate"),
			frappe.db.get_single_value("Payroll Tax Settings", "military_levy_rate"),
		]).then(([pit, levy]) => [flt(pit || 18) / 100, flt(levy || 5) / 100]);
	}

	return withheld_rates.promise;
}
