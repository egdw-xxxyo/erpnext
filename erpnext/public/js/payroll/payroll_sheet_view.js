// Спільний екран двох нарахувань зарплати: офіційного (на картку) і управлінського (готівкою).
// Рахуються вони однаково, тож і виглядають однаково — різниця лише в тому, яку половину
// документ показує й платить. Половину задає `setup()` кожного з двох DocType.

frappe.provide("erpnext.payroll");

const PARTS = {};

// Половина документа: офіційна платить на картку, управлінська — з каси.
function is_official(frm) {
	return PARTS[frm.doctype] !== "cash";
}

function amount(frm, row) {
	return is_official(frm) ? flt(row.salary_card) : flt(row.salary_cash);
}

function advance(frm, row) {
	return is_official(frm) ? flt(row.advance_card) : flt(row.advance_cash);
}

erpnext.payroll.sheet_view = function (doctype, options) {
	PARTS[doctype] = options.part;

	frappe.ui.form.on(doctype, {
		onload(frm) {
			erpnext.utils.month_field.apply_period(frm, "period_start");
		},

		refresh(frm) {
			erpnext.utils.month_field.apply_period(frm, "period_start");
			render_preview(frm);

			if (frm.is_new()) {
				return;
			}

			frm.add_custom_button(__("Recalculate"), () => run(frm, "refresh_data"));

			// Без затверджених премій місяць не рахується: нарахований листок довелося б
			// скасовувати, щоб додати премію. Нараховує в HRMS лише офіційна половина —
			// управлінська офіційно не проходить.
			if (is_official(frm) && !frm.doc.payroll_entry && frm.doc.bonus_approved) {
				frm.add_custom_button(__("Accrue Salary"), () => run(frm, "create_payroll"), __("Payroll"));
			}

			// Друга половина того самого місяця платиться іншим документом і в іншу дату.
			frm.add_custom_button(__("The Other Half"), () => open_counterpart(frm), __("Payroll"));

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
					__(
						"The bonuses for this month are not approved yet — the salary cannot be accrued or paid."
					),
					"orange",
					true
				);
			}

			// Підказки рахуються по рядках, а не по полях шапки: підсумки з форми прибрані,
			// а попередити бухгалтерію все одно треба.
			const rows = frm.doc.employees || [];
			const without_attendance = rows.filter((row) => !row.credited_days).length;
			const without_salary = rows.filter((row) => !has_salary(row)).length;
			const not_accrued = rows.filter((row) => row.credited_days && !row.salary_slip).length;

			if (is_official(frm) && without_attendance) {
				frm.dashboard.add_comment(
					__("{0} employees have no attendance for the period — they get no salary slip.", [
						without_attendance,
					]),
					"orange",
					true
				);
			}

			// Оклад задається в картці працівника — без нього відомість не має що рахувати.
			if (without_salary) {
				frm.dashboard.add_comment(
					__("{0} employees have no salary set on their card — fill it in to pay them.", [
						without_salary,
					]),
					"orange",
					true
				);
			}

			// Нарахування в HRMS виплату не блокує — це підказка бухгалтерії, а не перепона.
			if (is_official(frm) && not_accrued) {
				frm.dashboard.add_comment(
					__("{0} employees have no salary slip yet — the payout does not wait for it.", [
						not_accrued,
					]),
					"blue",
					true
				);
			}
		},
	});
};

