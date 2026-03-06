// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Serial Number Template", {
	validate(frm) {
		frm.trigger("rebuild_preview");
	},
});

frappe.ui.form.on("Serial Number Template Component", {
	component_type(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.component_type !== "Item Attribute") {
			frappe.model.set_value(cdt, cdn, "attribute_link", "");
		}
		frm.trigger("rebuild_preview");
	},
	attribute_link(frm) {
		frm.trigger("rebuild_preview");
	},
	value(frm) {
		frm.trigger("rebuild_preview");
	},
	components_remove(frm) {
		frm.trigger("rebuild_preview");
	},
});
