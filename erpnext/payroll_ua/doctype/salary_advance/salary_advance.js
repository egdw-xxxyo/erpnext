frappe.ui.form.on("Salary Advance", {
	onload(frm) {
		erpnext.utils.month_field.apply_period(frm, "period_start");
	},

	refresh(frm) {
		// buttons first: a throw in any of the helpers below must not cost the toolbar
		if (!frm.is_new() && frm.doc.status !== "Paid") {
			const rows = frm.doc.employees || [];

			if (rows.every((row) => !row.additional_salary_card && !row.additional_salary_cash)) {
				frm.add_custom_button(__("Recalculate"), () => run(frm, "calculate"));
			}

			// the money is paid row by row — the toolbar only files the deduction and closes
			// the month once every employee has been paid
			if (rows.some((row) => !row.paid && flt(row.advance_total))) {
				frm.add_custom_button(__("Create Advance"), () => confirm_create(frm));
			} else if (rows.length && frm.doc.status !== "Draft") {
				frm.add_custom_button(__("Mark as Paid"), () => confirm_mark_paid(frm)).addClass(
					"btn-primary"
				);
			}
		}

		erpnext.utils.month_field.apply_period(frm, "period_start");
		erpnext.utils.grid_editor.compact_row_actions(frm);
		calculate_totals(frm);
		render_preview(frm);

		if (frm.is_new()) {
			fetch_employees(frm);
			return;
		}

		frm.page.set_indicator(
			__(frm.doc.status),
			{ Draft: "orange", "To Pay": "blue", "Partly Paid": "yellow", Paid: "green" }[frm.doc.status] ||
				"gray"
		);

		show_missing_count(frm);
	},

	company: (frm) => fetch_employees(frm, true),
	period_start: (frm) => fetch_employees(frm, true),
	cutoff_day: (frm) => fetch_employees(frm, true),

	employees_add: (frm) => refresh_view(frm),
	employees_remove: (frm) => refresh_view(frm),
	validate: (frm) => calculate_totals(frm),
});

frappe.ui.form.on("Salary Advance Item", {
	advance_card: (frm, cdt, cdn) => update_row(frm, cdt, cdn),
	advance_cash: (frm, cdt, cdn) => update_row(frm, cdt, cdn),
});

function update_row(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	row.advance_total = flt(row.advance_card) + flt(row.advance_cash);
	frm.refresh_field("employees");
	refresh_view(frm);
}

function refresh_view(frm) {
	calculate_totals(frm);
	render_preview(frm);
}

function calculate_totals(frm) {
	const rows = frm.doc.employees || [];
	const totals = {
		total_employees: rows.length,
		employees_without_attendance: rows.filter((row) => !row.attendance_approved).length,
	};

	rows.forEach((row) => {
		row.advance_total = flt(row.advance_card) + flt(row.advance_cash);
	});

	// a read-only field with no value at all is hidden by the desk, so an untouched
	// document must still be given its zeroes
	Object.entries(totals).forEach(([fieldname, value]) => {
		if (frm.doc[fieldname] === undefined || flt(frm.doc[fieldname]) !== flt(value)) {
			frm.set_value(fieldname, value);
		}
	});

	frm.refresh_field("employees");
}

const money = (value) => erpnext.utils.employee_preview.money(value);
const number = (value) => erpnext.utils.employee_preview.number(value);

function days(value) {
	return __("{0} d", [number(value)]);
}

