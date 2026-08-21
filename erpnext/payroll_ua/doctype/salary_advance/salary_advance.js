frappe.ui.form.on("Salary Advance", {
	onload(frm) {
		erpnext.utils.month_field.apply_period(frm, "period_start");
	},

	refresh(frm) {
		// buttons first: a throw in any of the helpers below must not cost the toolbar
		if (!frm.is_new() && frm.doc.status === "Draft") {
			frm.add_custom_button(__("Recalculate"), () => run(frm, "calculate"));
			frm.add_custom_button(__("Create Advance"), () => confirm_create(frm)).addClass("btn-primary");
		}

		if (!frm.is_new() && frm.doc.status === "To Pay") {
			frm.add_custom_button(__("Pay Advance"), () => ask_payment_date(frm)).addClass("btn-primary");
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
			{ Draft: "orange", "To Pay": "blue", Paid: "green" }[frm.doc.status] || "gray"
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
		total_credited_days: 0,
		total_advance_card: 0,
		total_advance_cash: 0,
		total_advance: 0,
		employees_without_attendance: rows.filter((row) => !row.attendance_approved).length,
	};

	rows.forEach((row) => {
		row.advance_total = flt(row.advance_card) + flt(row.advance_cash);

		totals.total_credited_days += flt(row.credited_days);
		totals.total_advance_card += flt(row.advance_card);
		totals.total_advance_cash += flt(row.advance_cash);
		totals.total_advance += flt(row.advance_total);
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
			{ label: __("Credited Days"), value: (row) => number(row.credited_days) },
			{ label: __("Working Days in Half"), value: (row) => number(row.planned_days) },
			{ label: __("Daily Rate"), value: (row) => money(row.daily_rate) },
			{ label: __("Advance to Card"), value: (row) => money(row.advance_card) },
			{ label: __("Advance in Cash"), value: (row) => money(row.advance_cash) },
			{ label: __("Total Advance"), value: (row) => money(row.advance_total), bold: true },
			{ label: __("Paid"), value: (row) => (row.paid ? __("Yes") : "") },
		],
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
			frm.clear_table("employees");
			(response.message || []).forEach((row) => frm.add_child("employees", row));
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

function confirm_create(frm) {
	frappe.confirm(
		__("The advance of {0} employees will be filed as a deduction on their payslips. Continue?", [
			frm.doc.total_employees,
		]),
		() => run(frm, "create_advance")
	);
}

function ask_payment_date(frm) {
	frappe.prompt(
		{
			fieldname: "posting_date",
			fieldtype: "Date",
			label: __("Payment Date"),
			default: frm.doc.payment_date,
			reqd: 1,
		},
		(values) => run(frm, "pay", values),
		__("Pay Advance"),
		__("Post")
	);
}
