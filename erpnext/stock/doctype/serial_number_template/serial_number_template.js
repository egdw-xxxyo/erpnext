// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Serial Number Template", {
	validate(frm) {
		frm.trigger("rebuild_preview");
	},
});

frappe.ui.form.on("Serial Number Template Component", {
	component_type(frm) {
		frm.trigger("rebuild_preview");
	},
	value(frm) {
		frm.trigger("rebuild_preview");
	},
	components_remove(frm) {
		frm.trigger("rebuild_preview");
	},
});
