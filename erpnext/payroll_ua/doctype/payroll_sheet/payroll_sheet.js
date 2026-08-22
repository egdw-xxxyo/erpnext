frappe.ui.form.on("Payroll Sheet", {
	onload(frm) {
		erpnext.utils.month_field.apply_period(frm, "period_start");
	},

	refresh(frm) {
		erpnext.utils.month_field.apply_period(frm, "period_start");
		render_preview(frm);

		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(__("Refresh from HRMS"), () => run(frm, "refresh_data"));

		// Без затверджених премій місяць не рахується: нарахований листок довелося б
		// скасовувати, щоб додати премію.
		if (!frm.doc.payroll_entry && frm.doc.bonus_approved) {
			frm.add_custom_button(__("Accrue Salary"), () => run(frm, "create_payroll"), __("Payroll"));
		}

		// Аванс живе окремим документом — платиться 15-го, задовго до розрахунку місяця.
		frm.add_custom_button(__("Advance"), () => open_advance(frm), __("Payroll"));

		if (frm.doc.total_outstanding && frm.doc.bonus_approved) {
			frm.add_custom_button(__("Pay Salary"), () => ask_payment_date(frm), __("Pay"));
		}

		frm.trigger("show_status");
	},

	show_status(frm) {
		const colors = { Draft: "gray", "To Pay": "orange", "Partly Paid": "yellow", Paid: "green" };
		frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");

		if (!frm.doc.bonus_approved) {
			frm.dashboard.add_comment(
				__("The bonuses for this month are not approved yet — the salary cannot be accrued or paid."),
				"orange",
				true
			);
		}

		if (frm.doc.employees_without_attendance) {
			frm.dashboard.add_comment(
				__("{0} employees have no attendance for the period — they get no salary slip.", [
					frm.doc.employees_without_attendance,
				]),
				"orange",
				true
			);
		}

		// Без нарахування платити нічого: спершу «Затвердження ЗП», далі «Нарахувати ЗП».
		if (frm.doc.employees_not_accrued) {
			frm.dashboard.add_comment(
				__("{0} employees have no salary slip yet — accrue the salary before paying.", [
					frm.doc.employees_not_accrued,
				]),
				"blue",
				true
			);
		}
	},
});

const money = (value) => erpnext.utils.employee_preview.money(value);
const number = (value) => erpnext.utils.employee_preview.number(value);

function hours(value) {
	return __("{0} h", [number(value)]);
}

function days(value) {
	return __("{0} d", [number(value)]);
}

function render_preview(frm) {
	erpnext.utils.employee_preview.render(frm, {
		field: "employees_preview",
		table: "employees",
		group_by: (row) => row.department || __("No Department"),
		warn: (row) => !row.credited_days,
		// attendance is not a column of its own: the name carries the warning, and the worked
		// time next to it opens the whole month of that employee
		name_suffix: (row) =>
			row.credited_days
				? ""
				: `<span class="employee-preview-badge warn">${__("No attendance sheet")}</span>`,
		filter: { label: __("Unpaid only"), test: (row) => !row.paid },
		columns: [
			{
				label: __("Worked"),
				value: (row) => `${days(row.credited_days)} / ${hours(row.working_hours)}`,
				click: (row) => show_details(frm, row),
			},
			{ label: __("Gross Pay"), value: (row) => money(row.gross_pay) },
			{ label: __("Advance"), value: (row) => money(flt(row.advance_card) + flt(row.advance_cash)) },
			{ label: __("To Card"), value: (row) => money(row.salary_card) },
			{ label: __("Deposit"), value: (row) => money(row.deposit) },
			{ label: __("Outstanding"), value: (row) => money(row.outstanding), bold: true },
			{
				label: __("Payment"),
				value: (row) => (row.paid ? __("Paid") : payable(frm, row) ? __("Pay") : ""),
				clickable: (row) => row.paid || payable(frm, row),
				click: (row) => (row.paid ? show_receipt(frm, row) : ask_payment_date(frm, row)),
			},
		],
	});
}

// Nothing is paid before HRMS has accrued it and the month's bonuses are approved:
// the slip is what the money closes, and the bonus is part of that slip.
function payable(frm, row) {
	return (
		Boolean(frm.doc.bonus_approved) &&
		Boolean(row.salary_slip) &&
		(flt(row.salary_card) > 0 || flt(row.salary_cash) > 0)
	);
}

