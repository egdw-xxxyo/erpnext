frappe.ui.form.on("Salary Change", {
	onload(frm) {
		set_default_month(frm);
		erpnext.utils.month_field.apply_period(frm, "effective_from");
		// Мінімум бронювання малюється в кожному рядку — без нього попередній перегляд
		// показував би застаріле запасне число.
		load_reservation_minimum(frm).then(() => {
			render_preview(frm);
			show_reservation_warning(frm);
		});
	},

	refresh(frm) {
		set_default_month(frm);

		// buttons first: a throw in any of the helpers below must not cost the toolbar
		if (!frm.doc.status || frm.doc.status === "Draft") {
			frm.add_custom_button(__("Fill Amounts for Everyone"), () => open_bulk_dialog(frm));
		}

		erpnext.utils.month_field.apply_period(frm, "effective_from");
		erpnext.utils.grid_editor.compact_row_actions(frm);
		calculate_totals(frm);
		render_preview(frm);

		if (frm.is_new()) {
			fetch_employees(frm);
			return;
		}

		show_reservation_warning(frm);
		load_reservation_minimum(frm).then(() => show_reservation_mismatch(frm));
		lock_when_approved(frm);

		frm.page.set_indicator(
			__(frm.doc.status),
			{ Draft: "orange", Approved: "green" }[frm.doc.status] || "gray"
		);

		if (frm.doc.status === "Draft") {
			frm.add_custom_button(__("Reload Employees"), () =>
				frm
					.call({ doc: frm.doc, method: "load_employees", freeze: true })
					.then(() => frm.reload_doc())
			);

			frm.add_custom_button(__("Approve"), () => confirm_approval(frm)).addClass("btn-primary");
		}
	},

	company: (frm) => fetch_employees(frm, true),
	effective_from: (frm) => fetch_employees(frm, true),

	employees_add: (frm) => refresh_view(frm),
	employees_remove: (frm) => refresh_view(frm),
	validate: (frm) => calculate_totals(frm),
});

// The current month is already being paid, so a new document opens on the next one.
function set_default_month(frm) {
	if (!frm.is_new() || frm.doc.effective_from) return;

	const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());

	frm.set_value(
		"effective_from",
		frappe.datetime.obj_to_str(new Date(today.getFullYear(), today.getMonth() + 1, 1)).slice(0, 10)
	);
}

// Як у картці працівника: вводять «Разом ЗП» і офіційну частину, а готівка — те, що лишається
// від суми на руки після нарахованого на картку.
frappe.ui.form.on("Salary Change Item", {
	new_in_hand: (frm, cdt, cdn) => update_row(frm, cdt, cdn, true),
	new_official: (frm, cdt, cdn) => update_row(frm, cdt, cdn, true),
	new_bonus: (frm, cdt, cdn) => update_row(frm, cdt, cdn),
});

// Ставки утримань приходять разом із порогами бронювання; до того рахуємо за законними.
let withheld_cached = { pit: 0.18, levy: 0.05 };

// Нараховане на картку — офіційна сума без ПДФО й військового збору, з тим самим
// округленням, що й на сервері.
function card_net(official) {
	const gross = flt(official, 2);

	return flt(gross - flt(gross * withheld_cached.pit, 2) - flt(gross * withheld_cached.levy, 2), 2);
}

function in_hand(official, cash) {
	return flt(card_net(official) + flt(cash), 2);
}

// Готівка з «Разом ЗП»: сума на руки лишається, змінюється лише те, що видається з каси.
function cash_from_in_hand(row) {
	row.new_cash = flt(flt(row.new_in_hand) - card_net(row.new_official), 2);
}

// The same arithmetic the server runs on validate, so the row answers while the accountant
// is still typing instead of after a save.
function calculate_row(row) {
	row.current_total = flt(row.current_official) + flt(row.current_cash);
	row.current_in_hand = in_hand(row.current_official, row.current_cash);
	row.new_total = flt(row.new_official) + flt(row.new_cash);
	row.new_in_hand = in_hand(row.new_official, row.new_cash);
	row.change_amount = flt(row.new_in_hand - row.current_in_hand, 2);
	row.change_percent = row.current_in_hand ? flt((row.change_amount / row.current_in_hand) * 100, 2) : 0;
}

