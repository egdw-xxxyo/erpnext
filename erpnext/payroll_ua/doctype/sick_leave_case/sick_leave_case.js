// Випадок лікарняного: розрахунок за законом і дві виплати — роботодавця (із зарплатою) і фонду.

frappe.ui.form.on("Sick Leave Case", {
	refresh(frm) {
		render_calculation(frm);

		if (frm.is_new()) return;

		show_status(frm);

		if (frm.doc.docstatus === 0 && !frm.doc.employer_paid_date) {
			frm.add_custom_button(__("Recalculate"), () => recalculate(frm));
		}

		if (frm.doc.docstatus === 2) return;

		add_social_buttons(frm);

		if (frm.doc.docstatus !== 1) return;

		if (frm.doc.je_fund_receipt && !frm.doc.fund_paid_date) {
			frm.add_custom_button(__("Pay Fund Part to Employee"), () => ask_payment(frm), __("Fund"));
		}
	},
});

// Лікарняний спершу відмічають у табелі: новий випадок підтягує ці дні, щоб їх не
// вводили вдруге.
frappe.ui.form.on("Sick Leave Case", {
	incapacity_case(frm) {
		if (!frm.doc.incapacity_case) return;

		frappe.db
			.get_value("Incapacity Case", frm.doc.incapacity_case, [
				"employee",
				"company",
				"case_type",
				"end_date",
			])
			.then(({ message }) => {
				if (!message) return;
				frm.set_value({
					employee: message.employee,
					company: message.company,
					case_type: message.case_type,
				});

				if (!frm.doc.start_date && message.end_date) {
					frm.set_value("start_date", frappe.datetime.add_days(message.end_date, 1));
				}
			});
	},

	employee(frm) {
		if (!frm.is_new() || !frm.doc.employee || frm.doc.start_date || frm.doc.incapacity_case) return;

		frappe
			.xcall("erpnext.payroll_ua.doctype.sick_leave_case.sick_leave_case.get_unregistered_days", {
				employee: frm.doc.employee,
			})
			.then((runs) => {
				if (!runs || !runs.length) return;

				// одна хвороба — один випадок: беремо найсвіжіший відрізок, решта лишається
				// для «Знайти незареєстровані лікарняні»
				const run = runs[runs.length - 1];

				frm.set_value({ start_date: run.from_date, end_date: run.to_date });
				frappe.show_alert({
					message: __("Sick days from the timesheet: {0} — {1}", [
						frappe.datetime.str_to_user(run.from_date),
						frappe.datetime.str_to_user(run.to_date),
					]),
					indicator: "blue",
				});
			});
	},

	end_date(frm) {
		render_calculation(frm);
	},

	average_details_button(frm) {
		show_average_dialog(frm);
	},
});

const SOCIAL_STATUS_COLORS = {
	"Not Required": "gray",
	"Not Requested": "gray",
	"Requested, Waiting for Money": "orange",
	"Money Received, Waiting for Payment": "purple",
	"Paid by Social Security": "green",
};

function add_social_buttons(frm) {
	const group = __("Social Security");
	const flow = [
		["Not Requested", __("Not Requested"), __("Not Requested")],
		["Requested, Waiting for Money", __("Application Submitted"), __("Requested, Waiting for Money")],
		[
			"Money Received, Waiting for Payment",
			__("Confirm Money Received"),
			__("Money Received, Waiting for Payment"),
		],
		["Paid by Social Security", __("Confirm Payment"), __("Paid by Social Security")],
	];
	const current = flow.findIndex(([status]) => status === frm.doc.social_status);
	const add = (status, label) => frm.add_custom_button(label, () => set_social_status(frm, status), group);
	let shown = false;

	if (current >= 0 && current + 1 < flow.length) {
		add(flow[current + 1][0], flow[current + 1][1]);
		shown = true;
	}

	if (current > 0) {
		if (shown) frm.page.add_divider_to_button_group(group);
		add(flow[current - 1][0], __("Back to: {0}", [flow[current - 1][2]]));
		shown = true;
	}

	const others = [
		...flow.map(([status, , label], index) => [status, label, index]),
		["Not Required", __("Not Required"), -1],
	].filter(
		([status, , index]) =>
			status !== frm.doc.social_status &&
			(index < 0 || current < 0 || (index !== current + 1 && index !== current - 1))
	);

	if (others.length) {
		if (shown) frm.page.add_divider_to_button_group(group);
		others.forEach(([status, label]) => add(status, label));
	}

	frm.dashboard.add_comment(
		`${__("Social Security Status")}: <b>${__(frm.doc.social_status || "Not Requested")}</b>` +
			(frm.doc.social_status_date
				? ` (${frappe.datetime.str_to_user(frm.doc.social_status_date)})`
				: ""),
		SOCIAL_STATUS_COLORS[frm.doc.social_status] || "gray",
		true
	);
}

