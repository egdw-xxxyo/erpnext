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

frappe.ui.form.on("Salary Change Item", {
	new_official: (frm, cdt, cdn) => update_row(frm, cdt, cdn),
	new_cash: (frm, cdt, cdn) => update_row(frm, cdt, cdn),
});

// The same arithmetic the server runs on validate, so the row answers while the accountant
// is still typing instead of after a save.
function calculate_row(row) {
	row.current_total = flt(row.current_official) + flt(row.current_cash);
	row.new_total = flt(row.new_official) + flt(row.new_cash);
	row.change_amount = flt(row.new_total - row.current_total, 2);
	row.change_percent = row.current_total ? flt((row.change_amount / row.current_total) * 100, 2) : 0;
}

function update_row(frm, cdt, cdn) {
	calculate_row(locals[cdt][cdn]);
	frm.refresh_field("employees");
	refresh_view(frm);
}

function refresh_view(frm) {
	calculate_totals(frm);
	render_preview(frm);
}

// Мінімум бронювання приходить в `__onload`, але нового документа сервер не завантажує —
// там він читається з налаштувань і лишається в кеші на всю сесію. Запасне значення в коді
// потрібне лише поки не відповів сервер.
const RESERVATION_FALLBACK = 26000;
let reservation_cached = null;

function reservation_minimum(frm) {
	// Збережений документ носить свій мінімум — саме за ним його й погоджували.
	const onload = frm.doc.__onload && frm.doc.__onload.reservation_minimum;

	return flt(frm.doc.reservation_minimum) || flt(onload) || reservation_cached || RESERVATION_FALLBACK;
}

