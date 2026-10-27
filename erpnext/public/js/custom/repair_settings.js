frappe.ui.form.on("Repair Settings", {
	setup(frm) {
		frm.set_query("warehouse", "warehouses", (_doc, cdt, cdn) => ({
			filters: { company: locals[cdt][cdn].company || "", is_group: 0, disabled: 0 },
		}));
	},
});
frappe.ui.form.on("Repair Company Warehouse", {
	company(_frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "warehouse", null);
	},
});