function update_row(frm, cdt, cdn, recalculate_cash = false) {
	const row = locals[cdt][cdn];

	if (recalculate_cash) cash_from_in_hand(row);

	calculate_row(row);
	frm.refresh_field("employees");
	refresh_view(frm);
}

// Затверджений документ уже в картках працівників: правити його нема куди, тож форма
// закривається на замок — сервер це саме й перевіряє при збереженні.
function lock_when_approved(frm) {
	if (frm.doc.status !== "Approved") return;

	frm.disable_save();
	frm.set_read_only();
	frm.dashboard.add_comment(
		__("This change is approved — create a new document to change the salary again."),
		"blue",
		true
	);
}

function refresh_view(frm) {
	calculate_totals(frm);
	render_preview(frm);
}

// Мінімум бронювання приходить в `__onload`, але нового документа сервер не завантажує —
// там він питається окремо й лишається в кеші на всю сесію. Саме правило (кратне мінімальної
// зарплати) живе на сервері: форма його не повторює.
let reservation_cached = null;

function reservation_minimum(frm) {
	// Збережений документ носить свій мінімум — саме за ним його й погоджували.
	const onload = frm.doc.__onload && frm.doc.__onload.reservation_minimum;

	return flt(frm.doc.reservation_minimum) || flt(onload) || flt(reservation_cached);
}

// Читається один раз на сесію: значення міняє постанова, а не користувач у формі.
function load_reservation_minimum(frm) {
	if (reservation_cached) return Promise.resolve(reservation_minimum(frm));

	return frappe.call("erpnext.hr.payroll_tax.get_reservation_thresholds").then((response) => {
		const thresholds = response.message || {};

		reservation_cached = flt(thresholds.minimum) || null;
		average_cached = flt(thresholds.average_minimum) || null;

		if (thresholds.pit_rate !== undefined) {
			withheld_cached = { pit: flt(thresholds.pit_rate), levy: flt(thresholds.military_levy_rate) };
		}
		show_average_warning(frm);

		return reservation_minimum(frm);
	});
}

// Мінімум середньої зарплати — окреме число в налаштуваннях; порожнє означає «той самий
// мінімум бронювання».
let average_cached = null;

function average_minimum(frm) {
	const onload = frm.doc.__onload && frm.doc.__onload.reservation_average_minimum;

	return average_cached || flt(onload) || flt(reservation_cached);
}

// Решта компанії — ті, кого в документі немає: сума їхнього офіційного заробітку й кількість.
// Збережений документ отримує їх із сервера при відкритті, новий — окремим запитом.
function company_others(frm) {
	return frm.company_others || (frm.doc.__onload && frm.doc.__onload.company_others) || {};
}

function load_company_others(frm) {
	if (!frm.doc.company || !frm.doc.effective_from) return;

	frappe
		.call({
			method: "erpnext.payroll_ua.doctype.salary_change.salary_change.get_company_others",
			args: {
				company: frm.doc.company,
				effective_from: frm.doc.effective_from,
				employees: (frm.doc.employees || []).map((row) => row.employee),
			},
		})
		.then((response) => {
			frm.company_others = response.message || {};
			calculate_totals(frm);
		});
}

// Попередження стоїть під самим полем: середня — одне число, і шукати його пояснення в шапці
// документа незручно.
function show_average_warning(frm) {
	const minimum = average_minimum(frm);
	const warning = (text) =>
		`<span class="text-danger"><i class="fa fa-exclamation-triangle"></i> ${text}</span>`;
	const below = (value) => minimum && flt(value) > 0 && flt(value) < minimum;
	const month = frm.doc.average_accrued_month
		? frappe.datetime.str_to_user(frm.doc.average_accrued_month).slice(3)
		: "";

	// Факт: що нараховано за останній календарний місяць — саме це перевіряє закон.
	let accrued = __("Accrued for {0}: the law compares this number with the minimum of {1}.", [
		month,
		money(minimum),
	]);

	if (!frm.doc.average_accrued_month) {
		accrued = "";
	} else if (!flt(frm.doc.average_accrued)) {
		accrued = __("No Payroll Sheet for {0} yet — nothing to compare.", [month]);
	} else if (below(frm.doc.average_accrued)) {
		accrued = warning(
			__(
				"Accrued for {0} is below the minimum company average of {1} — the critical status is at risk.",
				[month, money(minimum)]
			)
		);
	}

	frm.set_df_property("average_accrued", "description", accrued);

	// Прогноз: якою середня стане в місяці цієї зміни.
	frm.set_df_property(
		"average_salary",
		"description",
		below(frm.doc.average_salary)
			? warning(
					__("Below the minimum company average salary for reservation of {0}.", [money(minimum)])
			  )
			: ""
	);
}

