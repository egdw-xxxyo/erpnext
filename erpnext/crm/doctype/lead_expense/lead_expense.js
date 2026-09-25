// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Lead Expense", {
	setup: function (frm) {
		frm.custom_make_buttons = { "Stock Entry": "Create Stock Entry" };
		frm.set_query("expense_type", () => ({ filters: { disabled: 0 } }));
		frm.set_query("item_code", "items", () => ({ filters: { is_stock_item: 1, disabled: 0 } }));
	},

	onload: function (frm) {
		if (frm.is_new() && !frm.doc.company) {
			frm.set_value("company", frappe.defaults.get_user_default("Company"));
		}
	},

	refresh: function (frm) {
		if (!frappe.user.has_role("Stock Manager")) return;

		const { can_issue, can_close } = frm.doc.__onload || {};
		if (can_issue) {
			frm.add_custom_button(__("Create Stock Entry"), () => make_stock_entry(frm)).addClass(
				"btn-primary"
			);
		}
		if (can_close) {
			frm.add_custom_button(__("Close Remainder"), () => close_remainder(frm));
		}
	},
});

function close_remainder(frm) {
	frappe.confirm(
		__("Close the remainder of this expense? No more stock entries can be created for it."),
		() =>
			frappe
				.call({
					method: "erpnext.crm.doctype.lead_expense.lead_expense.close_remainder",
					args: { expense: frm.doc.name },
					freeze: true,
				})
				.then(() => frm.reload_doc())
	);
}

function make_stock_entry(frm) {
	frappe.model.open_mapped_doc({
		method: "erpnext.crm.doctype.lead_expense.lead_expense.make_stock_entry",
		frm,
	});
}
