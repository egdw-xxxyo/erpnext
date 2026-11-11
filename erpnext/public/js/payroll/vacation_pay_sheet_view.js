// Відомість відпускних: скільки днів відпустки працівники взяли і скільки з них уже оплачено офіційно.
// Дні копляться, а офіційний блок платиться одним рухом — закон вимагає не менше 14 днів в одній частині.

frappe.provide("erpnext.payroll");

const money = (value) => erpnext.utils.employee_preview.money(value);
const number = (value) => erpnext.utils.employee_preview.number(value);
const days = (value) => __("{0} d", [number(value)]);

erpnext.payroll.vacation_pay_sheet_view = function (doctype) {
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
			show_status(frm);
		},
	});
};

function show_status(frm) {
	const colors = { Draft: "gray", "To Pay": "orange", "Partly Paid": "yellow", Paid: "green" };
	frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");

	const late = (frm.doc.employees || []).filter(
		(row) => !row.paid && cint(row.pay_days) && row.due_date && row.due_date < frappe.datetime.get_today()
	).length;

	if (late) {
		frm.dashboard.add_comment(
			__("{0} employees are paid later than the due date before the vacation.", [late]),
			"red",
			true
		);
	}
}

function render_preview(frm) {
	erpnext.utils.employee_preview.render(frm, {
		field: "employees_preview",
		table: "employees",
		group_by: (row) => row.department || __("No Department"),
		open: (row) => frappe.set_route("Form", "Employee", row.employee),
		warn: (row) => Boolean(row.note) && !row.paid,
		name_suffix: (row) =>
			row.paid
				? ""
				: (row.note || "")
						.split("\n")
						.filter(Boolean)
						.map(
							(text) =>
								`<span class="employee-preview-badge warn">${frappe.utils.escape_html(
									text
								)}</span>`
						)
						.join(""),
		filter: { label: __("Unpaid only"), test: (row) => !row.paid },
		columns: [
			{ label: __("Requested"), value: (row) => days(row.requested_days) },
			{
				label: __("Already Paid (Opening)"),
				value: (row) => days(row.opening_paid_days),
				clickable: (row) => !row.paid,
				click: (row) => ask_opening(frm, row),
			},
			{ label: __("Paid Through Sheets"), value: (row) => days(row.sheet_paid_days) },
			{ label: __("Unpaid Days"), value: (row) => days(row.unpaid_days), bold: true },
			{
				label: __("Days to Pay"),
				value: (row) => days(row.pay_days),
				clickable: (row) => !row.paid && cint(row.unpaid_days) > 0,
				click: (row) => ask_pay_days(frm, row),
			},
			{ label: __("Period"), value: (row) => period(row) },
			{
				label: __("Pay Not Later Than"),
				value: (row) => (row.due_date ? frappe.datetime.str_to_user(row.due_date) : "—"),
			},
			{ label: __("Accrued"), value: (row) => money(row.gross), secret: true },
			{ label: __("To Card"), value: (row) => money(row.net), bold: true, secret: true },
			{
				label: __("Payment"),
				value: (row) => (row.paid ? __("Paid") : cint(row.pay_days) > 0 ? __("Pay") : ""),
				clickable: (row) => row.paid || cint(row.pay_days) > 0,
				click: (row) => (row.paid ? show_receipt(row) : ask_payment_date(frm, row)),
			},
		],
	});
}

function period(row) {
	if (!row.first_day) return "—";

	return `${frappe.datetime.str_to_user(row.first_day)} – ${frappe.datetime.str_to_user(row.last_day)}`;
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

function ask_opening(frm, row) {
	frappe.prompt(
		[
			{
				fieldname: "days",
				fieldtype: "Float",
				label: __("Calendar days already paid officially"),
				default: flt(row.opening_paid_days),
				reqd: 1,
			},
		],
		(values) => run(frm, "set_opening", { employee: row.employee, days: values.days }),
		row.employee_name || row.employee,
		__("Save")
	);
}

function ask_pay_days(frm, row) {
	frappe.prompt(
		[
			{
				fieldname: "days",
				fieldtype: "Int",
				label: __("Days to pay (up to {0})", [cint(row.unpaid_days)]),
				default: cint(row.pay_days),
				reqd: 1,
			},
		],
		(values) => run(frm, "set_pay_days", { employee: row.employee, days: values.days }),
		row.employee_name || row.employee,
		__("Save")
	);
}

// always one employee: the row is the only way money leaves this document
function ask_payment_date(frm, row) {
	frappe.prompt(
		[
			{
				fieldtype: "HTML",
				fieldname: "details",
				options: `<p>${__("{0} d from {1} to {2}: {3} accrued, {4} to the card.", [
					number(row.pay_days),
					frappe.datetime.str_to_user(row.first_day),
					frappe.datetime.str_to_user(row.last_day),
					money(row.gross),
					money(row.net),
				])}</p>`,
			},
			{
				fieldname: "posting_date",
				fieldtype: "Date",
				label: __("Payment Date"),
				default: frappe.datetime.get_today(),
				reqd: 1,
			},
		],
		(values) => run(frm, "pay", { posting_date: values.posting_date, employees: [row.employee] }),
		__("Pay {0}", [row.employee_name || row.employee]),
		__("Post")
	);
}

function show_receipt(row) {
	const link = (name) =>
		name
			? `<p><a href="/desk/journal-entry/${encodeURIComponent(name)}">${frappe.utils.escape_html(
					name
			  )}</a></p>`
			: "";

	frappe.msgprint({
		title: __("Paid {0}", [row.employee_name || row.employee]),
		message: `
			<p>${__("{0} d, {1}", [number(row.pay_days), period(row)])}</p>
			<p>${__("Paid on {0}", [frappe.datetime.str_to_user(row.paid_date)])}</p>
			${link(row.journal_entry_accrual)}${link(row.journal_entry_card)}${link(row.journal_entry_tax)}
		`,
	});
}