// Місяць, який ще не почався: у поточному чи закритому оклади вже рахуються, тож і мінімум
// у документі міняти нема сенсу.
function is_future_month(frm) {
	if (!frm.doc.effective_from) return false;

	const month = frappe.datetime.str_to_obj(frm.doc.effective_from);
	const now = frappe.datetime.str_to_obj(frappe.datetime.get_today());

	return month.getFullYear() * 12 + month.getMonth() > now.getFullYear() * 12 + now.getMonth();
}

// Документ носить мінімум із дня створення — постанова могла змінити його відтоді. Кажемо про
// розбіжність і даємо оновити одним натиском, поки місяць не почався.
function show_reservation_mismatch(frm) {
	const current = flt(reservation_cached);
	const saved = flt(frm.doc.reservation_minimum);

	if (!current || !saved || current === saved) return;
	if (frm.doc.status !== "Draft" || !is_future_month(frm)) return;

	frm.dashboard.add_comment(
		__("The document keeps the reservation minimum of {0}, and the settings now have {1}.", [
			money(saved),
			money(current),
		]),
		"orange",
		true
	);

	frm.add_custom_button(__("Update the Reservation Minimum"), () =>
		frm
			.call({ doc: frm.doc, method: "refresh_reservation_minimum", freeze: true })
			.then(() => frm.reload_doc())
	);
}

// Бронюють за офіційною частиною: готівка для військкомату не існує. Стежимо лише за тими,
// кому в картці позначено, що оклад має відповідати мінімуму бронювання.
function below_minimum(frm, row) {
	return cint(row.reservation_required) && official_with_bonus(row) < reservation_minimum(frm);
}

// Доплата рахується як офіційна зарплата, хоч поле окладу й не міняє.
function official_with_bonus(row) {
	return flt(flt(row.new_official) * employment_rate(row) + flt(row.new_bonus), 2);
}

// При неповній зайнятості людина заробляє частину окладу — і бронюють її за цією частиною.
function employment_rate(row) {
	return flt(row.employment_rate) || 1;
}

function rate_badge(row) {
	return employment_rate(row) === 1
		? ""
		: `<span class="employee-preview-badge">${__("Rate {0}", [employment_rate(row)])}</span>`;
}

// Скільки бракує до мінімуму, якщо оклад лишити як є.
function bonus_to_minimum(official, minimum, rate) {
	return Math.max(flt(minimum - flt(official) * rate, 2), 0);
}

// Оклад повної ставки, з якого на цій ставці виходить рівно мінімум.
function official_to_minimum(minimum, rate) {
	return Math.ceil((minimum / rate) * 100) / 100;
}

// Факт, а не прогноз: закон дивиться на нараховане за останній місяць. Лікарняний чи дні без
// збереження зменшують його, хоч оклад і достатній. Нуля не чіпаємо — це «даних ще немає».
function accrued_below(frm, row) {
	return (
		cint(row.reservation_required) &&
		flt(row.accrued_last_month) > 0 &&
		flt(row.accrued_last_month) < reservation_minimum(frm)
	);
}

function rows_below_minimum(frm) {
	return (frm.doc.employees || []).filter((row) => below_minimum(frm, row));
}

function show_reservation_warning(frm) {
	const below = rows_below_minimum(frm);
	const accrued = (frm.doc.employees || []).filter((row) => accrued_below(frm, row));

	if (accrued.length) {
		frm.dashboard.add_comment(
			__("{0} employees were accrued less than the reservation minimum of {1} last month: {2}", [
				accrued.length,
				money(reservation_minimum(frm)),
				accrued
					.slice(0, 20)
					.map((row) => frappe.utils.escape_html(row.employee_name || row.employee))
					.join(", ") + (accrued.length > 20 ? "…" : ""),
			]),
			"red",
			true
		);
	}

	if (!below.length) return;

	frm.dashboard.add_comment(
		__("{0} employees stay below the reservation minimum of {1} — they cannot be reserved.", [
			below.length,
			money(reservation_minimum(frm)),
		]),
		"orange",
		true
	);
}

