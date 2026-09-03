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

			// Нараховує в HRMS лише офіційна половина — управлінська офіційно не проходить.
			if (is_official(frm) && !frm.doc.payroll_entry) {
				frm.add_custom_button(__("Accrue Salary"), () => run(frm, "create_payroll"), __("Payroll"));
			}

			// Друга половина того самого місяця платиться іншим документом і в іншу дату.
			frm.add_custom_button(__("The Other Half"), () => open_counterpart(frm), __("Payroll"));

			// Аванс живе окремим документом — платиться 15-го, задовго до розрахунку місяця.
			frm.add_custom_button(__("Advance"), () => open_advance(frm), __("Payroll"));

			// the money leaves through the row button, one employee at a time; the toolbar only
			// closes the month once nobody is left unpaid
			if (!["Draft", "Paid"].includes(frm.doc.status) && !unpaid_rows(frm).length) {
				frm.add_custom_button(__("Mark as Paid"), () => confirm_mark_paid(frm), __("Pay"));
			}

			// Ставки податків підтягуються заздалегідь — розклад виплати малюється синхронно.
			erpnext.payroll.withheld_rates();
			frm.trigger("show_status");
		},

		show_status(frm) {
			const colors = { Draft: "gray", "To Pay": "orange", "Partly Paid": "yellow", Paid: "green" };
			frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");

			// Підказки рахуються по рядках, а не по полях шапки: підсумки з форми прибрані,
			// а попередити бухгалтерію все одно треба.
			const rows = frm.doc.employees || [];
			const without_attendance = rows.filter((row) => !row.attendance_approved).length;
			const without_bonus = rows.filter((row) => !row.bonus_approved).length;
			const without_salary = rows.filter((row) => !has_salary(row)).length;
			const not_accrued = rows.filter((row) => row.credited_days && !row.salary_slip).length;

			// Без зданого табеля місяць не рахується чесно — таких людей платити не можна.
			if (without_attendance) {
				frm.dashboard.add_comment(
					__(
						"{0} employees have no approved attendance sheet for the month — they cannot be paid.",
						[without_attendance]
					),
					"red",
					true
				);
			}

			// Премії платить готівкова половина, тож і чекає на затвердження лише вона.
			if (without_bonus) {
				frm.dashboard.add_comment(
					__("{0} employees have no approved bonuses for the month — they cannot be paid.", [
						without_bonus,
					]),
					"red",
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
		]).then(([pit, levy]) => {
			// Ставки лишаються під рукою й синхронно: розклад виплати будується разом із
			// діалогом, чекати на сервер там нема коли.
			erpnext.payroll.withheld_rates.value = [flt(pit || 18) / 100, flt(levy || 5) / 100];

			return erpnext.payroll.withheld_rates.value;
		});
	}

	return erpnext.payroll.withheld_rates.promise;
};

// Останні відомі ставки — до першої відповіді сервера діють законні 18% і 5%.
erpnext.payroll.rates = function () {
	return erpnext.payroll.withheld_rates.value || [0.18, 0.05];
};

const NO_SALARY_GROUP = __("Salary not set");

