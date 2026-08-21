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

		if (!frm.doc.payroll_entry) {
			frm.add_custom_button(__("Accrue Salary"), () => run(frm, "create_payroll"), __("Payroll"));
		}

		// Аванс живе окремим документом — платиться 15-го, задовго до розрахунку місяця.
		frm.add_custom_button(__("Advance"), () => open_advance(frm), __("Payroll"));

		if (frm.doc.total_outstanding) {
			frm.add_custom_button(__("Pay Salary"), () => pay(frm), __("Pay"));
		}

		frm.trigger("show_status");
	},

	show_status(frm) {
		const colors = { Draft: "gray", "To Pay": "orange", "Partly Paid": "yellow", Paid: "green" };
		frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");

		if (frm.doc.employees_without_attendance) {
			frm.dashboard.add_comment(
				__("{0} employees have no attendance for the period — they get no salary slip.", [
					frm.doc.employees_without_attendance,
				]),
				"orange",
				true
			);
		}
	},
});

const money = (value) => erpnext.utils.employee_preview.money(value);

function render_preview(frm) {
	erpnext.utils.employee_preview.render(frm, {
		field: "employees_preview",
		table: "employees",
		group_by: (row) => row.department || __("No Department"),
		warn: (row) => !row.credited_days,
		status_column: __("Attendance"),
		warn_label: __("No attendance sheet"),
		ok_label: __("Present"),
		columns: [
			{ label: __("Days"), value: (row) => erpnext.utils.employee_preview.number(row.credited_days) },
			{ label: __("Gross Pay"), value: (row) => money(row.gross_pay) },
			{ label: __("Advance"), value: (row) => money(flt(row.advance_card) + flt(row.advance_cash)) },
			{ label: __("To Card"), value: (row) => money(row.salary_card) },
			{ label: __("Deposit"), value: (row) => money(row.deposit) },
			{ label: __("Outstanding"), value: (row) => money(row.outstanding), bold: true },
			{ label: __("Paid"), value: (row) => (row.paid ? __("Yes") : "") },
		],
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

function pay(frm) {
	frappe.prompt(
		{
			fieldname: "posting_date",
			fieldtype: "Date",
			label: __("Payment Date"),
			default: frm.doc.period_end,
			reqd: 1,
		},
		(values) => run(frm, "pay", { posting_date: values.posting_date }),
		__("Pay Salary"),
		__("Post")
	);
}