const money = (value) => erpnext.utils.employee_preview.money(value);
const number = (value) => erpnext.utils.employee_preview.number(value);

function changed(row) {
	return (
		flt(row.new_official) !== flt(row.current_official) ||
		flt(row.new_cash) !== flt(row.current_cash) ||
		flt(row.new_bonus) !== flt(row.current_bonus)
	);
}

function delta(row) {
	if (!changed(row)) return "";

	const sign = flt(row.change_amount) > 0 ? "+" : "";

	return `${sign}${money(row.change_amount)} (${sign}${number(row.change_percent)}%)`;
}

function render_preview(frm) {
	erpnext.utils.employee_preview.render(frm, {
		field: "employees_preview",
		table: "employees",
		group_by: (row) => row.department || __("No Department"),
		open: (row) => show_details(frm, row),
		warn: (row) =>
			!flt(row.new_total) ||
			flt(row.new_cash) < 0 ||
			below_minimum(frm, row) ||
			accrued_below(frm, row),
		name_suffix: (row) => {
			const badges = [rate_badge(row)];

			if (changed(row)) {
				badges.push(`<span class="employee-preview-badge">${__("Changed")}</span>`);
			}

			// Значок стоїть на новому окладі: видно не «як було», а з чим людина лишиться.
			if (below_minimum(frm, row)) {
				badges.push(`<span class="employee-preview-badge warn">${__("Below reservation")}</span>`);
			}

			if (accrued_below(frm, row)) {
				badges.push(
					`<span class="employee-preview-badge warn">${__("Accrued below reservation")}</span>`
				);
			}

			return badges.join("");
		},
		filter: { label: __("Changed only"), test: (row) => changed(row) },
		columns: [
			{ label: __("Current Total Salary (In Hand)"), value: (row) => money(row.current_in_hand) },
			{ label: __("Current Official Salary"), value: (row) => money(row.current_official) },
			{ label: __("Current Cash Salary"), value: (row) => money(row.current_cash) },
			{ label: __("Total Salary"), value: (row) => money(row.new_in_hand), bold: true },
			{ label: __("Official Salary"), value: (row) => money(row.new_official) },
			{ label: __("Mgmt. Salary"), value: (row) => money(row.new_cash) },
			{ label: __("Official Bonus"), value: (row) => (flt(row.new_bonus) ? money(row.new_bonus) : "") },
			{ label: __("Change"), value: (row) => delta(row) },
		],
	});
}

