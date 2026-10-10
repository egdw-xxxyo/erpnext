frappe.ui.form.on("Consumption Recipe", {
	refresh(frm) {
		if (!frm.is_new() && (frm.doc.items || []).length) {
			frm.trigger("calculate");
		}
	},

	calculate(frm) {
		const wrapper = frm.fields_dict.preview_html.$wrapper;
		const items = (frm.doc.items || []).filter((row) => row.item_code);
		if (!items.length) {
			wrapper.html("");
			return;
		}

		erpnext.consumption.show(wrapper, { items: items, values: frm.doc.preview_values || "1" });
	},
});
