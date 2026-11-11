// Випадок лікарняного: розрахунок за законом і дві виплати — роботодавця (із зарплатою) і фонду.

frappe.ui.form.on("Sick Leave Case", {
	refresh(frm) {
		render_calculation(frm);

		if (frm.is_new()) return;

		show_status(frm);

		if (cint(frm.doc.fund_days) && !frm.doc.je_fund_receipt) {
			frm.add_custom_button(__("Money Received from Fund"), () => ask_receipt(frm), __("Fund"));
		}

		if (frm.doc.je_fund_receipt && !frm.doc.fund_paid_date) {
			frm.add_custom_button(__("Pay Fund Part to Employee"), () => ask_payment(frm), __("Fund"));
		}
	},
});

frappe.ui.form.on("Sick Leave Certificate", {
	to_date(frm) {
		render_calculation(frm);
	},
});

function show_status(frm) {
	const colors = {
		Open: "orange",
		Closed: "blue",
		"Employer Paid": "yellow",
		"Fund Received": "purple",
		Paid: "green",
	};
	frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");

	if (!frm.doc.closed) {
		frm.dashboard.add_comment(
			__(
				"The case is open: the employer part goes into the salary once the final certificate is ticked."
			),
			"orange",
			true
		);
	}
}

function money(value) {
	return format_currency(flt(value), frappe.defaults.get_default("currency"));
}

function render_calculation(frm) {
	const field = frm.get_field("calculation_html");
	if (!field) return;

	if (!frm.doc.start_date) {
		field.$wrapper.html(`<p class="text-muted">${__("Save the case to see the calculation.")}</p>`);
		return;
	}

	const row = (label, value) =>
		`<tr><td class="text-muted" style="width:45%">${label}</td><td>${value}</td></tr>`;
	const escape = (text) => frappe.utils.escape_html(text || "").replace(/\n/g, "<br>");

	frappe.db
		.get_value("Employee", frm.doc.employee, [
			"custom_insurance_years",
			"custom_insurance_months",
			"custom_sick_pay_in_full",
			"date_of_joining",
		])
		.then(({ message: employee }) => {
			employee = employee || {};
			const before =
				cint(employee.custom_insurance_years) * 12 + cint(employee.custom_insurance_months);
			const total = cint(frm.doc.insurance_years) * 12 + cint(frm.doc.insurance_months);
			const link = `<a href="/desk/employee/${encodeURIComponent(frm.doc.employee)}">${__(
				"employee card"
			)}</a>`;

			field.$wrapper.html(`
				<table class="table table-bordered table-sm" style="margin-bottom:0">
					${row(
						__("Insurance record"),
						__("{0} y {1} m = before joining {2} m (from the {3}) + here {4} m since {5}", [
							cint(frm.doc.insurance_years),
							cint(frm.doc.insurance_months),
							before,
							link,
							Math.max(total - before, 0),
							employee.date_of_joining
								? frappe.datetime.str_to_user(employee.date_of_joining)
								: "—",
						])
					)}
					${row(__("Pay percent"), `${flt(frm.doc.percent)}% — ${escape(frm.doc.percent_reason)}`)}
					${row(
						__("Average daily wage"),
						`${money(frm.doc.average_daily)}<br><small>${escape(frm.doc.average_note)}</small>`
					)}
					${row(__("Pay per day"), money(frm.doc.daily_pay))}
					${row(
						__("Days"),
						__("{0} calendar days: employer {1}, fund {2}", [
							cint(frm.doc.calendar_days),
							cint(frm.doc.employer_days),
							cint(frm.doc.fund_days),
						])
					)}
					${row(
						__("Employer part (with the salary)"),
						__("{0} accrued, {1} to the card", [
							money(frm.doc.employer_gross),
							money(frm.doc.employer_net),
						])
					)}
					${row(
						__("Fund part (when the money arrives)"),
						__("{0} accrued, {1} to the card", [
							money(frm.doc.fund_gross),
							money(frm.doc.fund_net),
						])
					)}
				</table>`);
		});
}

function ask_receipt(frm) {
	frappe.prompt(
		[
			{
				fieldname: "posting_date",
				fieldtype: "Date",
				label: __("Received On"),
				default: frappe.datetime.get_today(),
				reqd: 1,
			},
			{
				fieldname: "amount",
				fieldtype: "Currency",
				label: __("Amount Received"),
				default: flt(frm.doc.fund_expected),
				reqd: 1,
			},
		],
		(values) => run(frm, "receive_fund", values),
		__("Money Received from Fund"),
		__("Post")
	);
}

function ask_payment(frm) {
	frappe.prompt(
		[
			{
				fieldtype: "HTML",
				fieldname: "details",
				options: `<p>${__("{0} accrued, {1} to the card.", [
					money(frm.doc.fund_gross),
					money(frm.doc.fund_net),
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
		(values) => run(frm, "pay_fund", values),
		__("Pay Fund Part to Employee"),
		__("Post")
	);
}

function run(frm, method, args) {
	return frm
		.call({ doc: frm.doc, method, args, freeze: true, freeze_message: __("Working...") })
		.then(() => frm.reload_doc());
}