// Табель тут довідка, а не підстава: оклад міняється з майбутнього місяця, а календар
// показує, як людина працювала — з гортанням по місяцях назад.
function show_details(frm, row) {
	const start = frappe.datetime.obj_to_str(month_start_of(frm.doc.effective_from));
	const end = frappe.datetime.obj_to_str(month_end_of(frm.doc.effective_from));
	const settings = {
		start,
		end,
		// У рядку зміни окладу табельних чисел немає — лишається сам календар.
		skip_attendance_table: true,
		salary: salary_lines(frm, row),
	};

	// Затверджений документ уже в картках працівників — там попап лише читається.
	if (frm.doc.status && frm.doc.status !== "Draft") {
		erpnext.utils.attendance_details.show(row, settings);
		return;
	}

	// Оклад правиться там, де на нього дивляться: рядок таблиці для цього доводилося
	// розгортати окремо.
	const minimum = reservation_minimum(frm);
	const reserved = cint(row.reservation_required);
	// `let`, not `const`: the field handlers fire while the dialog is still being built.
	let dialog = null;
	dialog = new frappe.ui.Dialog({
		title: row.employee_name || row.employee,
		fields: [
			{ fieldtype: "HTML", fieldname: "details" },
			{ fieldtype: "Section Break", label: __("New Salary") },
			{
				fieldtype: "Currency",
				fieldname: "new_in_hand",
				label: __("Total Salary"),
				description: __(
					"What the employee gets in hand: the amount accrued to the card plus the cash part."
				),
				default: flt(row.new_in_hand),
				onchange: () => update_dialog_cash(dialog),
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Currency",
				fieldname: "new_official",
				label: __("Official Salary"),
				description: __("The amount accrued officially, before taxes."),
				default: flt(row.new_official),
				onchange: () => update_dialog_cash(dialog),
			},
			{
				// Перший спосіб закрити бронювання: підняти сам оклад — назавжди.
				fieldtype: "Button",
				fieldname: "match_official",
				label: __("Match Required for Reservation"),
				hidden: !reserved,
				click: () => {
					dialog.set_value("new_official", official_to_minimum(minimum, employment_rate(row)));
					dialog.set_value("new_bonus", 0);
				},
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Currency",
				fieldname: "new_cash",
				label: __("Mgmt. Salary"),
				description: __(
					"Calculated: the total salary less the amount accrued to the card. Paid from the cash desk and not taxed."
				),
				read_only: 1,
				default: flt(row.new_cash),
			},
			{ fieldtype: "Section Break" },
			{
				fieldtype: "Currency",
				fieldname: "new_bonus",
				label: __("Official Bonus"),
				description: __(
					"For this month only. Counts as official salary without changing it; the cash part of the month shrinks so the amount in hand stays the same."
				),
				default: flt(row.new_bonus),
			},
			{
				// Другий спосіб: оклад не чіпати, а до мінімуму дотягнути доплатою на місяць.
				fieldtype: "Button",
				fieldname: "match_bonus",
				label: __("Match Required for Reservation"),
				hidden: !reserved,
				click: () =>
					dialog.set_value(
						"new_bonus",
						bonus_to_minimum(dialog.get_value("new_official"), minimum, employment_rate(row))
					),
			},
		],
		primary_action_label: __("Save"),
		primary_action(values) {
			const cash = flt(flt(values.new_in_hand) - card_net(values.new_official), 2);

			if (cash < 0) {
				frappe.msgprint({
					title: __("Total Salary Is Too Low"),
					indicator: "red",
					message: __("Total Salary cannot be less than the amount accrued to the card ({0}).", [
						money(card_net(values.new_official)),
					]),
				});
				return;
			}

			// Готівку пишемо напряму: обробник рядка перерахував би її ще раз із недописаної суми.
			Object.assign(row, {
				new_official: flt(values.new_official),
				new_cash: cash,
				new_bonus: flt(values.new_bonus),
			});
			calculate_row(row);
			frm.dirty();
			frm.refresh_field("employees");
			refresh_view(frm);
			dialog.hide();
		},
	});

	dialog.fields_dict.details.$wrapper.html(
		erpnext.utils.attendance_details.html(row, Object.assign({}, settings, { calendar_slot: true }))
	);
	dialog.show();
	erpnext.utils.attendance_details.mount_calendar(dialog, row, settings);
}

function update_dialog_cash(dialog) {
	if (!dialog) return;

	dialog.set_value(
		"new_cash",
		flt(flt(dialog.get_value("new_in_hand")) - card_net(dialog.get_value("new_official")), 2)
	);
}

function salary_lines(frm, row) {
	const minimum = reservation_minimum(frm);
	const lines = [
		[__("Current Total Salary (In Hand)"), money(row.current_in_hand)],
		[__("Current Official Salary"), money(row.current_official)],
		[__("Current Cash Salary"), money(row.current_cash)],
		[__("Total Salary"), `<b>${money(row.new_in_hand)}</b>`],
		[__("Official Salary"), money(row.new_official)],
		[__("Mgmt. Salary"), money(row.new_cash)],
	];

	if (flt(row.new_bonus)) {
		lines.push([__("Official Bonus"), money(row.new_bonus)]);
	}

	if (employment_rate(row) !== 1) {
		lines.push([__("Employment Rate"), employment_rate(row)]);
		lines.push([__("Paid at This Rate"), money(official_with_bonus(row))]);
	}

	if (changed(row)) {
		lines.push([__("Change"), delta(row)]);
	}

	if (cint(row.reservation_required)) {
		if (flt(row.accrued_last_month)) {
			lines.push([
				__("Accrued Last Month"),
				accrued_below(frm, row)
					? `<span class="text-danger">${money(row.accrued_last_month)}</span>`
					: money(row.accrued_last_month),
			]);
		}

		lines.push([
			__("Minimum Salary for Reservation"),
			below_minimum(frm, row) ? `<span class="text-danger">${money(minimum)}</span>` : money(minimum),
		]);
	}

	return lines;
}

function month_start_of(date) {
	const parsed = frappe.datetime.str_to_obj(date || frappe.datetime.get_today());

	return new Date(parsed.getFullYear(), parsed.getMonth(), 1);
}

function month_end_of(date) {
	const parsed = frappe.datetime.str_to_obj(date || frappe.datetime.get_today());

	return new Date(parsed.getFullYear(), parsed.getMonth() + 1, 0);
}