function render_preview(frm) {
	erpnext.utils.employee_preview.render(frm, {
		field: "employees_preview",
		table: "employees",
		group_by: (row) => row.department || __("No Department"),
		open: (row) => show_attendance(frm, row),
		warn: (row) => !row.attendance_approved,
		filter: { label: __("Unpaid only"), test: (row) => !row.paid },
		// attendance is not a column of its own: the name carries the warning, and both the
		// name and the days next to it open the whole month of that employee
		name_suffix: (row) =>
			row.attendance_approved
				? ""
				: `<span class="employee-preview-badge warn">${__("No attendance sheet")}</span>`,
		columns: [
			{ label: __("Tax Number (RNOKPP)"), value: (row) => row.tax_id || "—" },
			{
				// Дні, за які платимо, а не ті, що в табелі: аванс рахується за календарем,
				// тож табельні дні в колонці лише збивали б з пантелику. Вони в попапі.
				label: __("Accrued"),
				value: (row) => days(row.advance_days),
				click: (row) => show_attendance(frm, row),
			},
			{ label: __("Official Salary"), value: (row) => money(row.official_salary), secret: true },
			{
				label: __("Advance Accrued"),
				value: (row) => money(row.advance_accrued),
				secret: true,
				click: (row) => show_accrual(row),
			},
			{
				label: __("Advance to Pay"),
				value: (row) => money(row.advance_total),
				bold: true,
				secret: true,
				click: (row) => show_advance(row),
			},
			{
				label: __("Payment"),
				value: (row) => row_action_label(row),
				clickable: (row) => Boolean(row_action(row)),
				click: (row) => (row.paid ? show_receipt(frm, row) : ask_payment_date(frm, row)),
			},
		],
	});
}

// A row walks the same two steps as the whole document: file the deduction, then pay it.
// One click per employee: filing the deduction and posting the money is a single decision,
// so the row asks once and the server does both steps.
function row_action(row) {
	if (!flt(row.advance_total)) return null;

	return row.paid ? "receipt" : "pay";
}

function row_action_label(row) {
	return row.paid ? __("Paid") : __("Pay");
}

// Аванс нараховується лише з офіційної частини (`advance_accrued` = оклад ÷ робочі дні × дні),
// тож і розклад показує офіційний оклад та офіційну ставку — `daily_rate` містить ще й готівкову
// частину, і з нею підсумок у popup не сходився.
function official_rate(row) {
	const days_in_month = flt(row.month_working_days);

	return days_in_month ? flt(row.official_salary) / days_in_month : 0;
}

function salary_lines(row) {
	// Скільки днів заплановано і скільки з них зняли — інакше «5 із 8» доводиться
	// відновлювати по календарю вручну.
	const unpaid = flt(flt(row.planned_days) - flt(row.advance_days), 2);
	const lines = [
		[__("Planned Days"), number(row.planned_days)],
		[__("Paid Days of the Advance"), `<b>${days(row.advance_days)}</b>`],
		[__("Official Salary"), money(row.official_salary)],
		[__("Working Days in Month"), number(row.month_working_days)],
		[__("Daily Rate"), money(official_rate(row))],
		[__("Advance Accrued"), money(row.advance_accrued)],
		[__("Advance to Card"), money(row.advance_card)],
		[__("Advance to Pay"), `<b>${money(row.advance_total)}</b>`],
	];

	if (unpaid > 0) {
		lines.splice(1, 0, [__("Unpaid Days"), `− ${number(unpaid)}`]);
	}

	// Готівкою аванс не платиться — рядок з'являється лише тоді, коли суму вписали руками.
	if (flt(row.advance_cash)) {
		lines.splice(lines.length - 1, 0, [__("Advance in Cash"), money(row.advance_cash)]);
	}

	return lines;
}

// Діалог виплати говорить про гроші тим самим розкладом, що й місяць у відомості: скільки
// нараховано за дні окремою секцією, а податки й сума на руки — окремою.
function payment_salary_lines(row) {
	const worked = `${days(row.advance_days)} / ${days(row.month_working_days)}`;

	return [
		[__("Off. Salary"), money(row.official_salary)],
		[__("Advance Accrued"), `${money(row.advance_accrued)} (${worked})`],
	];
}

function payment_payout_lines(row, pit_rate, levy_rate) {
	const accrued = flt(row.advance_accrued);
	const pit = flt(accrued * pit_rate, 2);
	const lines = [
		[__("PIT {0}%", [number(pit_rate * 100)]), money(pit)],
		[__("Military Levy {0}%", [number(levy_rate * 100)]), money(flt(accrued * levy_rate, 2))],
	];

	// Готівкою аванс не платиться — половини показуються лише тоді, коли готівкову вписали
	// руками. Без неї «на картку» і «до виплати» — те саме число двічі.
	if (flt(row.advance_cash)) {
		lines.push(
			[__("Advance to Card"), money(row.advance_card)],
			[__("Advance in Cash"), money(row.advance_cash)]
		);
	}

	lines.push([__("Advance to Pay"), `<b>${money(row.advance_total)}</b>`]);

	return lines;
}