// The card carries the two halves of the pay; without either one there is nothing to compute.
function has_salary(row) {
	return Boolean(flt(row.official_salary) || flt(row.cash_salary));
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
		// employees whose card has no salary at all cannot be paid from here — they get their
		// own block instead of sitting in a department with zeroes nobody explains
		group_by: (row) => (has_salary(row) ? row.department || __("No Department") : NO_SALARY_GROUP),
		open: (row) => show_details(frm, row),
		warn: (row) => !has_salary(row) || payment_blockers(row).length > 0,
		// attendance is not a column of its own: the name carries the warning, and both the
		// name and the days next to it open the whole month of that employee
		name_suffix: (row) => {
			if (!has_salary(row)) {
				return `<span class="employee-preview-badge warn">${__("No salary set")}</span>`;
			}

			return payment_blockers(row)
				.map((text) => `<span class="employee-preview-badge warn">${text}</span>`)
				.join("");
		},
		filter: { label: __("Unpaid only"), test: (row) => !row.paid },
		columns: [
			{ label: __("Tax Number (RNOKPP)"), value: (row) => row.tax_id || "—" },
			{
				// Ті самі дні, що й в авансі: місяць платиться за календарем, а табельні
				// дні лишилися довідкою в попапі.
				label: __("Accrued"),
				value: (row) => days(row.paid_days),
				click: (row) => show_details(frm, row),
			},
			...(is_official(frm)
				? [
						// Оклад місячний, а нараховують за табелем — обидва числа стоять поруч, щоб
						// різниця між ними не виглядала помилкою. Розклад податків відкривається
						// кліком по нарахованому або по сумі до виплати.
						{
							label: __("Off. Salary"),
							value: (row) => money(row.official_salary),
							secret: true,
						},
						{
							label: __("Off. Accrued"),
							value: (row) => money(row.earned_official),
							secret: true,
							click: (row) => show_payout(frm, row),
						},
						{
							// Скільки працівникові вже виплатили за місяць — до податків, щоб
							// колонка сходилася з нарахуванням: спершу аванс, після виплати
							// зарплати — весь місяць.
							label: __("Off. Paid"),
							clickable: (row) => paid_official(row) > 0,
							value: (row) => money(paid_official(row)),
							secret: true,
							click: (row) => show_paid_official(frm, row),
						},
						{
							// Скільки ще винні — нарахуванням, як і «Виплачено ОФ»: разом вони
							// дають «Нараховано ОФ». Виплаченому рядку лишається нуль.
							label: __("To Pay Off."),
							// Нуль розкладати нічого: рядок уже виплачено, розклад тієї виплати
							// відкривається з «Нараховано ОФ».
							clickable: (row) => outstanding_official(row) > 0,
							value: (row) => money(outstanding_official(row)),
							bold: true,
							secret: true,
							click: (row) => show_payout(frm, row),
						},
				  ]
				: [
						// Управлінська відомість говорить лише про свою половину: офіційні числа
						// живуть у своїй відомості, а тут вони лише розсували таблицю.
						// «Упр. ЗП» — та сама готівкова половина окладу, тільки назва колонки
						// коротша: у вузькій таблиці «ЗП готівкою» переносилося на два рядки.
						{ label: __("Mgmt. Salary"), value: (row) => money(row.cash_salary), secret: true },
						{
							label: __("Paid Out"),
							value: (row) => money(paid_out(row)),
							secret: true,
						},
						{
							label: __("To Pay"),
							clickable: (row) => flt(row.outstanding) > 0,
							value: (row) => money(row.outstanding),
							bold: true,
							secret: true,
							click: (row) => show_cash_payout(frm, row),
						},
				  ]),
			{
				label: __("Payment"),
				value: (row) => payment_label(frm, row),
				clickable: (row) => row.paid || payable(frm, row),
				click: (row) => (row.paid ? show_receipt(frm, row) : ask_payment_date(frm, row)),
			},
		],
	});
}

// Що тримає виплату цього рядка: табель здається керівником, премії затверджуються
// окремим документом, і кожне з двох тримає лише свого працівника — сусідній рядок
// платиться далі. Нарахування в HRMS умовою не є: виплата рахується зі структури й табеля.
function payment_blockers(row) {
	const blockers = [];

	if (!row.attendance_approved) blockers.push(__("Attendance sheet not approved"));
	if (!row.bonus_approved) blockers.push(__("Bonuses not approved"));

	return blockers;
}

// Порожня комірка не пояснює, чому кнопки немає: причину називаємо прямо.
function payment_label(frm, row) {
	if (row.paid) return __("Paid");
	if (payable(frm, row)) return __("Pay");

	const blockers = payment_blockers(row);

	return blockers.length && amount(frm, row) ? blockers[0] : "";
}

function payable(frm, row) {
	return !payment_blockers(row).length && amount(frm, row) > 0;
}

function attendance_extra(row) {
	// Платить місяць не табель, а календар: робочі дні мінус неоплачувані відсутності.
	const lines = [
		[__("Working Days in Month"), number(row.total_working_days)],
		[__("Paid Days"), `<b>${days(row.paid_days)}</b>`],
	];

	// За скільки днів уже заплатили авансом — решта місяця лишається на цей документ.
	if (flt(row.advance_days)) {
		lines.push([__("Paid Days of the Advance"), days(row.advance_days)]);
	}

	return lines;
}