function calculate_totals(frm) {
	const rows = frm.doc.employees || [];
	const totals = {
		total_employees: rows.length,
		employees_changed: 0,
		total_current: 0,
		total_new: 0,
		total_change: 0,
		average_salary: 0,
	};
	let official = 0;
	let counted = 0;

	rows.forEach((row) => {
		calculate_row(row);
		// Без офіційного окладу людині офіційно нічого не нараховують — у середню вона не входить.
		if (official_with_bonus(row) > 0) {
			official += official_with_bonus(row);
			counted += 1;
		}

		if (!changed(row)) return;

		totals.employees_changed += 1;
		totals.total_current += flt(row.current_total);
		totals.total_new += flt(row.new_total);
	});

	totals.total_change = flt(totals.total_new - totals.total_current, 2);
	// Середня — по всій компанії: до свого списку керівник додає решту з чинними окладами.
	const others = company_others(frm);
	const headcount = counted + cint(others.count);

	totals.average_salary = headcount ? flt((official + flt(others.total)) / headcount, 2) : 0;

	// a read-only field with no value at all is hidden by the desk, so an untouched
	// document must still be given its zeroes
	Object.entries(totals).forEach(([fieldname, value]) => {
		if (frm.doc[fieldname] === undefined || flt(frm.doc[fieldname]) !== flt(value)) {
			frm.set_value(fieldname, value);
		}
	});

	frm.refresh_field("employees");
	show_average_warning(frm);
}

// One dialog moves a whole list at once: one half of the salary, by percent or to a fixed
// amount — the exceptions are edited afterwards. The reservation minimum is a mode of its
// own: it is the one number that comes from the settings, not from the accountant.
function open_bulk_dialog(frm) {
	const minimum = reservation_minimum(frm);
	const dialog = new frappe.ui.Dialog({
		title: __("Fill Amounts"),
		fields: [
			{
				fieldname: "part",
				fieldtype: "Select",
				label: __("Which Salary"),
				options: [
					{ value: "official", label: __("Official Salary") },
					{ value: "in_hand", label: __("Total Salary") },
					{ value: "both", label: __("Both Halves") },
					{ value: "bonus", label: __("Official Bonus") },
				],
				default: "official",
				reqd: 1,
			},
			{
				fieldname: "mode",
				fieldtype: "Select",
				label: __("Mode"),
				options: [
					{ value: "percent", label: __("Raise by %") },
					{ value: "amount", label: __("Set Amount") },
					{ value: "minimum", label: __("Set to the Reservation Minimum") },
				],
				default: "percent",
				reqd: 1,
			},
			{
				fieldname: "percent",
				fieldtype: "Percent",
				label: __("Raise by %"),
				depends_on: "eval:doc.mode === 'percent'",
			},
			{
				fieldname: "amount",
				fieldtype: "Currency",
				label: __("New Salary"),
				depends_on: "eval:doc.mode === 'amount'",
			},
			{
				fieldname: "minimum_note",
				fieldtype: "HTML",
				options: `<p class="text-muted">${__(
					"The official salary of the employees marked for reservation is set to {0} — the minimum for it. Anybody already above it stays as they are.",
					[money(minimum)]
				)}</p>`,
				depends_on: "eval:doc.mode === 'minimum'",
			},
			{
				fieldname: "changed_only",
				fieldtype: "Check",
				label: __("Only the rows already changed"),
				default: 0,
			},
		],
		primary_action_label: __("Fill"),
		primary_action(values) {
			fill_rows(frm, values, minimum);
			dialog.hide();
			warn_below_minimum(frm, minimum);
		},
	});

	// «До мінімуму» стосується лише офіційної частини — готівка бронювання не дає.
	dialog.fields_dict.mode.$input.on("change", () => {
		if (dialog.get_value("mode") === "minimum" && dialog.get_value("part") !== "bonus") {
			dialog.set_value("part", "official");
		}
	});

	dialog.show();
}

// Which fields of the row this fill touches.
function target_fields(part) {
	if (part === "official") return ["new_official"];
	if (part === "in_hand") return ["new_in_hand"];
	if (part === "bonus") return ["new_bonus"];

	return ["new_official", "new_cash"];
}

