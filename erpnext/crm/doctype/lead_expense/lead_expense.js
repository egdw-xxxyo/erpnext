// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

const STOCK_ENTRY_REOPEN_STATUSES = ["Awaiting Warehouse", "Cancelled", "Deleted"];

frappe.ui.form.on("Lead Expense", {
	setup: function (frm) {
		frm.set_query("expense_type", () => ({ filters: { disabled: 0 } }));
		frm.set_query("item_code", "items", () => ({ filters: { is_stock_item: 1, disabled: 0 } }));
	},

	onload: function (frm) {
		if (frm.is_new() && !frm.doc.company) {
			frm.set_value("company", frappe.defaults.get_user_default("Company"));
		}
	},

	refresh: function (frm) {
		if (can_make_stock_entry(frm)) {
			frm.add_custom_button(__("Create Stock Entry"), () => make_stock_entry(frm)).addClass(
				"btn-primary"
			);
		}
	},
});

function can_make_stock_entry(frm) {
	return (
		frm.doc.docstatus === 1 &&
		frm.doc.expense_kind === "Materials" &&
		frappe.user.has_role("Stock Manager") &&
		STOCK_ENTRY_REOPEN_STATUSES.includes(frm.doc.stock_entry_status)
	);
}

function make_stock_entry(frm) {
	frappe.prompt(
		{
			fieldname: "warehouse",
			fieldtype: "Link",
			options: "Warehouse",
			label: __("Source Warehouse"),
			reqd: 1,
			get_query: () => ({ filters: { company: frm.doc.company, is_group: 0, disabled: 0 } }),
		},
		({ warehouse }) =>
			frappe
				.call({
					method: "erpnext.crm.doctype.lead_expense.lead_expense.make_stock_entry",
					args: { expense: frm.doc.name, warehouse },
					freeze: true,
				})
				.then(({ message }) => frappe.set_route("Form", "Stock Entry", message)),
		__("Create Stock Entry"),
		__("Create")
	);
}
