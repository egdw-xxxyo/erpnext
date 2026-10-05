// Оклади працівника по періодах — прямо на картці, щоб не шукати призначення структури.
// Джерело те саме, що й у звіті «Історія окладів»: подані Salary Structure Assignment.

frappe.ui.form.on("Employee", {
	// «Нараховано на картку» рахує сервер при збереженні, але правлять оклад тут і зараз —
	// тож поки поле в руках, показуємо результат одразу.
	custom_official_salary(frm) {
		show_card_amount(frm, true);
	},

	custom_total_salary(frm) {
		show_card_amount(frm, true);
	},

	custom_official_bonus: (frm) => show_reservation_match(frm),
	custom_official_bonus_month: (frm) => show_reservation_match(frm),
	custom_reservation_salary: (frm) => show_reservation_match(frm),
	custom_salary_effective_from: (frm) => show_reservation_match(frm),
	employment_type: (frm) => show_reservation_match(frm),
	custom_employment_rate: (frm) => show_reservation_match(frm),

	refresh(frm) {
		show_card_amount(frm);
		show_reservation_match(frm);

		if (frm.is_new()) return;

		frappe
			.call({
				method: "erpnext.payroll_ua.salary_history.get_salary_history",
				args: { employee: frm.doc.name },
			})
			.then((response) => render(frm, response.message || []));
	},
});

function render(frm, history) {
	if (!history.length) return;

	const date = (value) => (value ? frappe.format(value, { fieldtype: "Date" }) : "…");
	const money = (value) => format_currency(flt(value), frappe.defaults.get_default("currency"), 2);

	const rows = history
		.slice()
		.reverse()
		.map((row) => {
			const label = { Past: __("Past"), Current: __("Current"), Future: __("Future") }[row.period];
			const style =
				row.period === "Current"
					? "font-weight: bold;"
					: row.period === "Future"
					? "color: var(--blue-600);"
					: "color: var(--text-muted);";

			return `<tr style="${style}">
				<td>${date(row.from_date)} — ${date(row.to_date)}</td>
				<td class="text-right">${money(row.official)}</td>
				<td class="text-right">${money(row.cash)}</td>
				<td class="text-right">${money(row.total)}</td>
				<td class="text-right">${row.change ? money(row.change) : ""}</td>
				<td>${label}</td>
			</tr>`;
		})
		.join("");

	const html = `
		<table class="table table-bordered" style="margin: 0;">
			<thead>
				<tr>
					<th>${__("Period")}</th>
					<th class="text-right">${__("Official Salary")}</th>
					<th class="text-right">${__("Mgmt. Salary")}</th>
					<th class="text-right">${__("Total Salary")}</th>
					<th class="text-right">${__("Change")}</th>
					<th>${__("Status")}</th>
				</tr>
			</thead>
			<tbody>${rows}</tbody>
		</table>`;

	frm.dashboard.add_section(html, __("Salary History"));
}

// Ставки живуть у «Налаштуваннях зарплатних податків» — беремо їх звідти, а не з коду,
// інакше картка почне розходитися з листком наступного ж дня після зміни закону.
function show_card_amount(frm, with_cash) {
	const gross = flt(frm.doc.custom_official_salary);

	if (with_cash) show_reservation_match(frm);

	withheld_rates().then(([pit, levy]) => {
		const net = gross ? flt(gross - flt(gross * pit, 2) - flt(gross * levy, 2), 2) : 0;
		frm.set_value("custom_official_salary_net", net);

		// Готівку перераховуємо лише коли оклад правлять: на відкритті картка не має ставати зміненою.
		if (with_cash && flt(frm.doc.custom_total_salary)) {
			frm.set_value("custom_cash_salary", flt(flt(frm.doc.custom_total_salary) - net, 2));
		}
	});
}

function withheld_rates() {
	if (!withheld_rates.promise) {
		withheld_rates.promise = Promise.all([
			frappe.db.get_single_value("Payroll Tax Settings", "pit_rate"),
			frappe.db.get_single_value("Payroll Tax Settings", "military_levy_rate"),
		]).then(([pit, levy]) => [flt(pit || 18) / 100, flt(levy || 5) / 100]);
	}

	return withheld_rates.promise;
}

