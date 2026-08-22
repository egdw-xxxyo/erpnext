frappe.ui.form.on("Salary Change", {
	onload(frm) {
		set_default_month(frm);
		erpnext.utils.month_field.apply_period(frm, "effective_from");
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
		warn: (row) => !flt(row.new_total),
		name_suffix: (row) =>
			changed(row) ? `<span class="employee-preview-badge">${__("Changed")}</span>` : "",
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

// One dialog moves a whole list at once: either everybody to the same amount, or everybody
// up by the same percent — the exceptions are edited afterwards.
function open_bulk_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Fill Amounts"),
		fields: [
			{
				fieldname: "mode",
				fieldtype: "Select",
				label: __("Mode"),
				options: [
					{ value: "amount", label: __("Set Amount") },
					{ value: "percent", label: __("Raise by %") },
				],
				default: "amount",
				reqd: 1,
			},
			{
				fieldname: "new_official",
				fieldtype: "Currency",
				label: __("New Official Salary"),
				depends_on: "eval:doc.mode === 'amount'",
			},
			{
				fieldname: "new_cash",
				fieldtype: "Currency",
				label: __("New Cash Salary"),
				depends_on: "eval:doc.mode === 'amount'",
			},
			{
				fieldname: "percent",
				fieldtype: "Percent",
				label: __("Raise by %"),
				depends_on: "eval:doc.mode === 'percent'",
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
			const rate = 1 + flt(values.percent) / 100;

			(frm.doc.employees || []).forEach((row) => {
				if (values.changed_only && !changed(row)) return;

				if (values.mode === "percent") {
					row.new_official = flt(flt(row.current_official) * rate, 2);
					row.new_cash = flt(flt(row.current_cash) * rate, 2);
				} else {
					["new_official", "new_cash"].forEach((fieldname) => {
						const value = values[fieldname];

						if (value !== undefined && value !== null && value !== "") {
							row[fieldname] = flt(value);
						}
					});
				}

				calculate_row(row);
			});

			frm.refresh_field("employees");
			refresh_view(frm);
			dialog.hide();
		},
	});

	dialog.show();
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

	frappe.confirm(
		__("The salary of {0} employees will change from {1}. Continue?", [
			frm.doc.employees_changed,
			frappe.format(frm.doc.effective_from, { fieldtype: "Date" }),
		]),
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