// Що місяць винен людині — самим нарахуванням: оклад, уже виплачене і залишок. Податки сюди
// не мішаються: скільки з залишку дійде до картки, показує окремий блок нижче.
function salary_lines(frm, row) {
	// Оклад місячний, а нараховують за оплачуваними днями — без рядка «нараховано» сума
	// до виплати виглядає більшою за оклад там, де є премія, і меншою там, де є пропуски.
	const worked = `${days(row.paid_days)} / ${days(row.total_working_days)}`;

	if (!is_official(frm)) {
		const lines = [
			[__("Cash Salary"), money(row.cash_salary)],
			[__("Accrued in Cash"), `${money(accrued_cash(row))} (${cash_worked(row)})`],
		];

		// Прогул готівкова половина не платить, а ще й забирає назад те, що за ці дні
		// пішло на картку офіційно.
		if (flt(row.absent_days)) {
			lines.push([__("Absent Days"), `− ${days(row.absent_days)}`]);
		}

		if (flt(row.absent_deduction)) {
			lines.push([__("Withheld for Absence"), `− ${money(row.absent_deduction)}`]);
		}

		// Премію могли призначити готівкою — тоді вона більша за оклад половини, і без
		// окремого рядка це читається як помилка.
		if (flt(row.bonus_cash)) {
			lines.push([__("Bonus in Cash"), money(row.bonus_cash)]);
		}

		lines.push(
			[__("Paid Out"), money(paid_out(row))],
			[__("To Pay"), `<b>${money(row.outstanding)}</b>`]
		);

		return lines;
	}

	const lines = [
		[__("Off. Salary"), money(row.official_salary)],
		[__("Off. Accrued"), `${money(accrued_official(row))} (${worked})`],
	];

	lines.push(
		[__("Off. Paid"), money(paid_official(row))],
		[__("To Pay Off."), `<b>${money(outstanding_official(row))}</b>`]
	);

	return lines;
}

// Нараховане за дні, без премії: саме воно й рахується з окладу денною ставкою.
// Утримане саме за переплату: борг минулого місяця й утримання за прогул стоять
// власними рядками, тож із загального утримання вони віднімаються.
function overpay_withheld(row) {
	return flt(flt(row.cash_deduction) - flt(row.debt_carried) - flt(row.absent_deduction), 2);
}

// Готівкою платяться лише відпрацьовані дні: прогул із них вилітає.
function cash_paid_days(row) {
	return flt(flt(row.paid_days) - flt(row.absent_days), 2);
}

function cash_worked(row) {
	return `${days(cash_paid_days(row))} / ${days(row.total_working_days)}`;
}

function accrued_cash(row) {
	return flt(flt(row.earned_cash) - flt(row.bonus_cash), 2);
}

// Премія й надбавка платяться лише готівкою, тож офіційне нараховане — це рівно оклад
// за оплачувані дні.
function accrued_official(row) {
	return flt(row.earned_official);
}

// Офіційна денна ставка: оклад ділиться на робочі дні місяця, як в авансі. `daily_rate`
// рядка містить ще й готівкову частину, тож для офіційного розкладу не годиться.
function official_rate(row) {
	const days_in_month = flt(row.total_working_days);

	return days_in_month ? flt(row.official_salary) / days_in_month : 0;
}

// Скільки з нарахованого залишку утримають і скільки ляже на картку. Числа взяті зі
// збережених: утримане — це різниця між залишком і тим, що виплачується.
function payout_lines(frm, row) {
	if (!is_official(frm)) {
		return [[__("In Cash"), `<b>${money(row.salary_cash)}</b>`]];
	}

	const [pit_rate, levy_rate] = erpnext.payroll.rates();
	const remainder = remainder_official(row);
	const withheld = flt(remainder - flt(row.salary_card) - flt(row.deposit), 2);
	// Утримане ділиться між податками за їхніми ставками, а не рахується від залишку наново:
	// так сума рядків завжди дорівнює тому, що справді утримали.
	const pit = flt((withheld * pit_rate) / (pit_rate + levy_rate), 2);
	const lines = [
		[__("PIT {0}%", [number(pit_rate * 100)]), money(pit)],
		[__("Military Levy {0}%", [number(levy_rate * 100)]), money(flt(withheld - pit, 2))],
	];

	// Задаток видають не всім — рядок з'являється лише тоді, коли він був.
	if (flt(row.deposit)) {
		lines.push([__("Deposit"), money(row.deposit)]);
	}

	lines.push(
		[__("To Card"), `<b>${money(row.salary_card)}</b>`],
		[__("Employer SSC {0}%", [number(ssc_rate(row) * 100)]), money(ssc(row))]
	);

	return lines;
}

// Ставка ЄСВ береться з самого рядка, а не з налаштувань: у працівника з інвалідністю
// вона інша (8.41% замість 22%), і в розкладі має стояти саме його.
function ssc_rate(row) {
	const accrued = flt(row.earned_official);

	return accrued ? flt(flt(row.employer_ssc) / accrued, 4) : 0;
}