// Ставки живуть у «Налаштуваннях зарплатних податків» — тягнемо їх звідти, і лише раз.
// Аванс читає їх звідси ж, щоб розклад утримань в обох документах був один.
erpnext.payroll.withheld_rates = function () {
	if (!erpnext.payroll.withheld_rates.promise) {
		erpnext.payroll.withheld_rates.promise = Promise.all([
			frappe.db.get_single_value("Payroll Tax Settings", "pit_rate"),
			frappe.db.get_single_value("Payroll Tax Settings", "military_levy_rate"),
		]).then(([pit, levy]) => [flt(pit || 18) / 100, flt(levy || 5) / 100]);
	}

	return erpnext.payroll.withheld_rates.promise;
};

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
			{ label: __("Tax Number (RNOKPP)"), value: (row) => row.tax_id || "—" },
			{
				label: __("Worked"),
				value: (row) => `${days(row.credited_days)} / ${hours(row.working_hours)}`,
				click: (row) => show_details(frm, row),
			},
			...(is_official(frm)
				? [
						// Оклад місячний, а нараховують за табелем — обидва числа стоять поруч, щоб
						// різниця між ними не виглядала помилкою. Розклад податків відкривається
						// кліком по нарахованому або по сумі до виплати.
						{
							label: __("Official Salary"),
							value: (row) => money(row.official_salary),
							secret: true,
						},
						{
							label: __("Accrued Officially"),
							value: (row) => money(row.earned_official),
							secret: true,
							click: (row) => show_payout(frm, row),
						},
						{
							label: __("Advance Paid Out"),
							value: (row) => money(row.advance_card),
							secret: true,
							click: (row) => show_advance_paid(frm, row),
						},
						{
							label: __("To Pay"),
							value: (row) => money(row.salary_card),
							bold: true,
							secret: true,
							click: (row) => show_payout(frm, row),
						},
				  ]
				: [
						// Готівкою платиться лише друга половина окладу, але читається вона поруч
						// з офіційною: разом вони і є те, що людина отримує за місяць.
						{
							label: __("Official Salary"),
							value: (row) => money(row.official_salary),
							secret: true,
						},
						{ label: __("Cash Salary"), value: (row) => money(row.cash_salary), secret: true },
						{
							label: __("Paid Out"),
							value: (row) => money(paid_out(row)),
							secret: true,
						},
						{
							label: __("To Pay"),
							value: (row) => money(row.outstanding),
							bold: true,
							secret: true,
							click: (row) => show_cash_payout(frm, row),
						},
				  ]),
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
	return Boolean(frm.doc.bonus_approved) && amount(frm, row) > 0;
}

function attendance_extra(row) {
	// Платить місяць не табель, а календар: робочі дні мінус відпустка й лікарняний.
	return [
		[__("Working Days in Month"), number(row.total_working_days)],
		[__("Paid Days"), `<b>${days(row.paid_days)}</b>`],
	];
}

// What the month is being paid for — the days above it come from the shared attendance block,
// so this list and the calendar over it can never tell two different stories.
function salary_lines(frm, row) {
	const lines = [
		[__("Official Salary"), money(row.official_salary)],
		[__("Cash Salary"), money(row.cash_salary)],
		[__("Bonus"), money(row.bonus_amount)],
		[__("Allowance"), money(row.allowance)],
		[__("Gross Pay"), money(row.gross_pay)],
	];

	if (is_official(frm)) {
		lines.push(
			[__("Accrued Officially"), money(row.earned_official)],
			[__("Taxes Withheld"), money(row.taxes_withheld)],
			[__("Employer SSC"), money(row.employer_ssc)],
			[__("Advance to Card"), money(row.advance_card)],
			[__("Deposit"), money(row.deposit)],
			[__("To Card"), money(row.salary_card)]
		);
	} else {
		lines.push(
			[__("Accrued in Cash"), money(row.earned_cash)],
			[__("Advance in Cash"), money(row.advance_cash)],
			[__("In Cash"), money(row.salary_cash)]
		);
	}

	lines.push([__("Outstanding"), `<b>${money(row.outstanding)}</b>`]);

	return lines;
}

