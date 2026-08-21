frappe.ui.form.on("Salary Approval", {
	onload(frm) {
		erpnext.utils.month_field.apply_period(frm, "effective_from");
	},

	refresh(frm) {
		// buttons first: a throw in any of the helpers below must not cost the toolbar
		if (!frm.doc.status || frm.doc.status === "Draft") {
			frm.add_custom_button(__("Fill Amounts for Everyone"), () => open_bulk_dialog(frm));
		}

		erpnext.utils.month_field.apply_period(frm, "effective_from");
		erpnext.utils.grid_editor.compact_row_actions(frm);
		calculate_totals(frm);
		mark_attendance(frm);
		render_preview(frm);

		if (frm.is_new()) {
			fetch_employees(frm);
			return;
		}

		frm.page.set_indicator(
			__(frm.doc.status),
			{ Draft: "orange", Approved: "green", Cancelled: "gray" }[frm.doc.status] || "gray"
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

	employees_add: (frm) => {
		calculate_totals(frm);
		render_preview(frm);
	},
	employees_remove: (frm) => {
		calculate_totals(frm);
		render_preview(frm);
	},
	validate: (frm) => calculate_totals(frm),
});

frappe.ui.form.on("Salary Approval Item", {
	official_salary: (frm, cdt, cdn) => update_row(frm, cdt, cdn),
	cash_salary: (frm, cdt, cdn) => update_row(frm, cdt, cdn),
	bonus_percent: (frm, cdt, cdn) => update_row(frm, cdt, cdn),
	allowance: (frm, cdt, cdn) => update_row(frm, cdt, cdn),
});

// The same arithmetic the server runs on validate, so the row and the totals answer
// while the accountant is still typing instead of after a save.
function calculate_row(row) {
	const base = flt(row.official_salary) + flt(row.cash_salary);

	row.bonus_amount = flt((base * flt(row.bonus_percent)) / 100, 2);
	row.total_salary = base + flt(row.bonus_amount) + flt(row.allowance);
}

function update_row(frm, cdt, cdn) {
	calculate_row(locals[cdt][cdn]);
	frm.refresh_field("employees");
	calculate_totals(frm);
	render_preview(frm);
}

const money = (value) => erpnext.utils.employee_preview.money(value);

function render_preview(frm) {
	erpnext.utils.employee_preview.render(frm, {
		field: "employees_preview",
		table: "employees",
		group_by: (row) => row.department || __("No Department"),
		warn: (row) => !row.attendance_approved,
		status_column: __("Attendance"),
		warn_label: __("No attendance sheet"),
		ok_label: __("Approved"),
		columns: [
			{ label: __("Official Salary"), value: (row) => money(row.official_salary) },
			{ label: __("Cash Salary"), value: (row) => money(row.cash_salary) },
			{
				label: __("Bonus %"),
				value: (row) => erpnext.utils.employee_preview.number(row.bonus_percent),
			},
			{ label: __("Bonus Amount"), value: (row) => money(row.bonus_amount) },
			{ label: __("Allowance"), value: (row) => money(row.allowance) },
			{ label: __("Total Salary"), value: (row) => money(row.total_salary), bold: true },
		],
	});
}

function calculate_totals(frm) {
	const rows = frm.doc.employees || [];
	const totals = {
		total_employees: rows.length,
		total_official: 0,
		total_cash: 0,
		total_bonus: 0,
		total_allowance: 0,
		total_salary: 0,
	};

	rows.forEach((row) => {
		calculate_row(row);

		totals.total_official += flt(row.official_salary);
		totals.total_cash += flt(row.cash_salary);
		totals.total_bonus += flt(row.bonus_amount);
		totals.total_allowance += flt(row.allowance);
		totals.total_salary += flt(row.total_salary);
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

// One dialog writes the same conditions into every row — the usual case is a whole
// department on the same terms, and only the exceptions get edited afterwards.
function open_bulk_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Fill Amounts"),
		fields: [
			{ fieldname: "official_salary", fieldtype: "Currency", label: __("Official Salary") },
			{ fieldname: "cash_salary", fieldtype: "Currency", label: __("Cash Salary") },
			{ fieldname: "bonus_percent", fieldtype: "Percent", label: __("Bonus %") },
			{ fieldname: "allowance", fieldtype: "Currency", label: __("Allowance") },
		],
		primary_action_label: __("Fill"),
		primary_action(values) {
			(frm.doc.employees || []).forEach((row) => {
				Object.entries(values).forEach(([fieldname, value]) => {
					if (value !== undefined && value !== null && value !== "") {
						row[fieldname] = flt(value);
					}
				});

				calculate_row(row);
			});

			frm.refresh_field("employees");
			calculate_totals(frm);
			render_preview(frm);
			dialog.hide();
		},
	});

	dialog.show();
}

function confirm_approval(frm) {
	frappe.confirm(
		__(
			"The salary of {0} employees will be written to their cards and the bonuses will be created. Continue?",
			[frm.doc.total_employees]
		),
		() =>
			frm
				.call({ doc: frm.doc, method: "approve", freeze: true, freeze_message: __("Working...") })
				.then((response) => {
					const applied = response.message || {};
					frappe.show_alert({
						message: __("Salary updated for {0}, bonuses created: {1}, allowances: {2}", [
							applied.salary || 0,
							applied.bonus || 0,
							applied.allowance || 0,
						]),
						indicator: "green",
					});
					frm.reload_doc();
				})
	);
}

// A new document fills itself: the accountant opens it and already sees who is in the
// month and whose timesheet is still open.
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
			method: "erpnext.payroll_ua.doctype.salary_approval.salary_approval.get_employees",
			args: { company: frm.doc.company, effective_from: frm.doc.effective_from },
		})
		.then((response) => {
			frm.clear_table("employees");
			(response.message || []).forEach((row) => frm.add_child("employees", row));
			frm.refresh_field("employees");
			mark_attendance(frm);
			render_preview(frm);
		})
		.always(() => {
			frm.fetching_employees = false;
		});
}

// The grid renders plain text, so the warning is painted onto the employee cell after
// every render — including the ones the grid does on its own (paging, expand, sort).
function mark_attendance(frm) {
	const grid = frm.fields_dict.employees && frm.fields_dict.employees.grid;
	if (!grid) return;

	const paint = () => {
		(grid.grid_rows || []).forEach((row) => {
			const $cell = row.row && row.row.find('[data-fieldname="employee_name"] .static-area');
			if (!$cell || !$cell.length) return;

			$cell.find(".attendance-warning").remove();

			if (!row.doc || row.doc.attendance_approved) return;

			$(
				`<i class="fa fa-exclamation-triangle attendance-warning" style="color: var(--orange-500); margin-right: 4px;"></i>`
			)
				.attr("title", row.doc.attendance_note || __("The attendance sheet is not approved"))
				.prependTo($cell);
		});
	};

	paint();
	show_missing_count(frm);

	if (!grid.attendance_warning_bound) {
		grid.attendance_warning_bound = true;
		const refresh = grid.refresh.bind(grid);
		grid.refresh = function (...args) {
			refresh(...args);
			paint();
		};
	}
}

function show_missing_count(frm) {
	frm.dashboard.clear_comment();

	const missing = (frm.doc.employees || []).filter((row) => !row.attendance_approved).length;

	if (!missing) return;

	frm.dashboard.add_comment(
		__(
			"{0} employees have no approved attendance sheet for this month — the salary cannot be approved.",
			[missing]
		),
		"orange",
		true
	);
}