// ЄСВ платить роботодавець зверху, тож із суми на картку він нічого не забирає. Береться
// часткою від місячного ЄСВ, а не ставкою: у працівника з інвалідністю вона інша (8.41%).
function ssc(row) {
	const share = flt(row.earned_official) ? remainder_official(row) / flt(row.earned_official) : 0;

	return flt(flt(row.employer_ssc) * share, 2);
}

// Підтвердження виплати й розписка — це вже про гроші: табель туди не йде, він живе в
// попапі працівника, який відкривається з таблиці.
function details_html(frm, row) {
	return erpnext.utils.attendance_details.html(row, {
		skip_attendance: true,
		salary: salary_lines(frm, row),
		payout: payout_lines(frm, row),
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

// Popup колонки «ЗП» пояснює лише нарахування: з чого рахували ставку і за скільки днів
// платять. Податки й сума на картку живуть у діалозі виплати — тут вони лише дублювали його.
function show_payout(frm, row) {
	const lines = [
		[__("Off. Salary"), money(row.official_salary)],
		[__("Working Days in Month"), number(row.total_working_days)],
		[__("Daily Rate"), money(official_rate(row))],
		[__("Paid Days"), `<b>${days(row.paid_days)}</b>`],
		[__("Off. Accrued"), money(flt(row.earned_official))],
	];

	const paid_note =
		row.paid && row.paid_date
			? `<p style="margin-top: 8px;">${__("Salary paid on {0}.", [
					frappe.format(row.paid_date, { fieldtype: "Date" }),
			  ])}</p>`
			: "";

	frappe.msgprint({
		title: row.employee_name || row.employee,
		indicator: row.paid ? "green" : "blue",
		message: `
			${lines_html(lines)}
			${paid_note}
			<p class="text-muted" style="margin-top: 8px;">${__(
				"The salary is paid for {0} paid days of {1} working days in the month — working days less sick leave over 5 days.",
				[number(row.paid_days), number(row.total_working_days)]
			)}</p>
		`,
	});
}

// Що людині вже виплатили за місяць і чим: аванс і зарплата — окремі виплати в різні дати,
// тож кожна показується своїм блоком, а разом вони дають «Виплачено».
function show_paid_official(frm, row) {
	frm.call("advance_details", { employee: row.employee }).then((response) => {
		const advance = response && response.message;
		const salary = row.paid ? flt(row.earned_official) - flt(row.advance_official) : 0;
		const groups = [];

		if (flt(row.advance_official)) {
			groups.push([
				__("Advance"),
				[
					[__("Accrued"), money(row.advance_official)],
					[__("To Card"), money(row.advance_card)],
				],
			]);
		}

		if (row.paid) {
			groups.push([
				__("Salary"),
				[
					[__("Accrued"), money(salary)],
					[__("To Card"), money(row.salary_card)],
				],
			]);
		}

		groups.push([
			__("Total"),
			[
				[__("Off. Paid"), `<b>${money(paid_official(row))}</b>`],
				[__("Total to Card"), money(flt(row.advance_card) + (row.paid ? flt(row.salary_card) : 0))],
			],
		]);

		frappe.msgprint({
			title: row.employee_name || row.employee,
			indicator: row.paid ? "green" : "blue",
			message: `${groups_html(groups)}${paid_footer(frm, row, advance)}`,
		});
	});
}

// Блоки виплат: заголовок і своя таблиця під ним — так «аванс» і «зарплата» не зливаються
// в один стовпчик однакових назв.
function groups_html(groups) {
	return groups
		.map(
			([title, lines]) => `
				<div style="margin-bottom: 10px;">
					<div style="font-weight: 700; font-size: 13px; margin-bottom: 6px;
						padding-bottom: 4px; border-bottom: 1px solid var(--border-color, #ddd);">${title}</div>
					${lines_html(lines)}
				</div>
			`
		)
		.join("");
}

// Дати й документи виплат — окремим абзацом під таблицею.
function paid_footer(frm, row, advance) {
	const notes = [];

	if (advance) {
		notes.push(
			`${__("Advance for {0}, paid on {1}.", [
				frappe.format(frm.doc.period_start, { fieldtype: "Date" }),
				frappe.format(advance.paid_on, { fieldtype: "Date" }),
			])} <a href="/app/salary-advance/${encodeURIComponent(
				advance.advance
			)}">${frappe.utils.escape_html(advance.advance)}</a>`
		);
	}

	if (row.paid && row.paid_date) {
		notes.push(__("Salary paid on {0}.", [frappe.format(row.paid_date, { fieldtype: "Date" })]));
	}

	if (!notes.length) return "";

	return `<p style="margin-top: 8px;">${notes.join("<br>")}</p>`;
}

// Скільки з готівкової половини людина вже отримала: аванс завжди, зарплата — коли рядок
// проведений. Разом це «Виплачено», а решта лишається в «До виплати».
// Виплачене офіційно — нарахуванням, а не сумою на картці: інакше колонка ніколи не зійшлася б
// із «Нараховано ОФ». До виплати зарплати місяць закриває лише аванс.
function paid_official(row) {
	return row.paid ? flt(row.earned_official) : flt(row.advance_official);
}

// Сума цієї виплати, до податків: нарахований місяць мінус аванс. Не залежить від того,
// заплатили вже чи ні — цим числом розписка й підтвердження говорять про одні гроші.
function remainder_official(row) {
	return flt(flt(row.earned_official) - flt(row.advance_official), 2);
}

// Те, що ще винні за місяць: та сама сума, поки її не виплатили.
function outstanding_official(row) {
	return row.paid ? 0 : remainder_official(row);
}

function paid_out(row) {
	return flt(row.advance_cash) + (row.paid ? flt(row.salary_cash) : 0);
}

// Готівкова половина податків не знає: нарахування, виданий аванс, уже виплачена зарплата —
// і те, що лишається на руки.
function show_cash_payout(frm, row) {
	const lines = [
		[__("Cash Salary"), money(row.cash_salary)],
		[__("Paid Days"), cash_worked(row)],
		[__("Accrued in Cash"), money(accrued_cash(row))],
	];

	// Прогул оплачує лише офіційна половина — готівкова за ці дні не платить і забирає
	// назад те, що за них уже пішло на картку.
	if (flt(row.absent_days)) {
		lines.push([__("Absent Days"), `− ${days(row.absent_days)}`]);
	}

	// Премію могли призначити готівкою — без окремого рядка нарахована сума виглядає
	// більшою за оклад половини.
	if (flt(row.bonus_cash)) {
		lines.push(
			[__("Bonus in Cash"), `+ ${money(row.bonus_cash)}`],
			[__("Accrued in Total"), money(row.earned_cash)]
		);
	}

	lines.push([__("Advance in Cash"), `− ${money(row.advance_cash)}`]);

	// Переплату офіційної половини й борг минулого місяця готівка гасить: обидва числа
	// стоять окремими рядками, інакше «до виплати» виглядає помилкою.
	if (flt(row.official_overpaid)) {
		lines.push(
			[__("Off. Overpaid"), money(row.official_overpaid)],
			[__("Withheld for the Overpayment"), `− ${money(overpay_withheld(row))}`]
		);
	}

	if (flt(row.absent_deduction)) {
		lines.push([__("Withheld for Absence"), `− ${money(row.absent_deduction)}`]);
	}

	if (flt(row.debt_carried)) {
		lines.push([__("Debt from the Previous Month"), `− ${money(row.debt_carried)}`]);
	}

	if (row.paid) {
		lines.push([__("Salary in Cash"), `− ${money(row.salary_cash)}`]);
	}

	lines.push([__("Paid Out"), money(paid_out(row))], [__("To Pay"), `<b>${money(row.outstanding)}</b>`]);

	// Готівки не вистачило на утримання — решта переходить у наступний місяць.
	if (flt(row.debt_forward)) {
		lines.push([__("Debt to the Next Month"), `<b>${money(row.debt_forward)}</b>`]);
	}

	frappe.msgprint({
		title: row.employee_name || row.employee,
		indicator: row.paid ? "green" : "blue",
		message: `
			${lines_html(lines)}
			<p class="text-muted" style="margin-top: 8px;">${__(
				"The salary is paid for {0} paid days of {1} working days in the month — working days less sick leave over 5 days.",
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
		payout: payout_lines(frm, row),
		note: row.note,
		// Без меж періоду календар не завантажується — відомість показує весь місяць,
		// на відміну від авансу, який обрізає його днем відсікання.
		start: frm.doc.period_start,
		end: frm.doc.period_end,
		part: is_official(frm) ? "official" : "cash",
	});
}

// What was paid, how much and by which documents — the row keeps its own receipt.
function show_receipt(frm, row) {
	const links = (
		is_official(frm)
			? [
					[__("Salary Slip"), row.salary_slip, "Salary Slip"],
					[__("Payment Entry (Card)"), row.journal_entry_card, "Journal Entry"],
					// Податки цієї виплати проводяться окремо — з розписки видно, куди вони пішли.
					[__("Tax Entry"), row.journal_entry_tax, "Journal Entry"],
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
