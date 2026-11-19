// Випадок лікарняного: розрахунок за законом і дві виплати — роботодавця (із зарплатою) і фонду.

frappe.ui.form.on("Sick Leave Case", {
	refresh(frm) {
		render_calculation(frm);

		if (frm.is_new()) return;

		show_status(frm);

		if (frm.doc.docstatus === 0 && !frm.doc.employer_paid_date) {
			frm.add_custom_button(__("Recalculate"), () => recalculate(frm));
		}

		if (frm.doc.docstatus !== 1) return;

		if (cint(frm.doc.fund_days) && !frm.doc.je_fund_receipt) {
			frm.add_custom_button(__("Money Received from Fund"), () => ask_receipt(frm), __("Fund"));
		}

		if (frm.doc.je_fund_receipt && !frm.doc.fund_paid_date) {
			frm.add_custom_button(__("Pay Fund Part to Employee"), () => ask_payment(frm), __("Fund"));
		}
	},
});

// Лікарняний спершу відмічають у табелі: новий випадок підтягує ці дні, щоб їх не
// вводили вдруге.
frappe.ui.form.on("Sick Leave Case", {
	employee(frm) {
		if (!frm.is_new() || !frm.doc.employee) return;
		if ((frm.doc.certificates || []).some((row) => row.from_date)) return;

		frappe
			.xcall("erpnext.payroll_ua.doctype.sick_leave_case.sick_leave_case.get_unregistered_days", {
				employee: frm.doc.employee,
			})
			.then((runs) => {
				if (!runs || !runs.length) return;

				// одна хвороба — один випадок: беремо найсвіжіший відрізок, решта лишається
				// для «Знайти незареєстровані лікарняні»
				const run = runs[runs.length - 1];

				frm.clear_table("certificates");
				frm.add_child("certificates", { from_date: run.from_date, to_date: run.to_date });
				frm.refresh_field("certificates");
				frappe.show_alert({
					message: __("Sick days from the timesheet: {0} — {1}", [
						frappe.datetime.str_to_user(run.from_date),
						frappe.datetime.str_to_user(run.to_date),
					]),
					indicator: "blue",
				});
			});
	},
});

frappe.ui.form.on("Sick Leave Certificate", {
	certificates_add(frm, cdt, cdn) {
		const last = (frm.doc.certificates || [])
			.filter((row) => row.name !== cdn && row.to_date)
			.map((row) => row.to_date)
			.sort()
			.pop();
		if (last) frappe.model.set_value(cdt, cdn, "from_date", frappe.datetime.add_days(last, 1));
	},
	from_date(frm, cdt, cdn) {
		set_days(cdt, cdn);
	},
	to_date(frm, cdt, cdn) {
		set_days(cdt, cdn);
		render_calculation(frm);
	},
});

function set_days(cdt, cdn) {
	const row = locals[cdt][cdn];
	const days =
		row.from_date && row.to_date ? frappe.datetime.get_day_diff(row.to_date, row.from_date) + 1 : 0;
	frappe.model.set_value(cdt, cdn, "days", days > 0 ? days : null);
}

function show_status(frm) {
	const colors = {
		Open: "orange",
		Closed: "blue",
		"Employer Paid": "yellow",
		"Fund Received": "purple",
		Paid: "green",
		Cancelled: "red",
	};
	frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");

	const without_number = (frm.doc.certificates || []).filter((row) => !(row.eln_number || "").trim());

	if (frm.doc.limit_warning) {
		frm.dashboard.add_comment(
			frappe.utils.escape_html(frm.doc.limit_warning).replace(/\n/g, "<br>"),
			"yellow",
			true
		);
	}

	if (frm.doc.docstatus === 0 && without_number.length) {
		frm.dashboard.add_comment(
			__(
				"No ЕЛН number for {0} certificates yet: it appears once the ЕЛН is processed in the ПФУ e-services portal. The case can be submitted only with all numbers.",
				[without_number.length]
			),
			"yellow",
			true
		);
	}

	if (frm.doc.docstatus === 0) {
		frm.dashboard.add_comment(
			__(
				"The case is open: submit it when the last certificate (ЕЛН) is received — then the employer part goes into the salary and the case can no longer be changed."
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