function set_social_status(frm, status) {
	if (
		status === "Money Received, Waiting for Payment" &&
		frm.doc.docstatus === 1 &&
		cint(frm.doc.fund_days) &&
		!frm.doc.je_fund_receipt
	) {
		ask_receipt(frm);
		return;
	}

	frappe.prompt(
		[
			{
				fieldname: "status_date",
				fieldtype: "Date",
				label: __("Status Date"),
				default: frappe.datetime.get_today(),
				reqd: 1,
			},
		],
		(values) => run(frm, "set_social_status", { status, status_date: values.status_date }),
		__(status),
		__("Set")
	);
}

function show_average_dialog(frm) {
	if (!frm.doc.employee || !frm.doc.start_date) {
		frappe.msgprint(__("Save the case to see the calculation."));
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Average Daily Wage Calculation"),
		size: "extra-large",
		fields: [
			{
				fieldname: "mode",
				fieldtype: "Select",
				label: __("Calculation Period"),
				options: [
					{ value: "auto", label: __("Standard, set automatically") },
					{ value: "manual", label: __("Set by hand") },
				],
				default: frm.doc.average_period_start ? "manual" : "auto",
				onchange: () => load(),
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "from_month",
				fieldtype: "Date",
				label: __("From Month"),
				depends_on: "eval:doc.mode=='manual'",
				default: frm.doc.average_period_start,
				onchange: () => load(),
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "to_month",
				fieldtype: "Date",
				label: __("To Month"),
				depends_on: "eval:doc.mode=='manual'",
				default: frm.doc.average_period_end,
				onchange: () => load(),
			},
			{ fieldtype: "Section Break" },
			{ fieldname: "table", fieldtype: "HTML" },
		],
		primary_action_label: __("Use This Period"),
		primary_action(values) {
			const manual = values.mode === "manual" && values.from_month && values.to_month;

			frm.set_value({
				average_period_start: manual ? first_of_month(values.from_month) : null,
				average_period_end: manual ? first_of_month(values.to_month) : null,
				average_override: null,
			});
			dialog.hide();
			frappe.show_alert({ message: __("Save the case to apply the period."), indicator: "blue" });
		},
	});

	const money = (value) => format_currency(flt(value), frappe.defaults.get_default("currency"));
	const first_of_month = (date) => `${(date || "").slice(0, 7)}-01`;

	function load() {
		const values = dialog.get_values(true) || {};
		const manual = values.mode === "manual" && values.from_month && values.to_month;

		frappe
			.xcall("erpnext.payroll_ua.doctype.sick_leave_case.sick_leave_case.average_breakdown", {
				employee: frm.doc.employee,
				start_date: frm.doc.start_date,
				incapacity_case: frm.doc.incapacity_case,
				from_month: manual ? first_of_month(values.from_month) : null,
				to_month: manual ? first_of_month(values.to_month) : null,
			})
			.then((data) => render(data));
	}

	function render(data) {
		const cells = (fn) =>
			data.rows
				.map((row) =>
					row.no_data
						? `<td class="text-right text-muted">—</td>`
						: `<td class="text-right">${fn(row)}</td>`
				)
				.join("");
		const row = (label, total, fn) =>
			`<tr><td><b>${label}</b></td><td class="text-right">${total}</td>${cells(fn)}</tr>`;
		const note = [];

		const empty = data.rows.filter((r) => r.no_data).map((r) => r.label);
		if (empty.length)
			note.push(
				__("No earnings data for: {0} (Payroll Sheet or Earnings Before ERP).", [empty.join(", ")])
			);
		if (empty.length)
			note.push(__("Full history of the employee: Employee card → Salary tab → Earnings by Month."));
		if (data.from_salary) note.push(__("No earnings in the period — taken from the official salary."));
		if (data.short_tenure)
			note.push(
				__(
					"Insurance record is {0} months (under 6): the daily wage cannot exceed the minimum wage for the period {1} / {2} = {3}.",
					[data.tenure_months, money(data.limit_wages), data.limit_days, money(data.limit)]
				)
			);
		else
			note.push(
				__("Insurance record is {0} months — the minimum wage rule applies below 6 months.", [
					data.tenure_months,
				])
			);
		if (data.capped)
			note.push(__("Capped: {0} a day instead of {1}.", [money(data.limit), money(data.uncapped)]));

		dialog.get_field("table").$wrapper.html(`
			<div style="overflow-x:auto">
			<table class="table table-bordered table-sm">
				<tr><th></th><th class="text-right">${__("Total")}</th>
					${data.rows.map((r) => `<th class="text-right">${r.label}</th>`).join("")}</tr>
				<tr><td><b>${__("Source")}</b></td><td></td>${data.rows
			.map(
				(r) =>
					`<td class="text-right ${r.source ? "" : "text-muted"}">${
						{ ERP: __("ERP"), "Before ERP": __("Before ERP"), Salary: __("Salary on card") }[
							r.source
						] || __("No data")
					}</td>`
			)
			.join("")}</tr>
				${row(__("Earnings"), data.from_salary ? "" : money(data.earnings), (r) => money(r.earnings))}
				${row(__("Days in Month"), "", (r) => r.month_days)}
				${row(__("Unpaid Leave Days"), "", (r) => r.unpaid_days || "")}
				${row(__("Sick Days"), "", (r) => r.sick_days || "")}
				${row(__("Days Worked (calendar)"), data.from_salary ? "" : data.days, (r) => r.worked_days)}
				${row(__("Minimum Wage"), data.from_salary ? "" : money(data.minimum_wages), (r) =>
					r.minimum_wage ? money(r.minimum_wage) : ""
				)}
			</table></div>
			<p><b>${__("Average Daily Wage")}:</b> ${
			data.from_salary ? `${money(data.salary)} / 30.44` : `${money(data.earnings)} / ${data.days}`
		} = ${money(data.uncapped)}
				→ <b>${money(data.average)}</b></p>
			${note.length ? `<p class="text-muted">${note.join("<br>")}</p>` : ""}
			${
				frm.doc.average_override
					? `<p class="text-muted">${__("Now set by hand: {0} a day.", [
							money(frm.doc.average_override),
					  ])}</p>`
					: ""
			}`);
	}

	dialog.show();
	load();
}

