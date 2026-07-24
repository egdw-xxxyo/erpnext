// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Scanner Command", {
	refresh: function (frm) {
		setup_barcode(frm);
		setup_print_labels(frm);
	},

	barcode_id: function (frm) {
		frm._barcode_field && frm._barcode_field.refresh();
	},
});

function setup_barcode(frm) {
	if (!frm.fields_dict.barcode_id) return;

	const $wrapper = frm.fields_dict.barcode_id.$wrapper;
	$wrapper.find(".btn-generate-barcode").remove();

	if (!frm.doc.barcode_id) {
		const $btn = $(`<button class="btn btn-xs btn-default btn-generate-barcode" style="margin-top: 6px;">
			${__("Generate Barcode")}
		</button>`);
		$wrapper.find(".help-box").before($btn);
		$btn.on("click", () => {
			const hash = Array.from(crypto.getRandomValues(new Uint8Array(4)))
				.map((b) => b.toString(16).padStart(2, "0"))
				.join("")
				.toUpperCase();
			frm.set_value("barcode_id", `CMD-${hash}`);
			frm.dirty();
		});
	}

	if (!frm._barcode_field) {
		frm._barcode_field = new erpnext.BarcodeField({
			frm,
			fieldname: "barcode_id",
			barcode_type: "CODE128",
			format: "CODE128",
		});
	}
	frm._barcode_field.refresh();
}

function setup_print_labels(frm) {
	if (frm.is_new()) return;
	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Label Template",
			filters: { reference_doctype: "Scanner Command" },
			fields: ["name"],
		},
		callback: function (r) {
			let templates = (r.message || []).map((t) => ({ label_template: t.name }));
			if (!templates.length) return;
			frm.page.add_menu_item(__("Print Labels"), function () {
				erpnext.utils.open_simple_label_print_dialog({
					doctype: "Scanner Command",
					doc_name: frm.doc.name,
					label_templates: templates,
				});
			});
		},
	});
}