// Читається один раз на сесію: значення міняє постанова, а не користувач у формі.
function load_reservation_minimum(frm) {
	if (reservation_cached) return Promise.resolve(reservation_minimum(frm));

	return frappe.db.get_single_value("Payroll Tax Settings", "minimum_reservation_salary").then((value) => {
		reservation_cached = flt(value) || null;

		return reservation_minimum(frm);
	});
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
			format_currency(saved),
			format_currency(current),
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

// Бронюють за офіційною частиною: готівка для військкомату не існує.
function below_minimum(frm, row) {
	return flt(row.new_official) < reservation_minimum(frm);
}

function rows_below_minimum(frm) {
	return (frm.doc.employees || []).filter((row) => below_minimum(frm, row));
}

function show_reservation_warning(frm) {
	const below = rows_below_minimum(frm);

	if (!below.length) return;

	frm.dashboard.add_comment(
		__("{0} employees stay below the reservation minimum of {1} — they cannot be reserved.", [
			below.length,
			format_currency(reservation_minimum(frm)),
		]),
		"orange",
		true
	);
}

const money = (value) => erpnext.utils.employee_preview.money(value);
const number = (value) => erpnext.utils.employee_preview.number(value);

function changed(row) {
	return flt(row.new_official) !== flt(row.current_official) || flt(row.new_cash) !== flt(row.current_cash);
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
		warn: (row) => !flt(row.new_total) || below_minimum(frm, row),
		name_suffix: (row) => {
			const badges = [];

			if (changed(row)) {
				badges.push(`<span class="employee-preview-badge">${__("Changed")}</span>`);
			}

			// Значок стоїть на новому окладі: видно не «як було», а з чим людина лишиться.
			if (below_minimum(frm, row)) {
				badges.push(`<span class="employee-preview-badge warn">${__("Below reservation")}</span>`);
			}

			return badges.join("");
		},
		filter: { label: __("Changed only"), test: (row) => changed(row) },
		columns: [
			{ label: __("Current Official Salary"), value: (row) => money(row.current_official) },
			{ label: __("Current Cash Salary"), value: (row) => money(row.current_cash) },
			{ label: __("New Official Salary"), value: (row) => money(row.new_official) },
			{ label: __("New Cash Salary"), value: (row) => money(row.new_cash) },
			{ label: __("New Total Salary"), value: (row) => money(row.new_total), bold: true },
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
	const dialog = new frappe.ui.Dialog({
		title: row.employee_name || row.employee,
		fields: [
			{ fieldtype: "HTML", fieldname: "details" },
			{ fieldtype: "Section Break", label: __("New Salary") },
			{
				fieldtype: "Currency",
				fieldname: "new_official",
				label: __("New Official Salary"),
				default: flt(row.new_official),
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Currency",
				fieldname: "new_cash",
				label: __("New Cash Salary"),
				default: flt(row.new_cash),
			},
		],
		primary_action_label: __("Save"),
		primary_action(values) {
			frappe.model.set_value(row.doctype, row.name, {
				new_official: flt(values.new_official),
				new_cash: flt(values.new_cash),
			});
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

function salary_lines(frm, row) {
	const minimum = reservation_minimum(frm);
	const lines = [
		[__("Current Official Salary"), money(row.current_official)],
		[__("Current Cash Salary"), money(row.current_cash)],
		[__("New Official Salary"), money(row.new_official)],
		[__("New Cash Salary"), money(row.new_cash)],
		[__("New Total Salary"), `<b>${money(row.new_total)}</b>`],
	];

	if (changed(row)) {
		lines.push([__("Change"), delta(row)]);
	}

	lines.push([
		__("Minimum Salary for Reservation"),
		below_minimum(frm, row) ? `<span class="text-danger">${money(minimum)}</span>` : money(minimum),
	]);

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
	};

	rows.forEach((row) => {
		calculate_row(row);

		if (!changed(row)) return;

		totals.employees_changed += 1;
		totals.total_current += flt(row.current_total);
		totals.total_new += flt(row.new_total);
	});

	totals.total_change = flt(totals.total_new - totals.total_current, 2);

	// a read-only field with no value at all is hidden by the desk, so an untouched
	// document must still be given its zeroes
	Object.entries(totals).forEach(([fieldname, value]) => {
		if (frm.doc[fieldname] === undefined || flt(frm.doc[fieldname]) !== flt(value)) {
			frm.set_value(fieldname, value);
		}
	});

	frm.refresh_field("employees");
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
					{ value: "cash", label: __("Cash Salary") },
					{ value: "both", label: __("Both Halves") },
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
					"The official salary is set to {0} — the minimum for the reservation. Anybody already above it stays as they are.",
					[format_currency(minimum)]
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
		if (dialog.get_value("mode") === "minimum") {
			dialog.set_value("part", "official");
		}
	});

	dialog.show();
}

// Which fields of the row this fill touches.
function target_fields(part) {
	if (part === "official") return ["new_official"];
	if (part === "cash") return ["new_cash"];

	return ["new_official", "new_cash"];
}

function current_field(fieldname) {
	return fieldname === "new_official" ? "current_official" : "current_cash";
}

function fill_rows(frm, values, minimum) {
	const rate = 1 + flt(values.percent) / 100;
	const fields = values.mode === "minimum" ? ["new_official"] : target_fields(values.part);

	(frm.doc.employees || []).forEach((row) => {
		if (values.changed_only && !changed(row)) return;

		fields.forEach((fieldname) => {
			if (values.mode === "percent") {
				row[fieldname] = flt(flt(row[current_field(fieldname)]) * rate, 2);
			} else if (values.mode === "amount") {
				row[fieldname] = flt(values.amount);
			} else if (flt(row[fieldname]) < minimum) {
				// Підняття до мінімуму нікому оклад не ріже: хто вже вище — лишається.
				row[fieldname] = flt(minimum);
			}
		});

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
			message: __("Every employee is at or above the reservation minimum of {0}.", [
				format_currency(minimum),
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
			format_currency(minimum),
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
				format_currency(reservation_minimum(frm)),
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
		})
		.always(() => {
			frm.fetching_employees = false;
		});
}