// Оклад нижче мінімуму бронювання закривається двома способами: підняти сам оклад або дати
// доплату на місяць, не чіпаючи його. Кнопка стоїть під кожним із двох полів і з'являється
// лише тому, кому в картці позначено бронювання і кому справді бракує.
function show_reservation_match(frm) {
	reservation_minimum().then((minimum) => {
		// При неповній зайнятості нараховується частина окладу — за нею й бронюють.
		const rate = employment_rate(frm);
		const official = flt(flt(frm.doc.custom_official_salary) * rate, 2);
		const below =
			cint(frm.doc.custom_reservation_salary) &&
			flt(official + active_bonus(frm), 2) < minimum &&
			!frm.is_new();

		match_button(frm, "custom_official_salary", below, () => {
			frm.set_value("custom_official_bonus", 0);
			frm.set_value("custom_official_salary", Math.ceil((minimum / rate) * 100) / 100);
		});

		match_button(frm, "custom_official_bonus", below, () => {
			frm.set_value("custom_official_bonus_month", bonus_month(frm));
			frm.set_value("custom_official_bonus", flt(minimum - official, 2));
		});

		show_paid_at_rate(frm, rate);
		show_accrued_warning(frm, minimum);
	});
}

function match_button(frm, fieldname, visible, action) {
	const field = frm.fields_dict[fieldname];

	if (!field) return;

	field.$wrapper.find(".reservation-match").remove();

	if (!visible || !frm.perm[0].write) return;

	$(`<button type="button" class="btn btn-xs btn-warning reservation-match" style="margin-top: 4px;">
			<i class="fa fa-exclamation-triangle"></i> ${__("Match Required for Reservation")}
		</button>`)
		.appendTo(field.$wrapper.find(".control-input-wrapper"))
		.on("click", action);
}

// Доплата рахується лише у своєму місяці: минула бронювання вже не тримає.
function active_bonus(frm) {
	const month = frm.doc.custom_official_bonus_month;

	if (!flt(frm.doc.custom_official_bonus)) return 0;
	if (month && month.slice(0, 7) < frappe.datetime.get_today().slice(0, 7)) return 0;

	return flt(frm.doc.custom_official_bonus);
}

// Місяць доплати — поточний, а якщо оклад у картці діє з пізнішої дати, то її місяць.
function bonus_month(frm) {
	const today = frappe.datetime.get_today();
	const effective = frm.doc.custom_salary_effective_from;
	const date = effective && effective > today ? effective : today;

	return `${date.slice(0, 7)}-01`;
}

function reservation_minimum() {
	if (!reservation_minimum.promise) {
		// Правило (кратне мінімальної зарплати) живе на сервері — картка лише питає суму.
		reservation_minimum.promise = frappe
			.call("erpnext.hr.payroll_tax.get_reservation_thresholds")
			.then((response) => flt((response.message || {}).minimum));
	}

	return reservation_minimum.promise;
}

function employment_rate(frm) {
	const rate = flt(frm.doc.custom_employment_rate, 2);

	return frm.doc.employment_type === "Part-time" && rate > 0 && rate <= 1 ? rate : 1;
}

// Поля окладу тримають суми повної ставки. Щоб не множити в голові, під ставкою показуємо,
// скільки з них виходить насправді.
function show_paid_at_rate(frm, rate) {
	if (!frm.fields_dict.custom_employment_rate) return;

	const money = (value) => format_currency(flt(flt(value) * rate, 2), frm.doc.salary_currency, 2);

	frm.set_df_property(
		"custom_employment_rate",
		"description",
		rate === 1
			? __("From 0 to 1: the share of a full working day and of the salary. Empty means a full rate.")
			: __("Paid at this rate: official {0}, cash {1}.", [
					money(frm.doc.custom_official_salary),
					money(frm.doc.custom_cash_salary),
			  ])
	);
}

// Бронювання перевіряють за нарахованим, а не за окладом: місяць із лікарняним чи днями без
// збереження може виявитися нижчим за мінімум. Кажемо про це під самою позначкою.
function show_accrued_warning(frm, minimum) {
	if (frm.is_new() || !cint(frm.doc.custom_reservation_salary)) {
		frm.set_df_property("custom_reservation_salary", "description", "");
		return;
	}

	frappe
		.call({
			method: "erpnext.payroll_ua.doctype.salary_change.salary_change.get_employee_accrued",
			args: { employee: frm.doc.name },
		})
		.then((response) => {
			const accrued = response.message || {};
			const below = flt(accrued.amount) > 0 && flt(accrued.amount) < minimum;

			frm.set_df_property(
				"custom_reservation_salary",
				"description",
				below
					? `<span class="text-danger"><i class="fa fa-exclamation-triangle"></i> ${__(
							"Accrued for {0}: {1} — below the reservation minimum of {2}.",
							[
								frappe.datetime.str_to_user(accrued.month).slice(3),
								format_currency(accrued.amount, frm.doc.salary_currency, 2),
								format_currency(minimum, frm.doc.salary_currency, 2),
							]
					  )}</span>`
					: ""
			);
		});
}