// What the month is made of, and what is being paid for it — the same block serves the info
// popup, the payment confirmation and the receipt.
function details_html(row) {
	const lines = [
		[__("Present Days"), number(row.present_days)],
		[__("Half Days"), number(row.half_days)],
		[__("Sick Leave Days"), number(row.sick_days)],
		[__("Paid Leave Days"), number(row.leave_days)],
		[__("Unpaid Leave Days"), number(row.unpaid_leave_days)],
		[__("Absent Days"), number(row.absent_days)],
		[__("Overtime Hours"), hours(row.overtime_hours)],
		[__("Shortfall Hours"), hours(row.shortfall_hours)],
		[__("Credited Days"), `<b>${days(row.credited_days)} / ${hours(row.working_hours)}</b>`],
		[__("Working Days in Month"), number(row.total_working_days)],
		[__("Gross Pay"), money(row.gross_pay)],
		[__("Advance to Card"), money(row.advance_card)],
		[__("Advance in Cash"), money(row.advance_cash)],
		[__("Deposit"), money(row.deposit)],
		[__("To Card"), money(row.salary_card)],
		[__("In Cash"), money(row.salary_cash)],
		[__("Outstanding"), `<b>${money(row.outstanding)}</b>`],
	];

	return `
		<table class="table table-bordered" style="margin: 0;">
			<tbody>
				${lines.map(([label, value]) => `<tr><td>${label}</td><td class="text-right">${value}</td></tr>`).join("")}
			</tbody>
		</table>
		${row.note ? `<p class="text-muted" style="margin-top: 8px;">${frappe.utils.escape_html(row.note)}</p>` : ""}
	`;
}

function show_details(frm, row) {
	frappe.msgprint({
		title: row.employee_name || row.employee,
		indicator: row.salary_slip ? "green" : "orange",
		message: details_html(row),
	});
}

// What was paid, how much and by which documents — the row keeps its own receipt.
function show_receipt(frm, row) {
	const links = [
		[__("Salary Slip"), row.salary_slip, "Salary Slip"],
		[__("Payment Entry (Card)"), row.journal_entry_card, "Journal Entry"],
		[__("Payment Entry (Cash)"), row.journal_entry_cash, "Journal Entry"],
	].filter(([, name]) => name);

	frappe.msgprint({
		title: __("Paid {0}", [money(flt(row.salary_card) + flt(row.salary_cash))]),
		indicator: "green",
		message: `
			<p>${__("Salary for {0}, paid on {1}.", [
				frappe.format(frm.doc.period_start, { fieldtype: "Date" }),
				frappe.format(row.paid_date || frm.doc.period_end, { fieldtype: "Date" }),
			])}</p>
			${details_html(row)}
			${
				links.length
					? `<p style="margin-top: 10px;">${links
							.map(
								([label, name, doctype]) =>
									`${label}: <a href="/app/${frappe.router.slug(
										doctype
									)}/${encodeURIComponent(name)}">${frappe.utils.escape_html(name)}</a>`
							)
							.join("<br>")}</p>`
					: ""
			}
		`,
	});
}

function run(frm, method, args) {
	return frm
		.call({
			doc: frm.doc,
			method: method,
			args: args || {},
			freeze: true,
			freeze_message: __("Working..."),
		})
		.then(() => frm.reload_doc());
}

function open_advance(frm) {
	if (frm.doc.advance_sheet) {
		frappe.set_route("Form", "Salary Advance", frm.doc.advance_sheet);
		return;
	}

	frappe.new_doc("Salary Advance", {
		company: frm.doc.company,
		period_start: frm.doc.period_start,
	});
}

function ask_payment_date(frm, row) {
	const fields = [
		{
			fieldname: "posting_date",
			fieldtype: "Date",
			label: __("Payment Date"),
			default: frm.doc.period_end,
			reqd: 1,
		},
	];

	if (row) fields.unshift({ fieldtype: "HTML", fieldname: "details", options: details_html(row) });

	frappe.prompt(
		fields,
		(values) =>
			run(frm, "pay", {
				posting_date: values.posting_date,
				employees: row ? [row.employee] : null,
			}),
		row ? __("Pay {0}", [row.employee_name || row.employee]) : __("Pay Salary"),
		__("Post")
	);
}
