// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Workplace", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Open Portal"), () => {
				frappe.set_route("workplace-portal", { workplace: frm.doc.name });
			}, __("View"));
		}
	},
});
