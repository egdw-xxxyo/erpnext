frappe.ui.form.on("Helper Guide", {
	setup(frm) {
		frm.set_query("target_doctype", () => ({ filters: { istable: 0 } }));
	},
});