function current_field(fieldname) {
	return {
		new_official: "current_official",
		new_cash: "current_cash",
		new_bonus: "current_bonus",
		new_in_hand: "current_in_hand",
	}[fieldname];
}

function fill_rows(frm, values, minimum) {
	const rate = 1 + flt(values.percent) / 100;
	// «До мінімуму» закривається або окладом, або доплатою на місяць — готівка тут ні до чого.
	const to_minimum = values.mode === "minimum";
	const with_bonus = to_minimum && values.part === "bonus";
	const fields = to_minimum ? [with_bonus ? "new_bonus" : "new_official"] : target_fields(values.part);

	(frm.doc.employees || []).forEach((row) => {
		if (values.changed_only && !changed(row)) return;

		calculate_row(row);

		fields.forEach((fieldname) => {
			if (values.mode === "percent") {
				row[fieldname] = flt(flt(row[current_field(fieldname)]) * rate, 2);
			} else if (values.mode === "amount") {
				row[fieldname] = flt(values.amount);
			} else if (cint(row.reservation_required) && below_minimum(frm, row)) {
				// Підняття до мінімуму нікому оклад не ріже: хто вже вище — лишається.
				if (with_bonus) {
					row.new_bonus = bonus_to_minimum(row.new_official, minimum, employment_rate(row));
				} else {
					row.new_official = official_to_minimum(minimum, employment_rate(row));
					row.new_bonus = 0;
				}
			}
		});

		// Обидві половини разом рухають і суму на руки; одна з них лише ділить ту саму
		// «Разом ЗП» по-іншому, як у картці. Готівка нижче нуля не йде: тоді росте сума на руки.
		if (values.part !== "both" || to_minimum) {
			cash_from_in_hand(row);
			row.new_cash = Math.max(row.new_cash, 0);
		}

		calculate_row(row);
	});

	frm.refresh_field("employees");
	refresh_view(frm);
}

// The point of the fill is usually the reservation, so the answer to it comes right after.
function warn_below_minimum(frm, minimum) {
	const below = rows_below_minimum(frm);

	if (!below.length) {
		frappe.show_alert({
			message: __("Every employee marked for reservation is at or above the minimum of {0}.", [
				money(minimum),
			]),
			indicator: "green",
		});
		return;
	}

	frappe.msgprint({
		title: __("Below the Reservation Minimum"),
		indicator: "orange",
		message: __("{0} employees stay below {1}: {2}", [
			below.length,
			money(minimum),
			below
				.slice(0, 20)
				.map((row) => frappe.utils.escape_html(row.employee_name || row.employee))
				.join(", ") + (below.length > 20 ? "…" : ""),
		]),
	});
}

function confirm_approval(frm) {
	if (!frm.doc.employees_changed) {
		frappe.msgprint({
			title: __("Nothing to Change"),
			indicator: "orange",
			message: __("No salary is changed here — the new amounts equal the current ones."),
		});
		return;
	}

	const below = rows_below_minimum(frm);
	// Бронювання перевіряється тут востаннє: після затвердження оклад уже в картці.
	const note = below.length
		? `<br><br>${__("{0} of them stay below the reservation minimum of {1}.", [
				below.length,
				money(reservation_minimum(frm)),
		  ])}`
		: "";

	frappe.confirm(
		__("The salary of {0} employees will change from {1}. Continue?", [
			frm.doc.employees_changed,
			frappe.format(frm.doc.effective_from, { fieldtype: "Date" }),
		]) + note,
		() =>
			frm
				.call({ doc: frm.doc, method: "approve", freeze: true, freeze_message: __("Working...") })
				.then((response) => {
					frappe.show_alert({
						message: __("Salary updated for {0} employees", [response.message || 0]),
						indicator: "green",
					});
					frm.reload_doc();
				})
	);
}

// A new document fills itself: the accountant opens it and already sees the current salaries.
function fetch_employees(frm, replace = false) {
	if (!frm.is_new() || !frm.doc.company || !frm.doc.effective_from) {
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
			method: "erpnext.payroll_ua.doctype.salary_change.salary_change.get_employees",
			args: { company: frm.doc.company, effective_from: frm.doc.effective_from },
		})
		.then((response) => {
			frm.clear_table("employees");
			(response.message || []).forEach((row) => frm.add_child("employees", row));
			frm.refresh_field("employees");
			refresh_view(frm);
			load_company_others(frm);
		})
		.always(() => {
			frm.fetching_employees = false;
		});
}