function attendance_note(row) {
	return row.attendance_approved
		? ""
		: __("The attendance sheet of this employee is not approved for the first half of the month");
}

function cutoff_date(frm) {
	if (!frm.doc.period_start) return null;

	const start = frappe.datetime.str_to_obj(frm.doc.period_start);
	const last = new Date(start.getFullYear(), start.getMonth() + 1, 0).getDate();
	const day = Math.min(cint(frm.doc.cutoff_day) || 15, last);

	return frappe.datetime.obj_to_str(new Date(start.getFullYear(), start.getMonth(), day));
}

// What the days are made of, and what is being paid for them — the same block serves the
// info popup and both confirmations, so a click never asks for money without showing the basis.
function details_html(row) {
	return erpnext.utils.attendance_details.html(row, {
		salary: salary_lines(row),
		note: attendance_note(row),
	});
}

function lines_html(lines) {
	return `
		<table class="table table-bordered" style="margin: 0;">
			<tbody>
				${lines.map(([label, value]) => `<tr><td>${label}</td><td class="text-right">${value}</td></tr>`).join("")}
			</tbody>
		</table>
	`;
}

// Звідки взялася нарахована сума: оклад ділиться на робочі дні місяця, а не на оплачувані,
// тож денна ставка в усіх однакова, і різницю робить лише кількість оплачуваних днів.
function show_accrual(row) {
	const salary = flt(row.official_salary);
	const rate = official_rate(row);
	const unpaid = flt(flt(row.planned_days) - flt(row.advance_days), 2);
	const lines = [
		[__("Official Salary"), money(salary)],
		[__("Working Days in Month"), number(row.month_working_days)],
		[__("Daily Rate"), money(rate)],
		[__("Planned Days"), number(row.planned_days)],
		[__("Paid Days of the Advance"), `<b>${days(row.advance_days)}</b>`],
		[__("Advance Accrued"), `<b>${money(row.advance_accrued)}</b>`],
	];

	if (unpaid > 0) {
		lines.splice(4, 0, [__("Unpaid Days"), `− ${number(unpaid)}`]);
	}

	frappe.msgprint({
		title: row.employee_name || row.employee,
		indicator: "blue",
		message: `
			${lines_html(lines)}
			<p class="text-muted" style="margin-top: 8px;">${__(
				"Daily rate = {0} ÷ {1} working days = {2}. Accrued = {2} × {3} paid days = {4}.",
				[
					money(salary),
					number(row.month_working_days),
					money(rate),
					number(row.advance_days),
					money(row.advance_accrued),
				]
			)}</p>
		`,
	});
}

// Скільки нарахували, скільки з того утримали і що лишається на руки — той самий розклад,
// що й у листку, тільки за оплачувані дні авансу.
function show_advance(row) {
	// Ставки спільні з відомістю — див. `public/js/payroll/payroll_sheet_view.js`.
	erpnext.payroll.withheld_rates().then(([pit_rate, levy_rate]) => {
		const accrued = flt(row.advance_accrued);
		const pit = flt(accrued * pit_rate, 2);
		const levy = flt(accrued * levy_rate, 2);
		const lines = [
			[__("Advance Accrued"), money(accrued)],
			[__("PIT {0}%", [number(pit_rate * 100)]), `− ${money(pit)}`],
			[__("Military Levy {0}%", [number(levy_rate * 100)]), `− ${money(levy)}`],
			[__("Advance to Card"), money(row.advance_card)],
		];

		if (flt(row.advance_cash)) {
			lines.push([__("Advance in Cash"), money(row.advance_cash)]);
		}

		lines.push([__("Advance to Pay"), `<b>${money(row.advance_total)}</b>`]);

		frappe.msgprint({
			title: row.employee_name || row.employee,
			indicator: "blue",
			message: `
				${lines_html(lines)}
				<p class="text-muted" style="margin-top: 8px;">${__(
					"The advance is paid for {0} paid days of {1} working days in the month.",
					[number(row.advance_days), number(row.month_working_days)]
				)}</p>
			`,
		});
	});
}

