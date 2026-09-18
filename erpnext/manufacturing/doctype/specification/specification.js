frappe.ui.form.on("Specification", {
	setup: function (frm) {
		frm.set_query("specification", "components", function (doc, cdt, cdn) {
			return { filters: { name: ["!=", doc.name], disabled: 0 } };
		});
	},

	refresh: function (frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Items"), function () {
			frappe.set_route("List", "Item", { specification: frm.doc.name });
		});
	},
});