function show_status(frm) {
	const colors = {
		Open: "orange",
		Closed: "blue",
		Cancelled: "red",
	};
	frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");

	if (frm.doc.limit_warning) {
		frm.dashboard.add_comment(
			frappe.utils.escape_html(frm.doc.limit_warning).replace(/\n/g, "<br>"),
			"yellow",
			true
		);
	}

	if (frm.doc.docstatus === 0 && !(frm.doc.eln_number || "").trim()) {
		frm.dashboard.add_comment(
			__(
				"No ЕЛН number yet: it appears once the ЕЛН is processed in the ПФУ e-services portal. The case can be submitted only with the number."
			),
			"yellow",
			true
		);
	}

	if (frm.doc.docstatus === 0) {
		frm.dashboard.add_comment(
			__(
				"The case is open: submit it when the certificate (ЕЛН) is received — then the employer part goes into the salary and the case can no longer be changed."
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

function recalculate(frm) {
	if (frm.is_dirty()) return frm.save();
	return run(frm, "recalculate", {}).then(() =>
		frappe.show_alert({ message: __("Recalculated"), indicator: "green" })
	);
}

function run(frm, method, args) {
	return frm
		.call({ doc: frm.doc, method, args, freeze: true, freeze_message: __("Working...") })
		.then(() => frm.reload_doc());
}