// The same block serves the info popup, the payment confirmation and the receipt.
function details_html(frm, row) {
	return erpnext.utils.attendance_details.html(row, {
		attendance: attendance_extra(row),
		salary: salary_lines(frm, row),
		note: row.note,
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

// Оклад місячний, а нараховують за оплачувані дні: без цього рядка розклад починався з готового
// числа, і зв'язок із окладом у колонці доводилося рахувати в голові.
function prorated(row, field) {
	return flt(row.total_working_days)
		? flt((flt(row[field]) * flt(row.paid_days)) / flt(row.total_working_days), 2)
		: 0;
}

// Від окладу до суми на руки: скільки нарахували за відпрацьовані дні, скільки з того утримали,
// що вже видали авансом і що лишається виплатити.
function show_payout(frm, row) {
	erpnext.payroll.withheld_rates().then(([pit_rate, levy_rate]) => {
		const accrued = flt(row.earned_official);
		const pit = flt(accrued * pit_rate, 2);
		const levy = flt(accrued * levy_rate, 2);
		const base = prorated(row, "official_salary");
		const lines = [
			[__("Official Salary"), money(row.official_salary)],
			[__("Paid Days"), `${days(row.paid_days)} / ${days(row.total_working_days)}`],
		];

		// Премію й надбавку нараховують понад оклад — без них розклад не сходився б із
		// «Нараховано офіційно», тож вони з'являються лише коли справді є.
		if (Math.abs(base - accrued) >= 0.01) {
			lines.push([__("Accrued for the Paid Days"), money(base)]);

			if (flt(row.bonus_amount)) {
				lines.push([__("Bonus"), money(row.bonus_amount)]);
			}

			if (flt(row.allowance)) {
				lines.push([__("Allowance"), money(row.allowance)]);
			}
		}

		lines.push(
			[__("Accrued Officially"), money(accrued)],
			[__("PIT {0}%", [number(pit_rate * 100)]), `− ${money(pit)}`],
			[__("Military Levy {0}%", [number(levy_rate * 100)]), `− ${money(levy)}`],
			[__("Accrued to Card"), money(row.earned_card)],
			[__("Advance Paid Out"), `− ${money(row.advance_card)}`]
		);

		// Задаток видають не всім — рядок з'являється лише тоді, коли він був.
		if (flt(row.deposit)) {
			lines.push([__("Deposit"), `− ${money(row.deposit)}`]);
		}

		lines.push([__("To Pay"), `<b>${money(row.salary_card)}</b>`]);

		frappe.msgprint({
			title: row.employee_name || row.employee,
			indicator: "blue",
			message: `
				${lines_html(lines)}
				<p class="text-muted" style="margin-top: 8px;">${__(
					"The salary is paid for {0} paid days of {1} working days in the month — working days minus leave and sick leave.",
					[number(row.paid_days), number(row.total_working_days)]
				)}</p>
			`,
		});
	});
}

// Аванс лишає у відомості одне число — тут видно, з чого воно склалося: за скільки днів його
// нарахували, що з нього утримали і скільки людина отримала на руки.
function show_advance_paid(frm, row) {
	Promise.all([
		erpnext.payroll.withheld_rates(),
		frm.call("advance_details", { employee: row.employee }),
	]).then(([[pit_rate, levy_rate], response]) => {
		const paid = response && response.message;

		if (!paid) {
			frappe.msgprint({
				title: row.employee_name || row.employee,
				indicator: "orange",
				message: __("No advance was paid to this employee for this month."),
			});
			return;
		}

		const accrued = flt(paid.advance_accrued);
		const lines = [
			[__("Official Salary"), money(paid.official_salary)],
			[__("Paid Days of the Advance"), `${days(paid.advance_days)} / ${days(paid.month_working_days)}`],
			[__("Advance Accrued"), money(accrued)],
			[__("PIT {0}%", [number(pit_rate * 100)]), `− ${money(flt(accrued * pit_rate, 2))}`],
			[__("Military Levy {0}%", [number(levy_rate * 100)]), `− ${money(flt(accrued * levy_rate, 2))}`],
			[__("Advance to Card"), money(paid.advance_card)],
		];

		if (flt(paid.advance_cash)) {
			lines.push([__("Advance in Cash"), money(paid.advance_cash)]);
		}

		lines.push([__("Advance Paid Out"), `<b>${money(paid.advance_total)}</b>`]);

		frappe.msgprint({
			title: row.employee_name || row.employee,
			indicator: paid.paid ? "green" : "orange",
			message: `
				${lines_html(lines)}
				<p style="margin-top: 8px;">${__("Advance for {0}, paid on {1}.", [
					frappe.format(frm.doc.period_start, { fieldtype: "Date" }),
					frappe.format(paid.paid_on, { fieldtype: "Date" }),
				])} <a href="/app/salary-advance/${encodeURIComponent(
				paid.advance
			)}">${frappe.utils.escape_html(paid.advance)}</a></p>
			`,
		});
	});
}

// Скільки з готівкової половини людина вже отримала: аванс завжди, зарплата — коли рядок
// проведений. Разом це «Виплачено», а решта лишається в «До виплати».
function paid_out(row) {
	return flt(row.advance_cash) + (row.paid ? flt(row.salary_cash) : 0);
}

// Готівкова половина податків не знає: нарахування, виданий аванс, уже виплачена зарплата —
// і те, що лишається на руки.
function show_cash_payout(frm, row) {
	const lines = [
		[__("Cash Salary"), money(row.cash_salary)],
		[__("Paid Days"), `${days(row.paid_days)} / ${days(row.total_working_days)}`],
		[__("Accrued in Cash"), money(row.earned_cash)],
		[__("Advance in Cash"), `− ${money(row.advance_cash)}`],
	];

	if (row.paid) {
		lines.push([__("Salary in Cash"), `− ${money(row.salary_cash)}`]);
	}

	lines.push([__("Paid Out"), money(paid_out(row))], [__("To Pay"), `<b>${money(row.outstanding)}</b>`]);

	frappe.msgprint({
		title: row.employee_name || row.employee,
		indicator: row.paid ? "green" : "blue",
		message: `
			${lines_html(lines)}
			<p class="text-muted" style="margin-top: 8px;">${__(
				"The salary is paid for {0} paid days of {1} working days in the month — working days minus leave and sick leave.",
				[number(row.paid_days), number(row.total_working_days)]
			)}</p>
		`,
	});
}

function show_details(frm, row) {
	erpnext.utils.attendance_details.show(row, {
		title: row.employee_name || row.employee,
		indicator: row.paid ? "green" : "blue",
		attendance: attendance_extra(row),
		salary: salary_lines(frm, row),
		note: row.note,
	});
}

// What was paid, how much and by which documents — the row keeps its own receipt.
function show_receipt(frm, row) {
	const links = (
		is_official(frm)
			? [
					[__("Salary Slip"), row.salary_slip, "Salary Slip"],
					[__("Payment Entry (Card)"), row.journal_entry_card, "Journal Entry"],
			  ]
			: [[__("Payment Entry (Cash)"), row.journal_entry_cash, "Journal Entry"]]
	).filter(([, name]) => name);

	frappe.msgprint({
		title: __("Paid {0}", [money(amount(frm, row))]),
		indicator: "green",
		message: `
			<p>${__("Salary for {0}, paid on {1}.", [
				frappe.format(frm.doc.period_start, { fieldtype: "Date" }),
				frappe.format(row.paid_date || frm.doc.period_end, { fieldtype: "Date" }),
			])}</p>
			${details_html(frm, row)}
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
	return (frm.doc.employees || []).filter((row) => !row.paid && amount(frm, row));
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

	fields.unshift({ fieldtype: "HTML", fieldname: "details", options: details_html(frm, row) });

	frappe.prompt(
		fields,
		(values) => run(frm, "pay", { posting_date: values.posting_date, employees: [row.employee] }),
		__("Pay {0}", [row.employee_name || row.employee]),
		__("Post")
	);
}

// Дві половини місяця живуть окремими документами — з кожного видно другий.
function open_counterpart(frm) {
	const doctype = is_official(frm) ? "Management Payroll Sheet" : "Payroll Sheet";

	frappe.db
		.get_value(doctype, { company: frm.doc.company, period_start: frm.doc.period_start }, "name")
		.then((response) => {
			const name = response.message && response.message.name;

			if (name) {
				frappe.set_route("Form", doctype, name);
				return;
			}

			frappe.new_doc(doctype, { company: frm.doc.company, period_start: frm.doc.period_start });
		});
}
