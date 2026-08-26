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

		// the money leaves through the row button, one employee at a time; the toolbar only
		// closes the month once nobody is left unpaid
		if (
			!["Draft", "Paid"].includes(frm.doc.status) &&
			frm.doc.bonus_approved &&
			!unpaid_rows(frm).length
		) {
			frm.add_custom_button(__("Mark as Paid"), () => confirm_mark_paid(frm), __("Pay"));
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

		// Оклад задається в картці працівника — без нього відомість не має що рахувати.
		if (frm.doc.employees_without_salary) {
			frm.dashboard.add_comment(
				__("{0} employees have no salary set on their card — fill it in to pay them.", [
					frm.doc.employees_without_salary,
				]),
				"orange",
				true
			);
		}

		// Нарахування в HRMS виплату не блокує — це підказка бухгалтерії, а не перепона.
		if (frm.doc.employees_not_accrued) {
			frm.dashboard.add_comment(
				__("{0} employees have no salary slip yet — the payout does not wait for it.", [
					frm.doc.employees_not_accrued,
				]),
				"blue",
				true
			);
		}
	},
});

const NO_SALARY_GROUP = __("Salary not set");

// The card carries the two halves of the pay; without either one there is nothing to compute.
function has_salary(row) {
	return Boolean(flt(row.official_salary) || flt(row.cash_salary));
}

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
		// employees whose card has no salary at all cannot be paid from here — they get their
		// own block instead of sitting in a department with zeroes nobody explains
		group_by: (row) => (has_salary(row) ? row.department || __("No Department") : NO_SALARY_GROUP),
		warn: (row) => !has_salary(row) || !row.credited_days,
		// attendance is not a column of its own: the name carries the warning, and the worked
		// time next to it opens the whole month of that employee
		name_suffix: (row) => {
			if (!has_salary(row)) {
				return `<span class="employee-preview-badge warn">${__("No salary set")}</span>`;
			}

			return row.credited_days
				? ""
				: `<span class="employee-preview-badge warn">${__("No attendance sheet")}</span>`;
		},
		filter: { label: __("Unpaid only"), test: (row) => !row.paid },
		columns: [
			{
				label: __("Worked"),
				value: (row) => `${days(row.credited_days)} / ${hours(row.working_hours)}`,
				click: (row) => show_details(frm, row),
			},
			{ label: __("Official Salary"), value: (row) => money(row.official_salary), secret: true },
			{ label: __("Cash Salary"), value: (row) => money(row.cash_salary), secret: true },
			{ label: __("Gross Pay"), value: (row) => money(row.gross_pay), secret: true },
			{ label: __("Advance to Card"), value: (row) => money(row.advance_card), secret: true },
			{ label: __("Advance in Cash"), value: (row) => money(row.advance_cash), secret: true },
			{ label: __("To Card"), value: (row) => money(row.salary_card), secret: true },
			{ label: __("In Cash"), value: (row) => money(row.salary_cash), secret: true },
			{ label: __("Outstanding"), value: (row) => money(row.outstanding), bold: true, secret: true },
			{
				label: __("Payment"),
				value: (row) => (row.paid ? __("Paid") : payable(frm, row) ? __("Pay") : ""),
				clickable: (row) => row.paid || payable(frm, row),
				click: (row) => (row.paid ? show_receipt(frm, row) : ask_payment_date(frm, row)),
			},
		],
	});
}

// The bonus is part of the month, so it has to be approved first; the HRMS accrual is not a
// gate — the payout is computed from the structure and the attendance sheet, like the advance.
function payable(frm, row) {
	return Boolean(frm.doc.bonus_approved) && (flt(row.salary_card) > 0 || flt(row.salary_cash) > 0);
}

function salary_lines(row) {
	return [
		[__("Official Salary"), money(row.official_salary)],
		[__("Cash Salary"), money(row.cash_salary)],
		[__("Bonus"), money(row.bonus_amount)],
		[__("Allowance"), money(row.allowance)],
		[__("Gross Pay"), money(row.gross_pay)],
		[__("Advance to Card"), money(row.advance_card)],
		[__("Advance in Cash"), money(row.advance_cash)],
		[__("Deposit"), money(row.deposit)],
		[__("To Card"), money(row.salary_card)],
		[__("In Cash"), money(row.salary_cash)],
		[__("Outstanding"), `<b>${money(row.outstanding)}</b>`],
	];
}

function attendance_extra(row) {
	return [[__("Working Days in Month"), number(row.total_working_days)]];
}

function details_html(row) {
	return erpnext.utils.attendance_details.html(row, {
		attendance: attendance_extra(row),
		salary: salary_lines(row),
		note: row.note,
	});
}

function show_details(frm, row) {
	erpnext.utils.attendance_details.show(row, {
		title: row.employee_name || row.employee,
		indicator: row.paid ? "green" : "blue",
		attendance: attendance_extra(row),
		salary: salary_lines(row),
		note: row.note,
		start: frm.doc.period_start,
		end: frm.doc.period_end,
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

function unpaid_rows(frm) {
	return (frm.doc.employees || []).filter(
		(row) => row.salary_slip && !row.paid && (flt(row.salary_card) || flt(row.salary_cash))
	);
}

function confirm_mark_paid(frm) {
	frappe.confirm(__("Every employee of this sheet is paid. Close the document as paid?"), () =>
		run(frm, "mark_paid")
	);
}

// always one employee: the row is the only way money leaves this document
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

	fields.unshift({ fieldtype: "HTML", fieldname: "details", options: details_html(row) });

	frappe.prompt(
		fields,
		(values) => run(frm, "pay", { posting_date: values.posting_date, employees: [row.employee] }),
		__("Pay {0}", [row.employee_name || row.employee]),
		__("Post")
	);
}
