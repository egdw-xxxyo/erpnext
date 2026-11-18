// Найближчі виплати відпускних: що, кому й до якої дати треба оплатити.

const VACATION_PAYMENTS = "erpnext.payroll_ua.page.vacation_payments.vacation_payments";

frappe.pages["vacation-payments"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Vacation Payments"),
		single_column: true,
	});
	const state = { rows: [] };

	const company = page.add_field({
		fieldname: "company",
		fieldtype: "Link",
		options: "Company",
		label: __("Company"),
		default: frappe.defaults.get_user_default("Company"),
		change: () => load(),
	});
	const horizon = page.add_field({
		fieldname: "horizon",
		fieldtype: "Int",
		label: __("Days Ahead"),
		default: 60,
		change: () => load(),
	});
	page.set_secondary_action(__("Refresh"), () => load(), "refresh");

	const $body = $(`<div class="vacation-payments" style="padding: 12px 0"></div>`).appendTo(page.main);

	function load() {
		if (!company.get_value()) return;

		frappe
			.call({
				method: `${VACATION_PAYMENTS}.get_data`,
				args: { company: company.get_value(), horizon: horizon.get_value() || 60 },
				freeze: true,
			})
			.then(({ message }) => {
				state.rows = message.rows || [];
				render(message);
			});
	}

	function money(value) {
		return format_currency(flt(value), frappe.defaults.get_default("currency"));
	}

	function when(row) {
		const left = cint(row.days_left);

		if (left < 0) {
			return `<span class="indicator-pill red">${__("Late by {0} d", [-left])}</span>`;
		}

		if (left === 0) {
			return `<span class="indicator-pill orange">${__("Today")}</span>`;
		}

		return `<span class="indicator-pill ${left <= 3 ? "yellow" : "blue"}">${__("In {0} d", [
			left,
		])}</span>`;
	}

	function render(data) {
		if (!state.rows.length) {
			$body.html(`<p class="text-muted">${__("No unpaid vacations ahead.")}</p>`);
			return;
		}

		const lines = state.rows
			.map((row, index) => {
				const person = erpnext.entity.html({
					name: row.employee_name || row.employee,
					sub: row.department,
					key: row.employee,
					route: ["Form", "Employee", row.employee],
					size: 28,
				});
				const earlier = cint(row.earlier_days)
					? `<br><small class="text-muted">${__("plus {0} earlier unpaid days", [
							cint(row.earlier_days),
					  ])}</small>`
					: "";

				return `<tr>
					<td>${person}</td>
					<td>${frappe.datetime.str_to_user(row.first_day)} – ${frappe.datetime.str_to_user(row.last_day)}</td>
					<td class="text-right">${cint(row.days)}${earlier}</td>
					<td>${frappe.datetime.str_to_user(row.due_date)}<br>${when(row)}</td>
					<td class="text-right" title="${frappe.utils.escape_html(row.average_note)}">${money(row.average)}</td>
					<td class="text-right">${money(row.gross)}</td>
					<td class="text-right"><b>${money(row.net)}</b></td>
					<td><button class="btn btn-xs btn-primary" data-index="${index}">${__("Pay")}</button></td>
				</tr>`;
			})
			.join("");

		$body.html(`
			<p class="text-muted">${__(
				"Vacation pay is due {0} d before the first vacation day (Payroll Tax Settings).",
				[cint(data.pay_before_days)]
			)}</p>
			<table class="table table-bordered">
				<thead><tr>
					<th>${__("Employee")}</th>
					<th>${__("Vacation")}</th>
					<th class="text-right">${__("Days")}</th>
					<th>${__("Pay Not Later Than")}</th>
					<th class="text-right">${__("Average Daily Wage")}</th>
					<th class="text-right">${__("Accrued")}</th>
					<th class="text-right">${__("To Card")}</th>
					<th></th>
				</tr></thead>
				<tbody>${lines}</tbody>
			</table>`);

		$body
			.find("button[data-index]")
			.on("click", (event) => ask_payment(state.rows[cint($(event.currentTarget).data("index"))]));
	}

	function ask_payment(row) {
		frappe.prompt(
			[
				{
					fieldtype: "HTML",
					fieldname: "details",
					options: `<p>${__("{0} d: {1} accrued, {2} to the card.", [
						cint(row.pay_days),
						money(row.gross),
						money(row.net),
					])}</p>`,
				},
				{
					fieldname: "posting_date",
					fieldtype: "Date",
					label: __("Payment Date"),
					default: frappe.datetime.get_today(),
					reqd: 1,
				},
			],
			(values) =>
				frappe
					.call({
						method: `${VACATION_PAYMENTS}.pay`,
						args: {
							company: company.get_value(),
							employee: row.employee,
							last_day: row.last_day,
							days: row.pay_days,
							posting_date: values.posting_date,
						},
						freeze: true,
						freeze_message: __("Working..."),
					})
					.then(({ message }) => {
						frappe.show_alert({
							message: __("Paid through {0}", [message.sheet]),
							indicator: "green",
						});
						load();
					}),
			__("Pay {0}", [row.employee_name || row.employee]),
			__("Post")
		);
	}

	load();
};