function show_attendance(frm, row) {
	erpnext.utils.attendance_details.show(row, {
		title: row.employee_name || row.employee,
		indicator: row.attendance_approved ? "green" : "orange",
		salary: salary_lines(row),
		note: attendance_note(row),
		start: frm.doc.period_start,
		end: cutoff_date(frm),
	});
}

// What was paid, how much and by which documents — the row keeps its own receipt.
function show_receipt(frm, row) {
	const links = [
		[__("Additional Salary (Card)"), row.additional_salary_card, "Additional Salary"],
		[__("Additional Salary (Cash)"), row.additional_salary_cash, "Additional Salary"],
		[__("Payment Entry (Card)"), row.journal_entry_card, "Journal Entry"],
		[__("Payment Entry (Cash)"), row.journal_entry_cash, "Journal Entry"],
	].filter(([, name]) => name);

	frappe.msgprint({
		title: __("Paid {0}", [money(row.advance_total)]),
		indicator: "green",
		message: `
			<p>${__("Advance for {0}, paid on {1}.", [
				frappe.format(frm.doc.period_start, { fieldtype: "Date" }),
				frappe.format(row.paid_on || frm.doc.payment_date, { fieldtype: "Date" }),
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

function show_missing_count(frm) {
	frm.dashboard.clear_comment();

	if (!frm.doc.employees_without_attendance) return;

	frm.dashboard.add_comment(
		__("{0} employees have no approved attendance for the first half — the advance cannot be created.", [
			frm.doc.employees_without_attendance,
		]),
		"orange",
		true
	);
}

// A new document fills itself: the accountant opens it and already sees the amounts.
function fetch_employees(frm, replace = false) {
	if (!frm.is_new() || !frm.doc.company || !frm.doc.period_start) {
		return;
	}

	if ((frm.doc.employees || []).length && !replace) {
		return;
	}

	if (frm.fetching_employees) {
		return;
	}

	frm.fetching_employees = true;

	frappe
		.call({
			method: "erpnext.payroll_ua.doctype.salary_advance.salary_advance.get_employees",
			args: {
				company: frm.doc.company,
				period_start: frm.doc.period_start,
				cutoff_day: frm.doc.cutoff_day || 15,
			},
		})
		.then((response) => {
			const data = response.message || {};

			frm.set_value("period_working_days", data.period_working_days || 0);

			frm.clear_table("employees");
			(data.employees || []).forEach((row) => frm.add_child("employees", row));
			frm.refresh_field("employees");
			refresh_view(frm);
		})
		.always(() => {
			frm.fetching_employees = false;
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

// The whole list at once; a single employee goes through the row button, which also pays.
function confirm_create(frm) {
	frappe.confirm(
		__("The advance of {0} employees will be filed as a deduction on their payslips. Continue?", [
			frm.doc.total_employees,
		]),
		() => run(frm, "create_advance", { employees: null })
	);
}

function confirm_mark_paid(frm) {
	frappe.confirm(__("Every employee of this advance is paid. Close the document as paid?"), () =>
		run(frm, "mark_paid")
	);
}

// always one employee: the row is the only way money leaves this document
function ask_payment_date(frm, row) {
	erpnext.payroll.withheld_rates().then(([pit_rate, levy_rate]) => {
		const details = erpnext.utils.attendance_details.html(row, {
			skip_attendance: true,
			salary: payment_salary_lines(row),
			payout: payment_payout_lines(row, pit_rate, levy_rate),
			note: attendance_note(row),
		});

		frappe.prompt(
			[
				{ fieldtype: "HTML", fieldname: "details", options: details },
				{
					fieldname: "posting_date",
					fieldtype: "Date",
					label: __("Payment Date"),
					default: frm.doc.payment_date,
					reqd: 1,
				},
			],
			(values) => run(frm, "settle", { ...values, employees: [row.employee] }),
			__("Pay {0}", [row.employee_name || row.employee]),
			__("Post")
		);
	});
}
