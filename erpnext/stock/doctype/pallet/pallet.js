frappe.ui.form.on("Pallet", {
	refresh(frm) {
		setup_pallet_print_labels(frm);
		render_pallet_packages(frm);
	},
});

function render_pallet_packages(frm) {
	const wrapper = frm.fields_dict.packages_html && frm.fields_dict.packages_html.$wrapper;
	if (!wrapper) return;
	if (frm.is_new()) {
		wrapper.empty();
		return;
	}
	erpnext.utils.render_package_list_table({
		wrapper,
		filters: { pallet: frm.doc.name },
		empty_message: __("No packages linked to this Pallet."),
	});
}

function setup_pallet_print_labels(frm) {
	if (frm.is_new()) return;
	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Label Template",
			filters: { reference_doctype: "Pallet" },
			fields: ["name"],
		},
		callback: function (r) {
			let templates = (r.message || []).map((t) => ({ label_template: t.name }));
			if (!templates.length) return;
			frm.page.add_menu_item(__("Print Labels"), function () {
				erpnext.utils.open_simple_label_print_dialog({
					doctype: "Pallet",
					doc_name: frm.doc.name,
					label_templates: templates,
				});
			});
		},
	});
}
