frappe.ui.form.on("Workplace", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(
				__("Open Portal"),
				() => {
					frappe.set_route("workplace-portal", { workplace: frm.doc.name });
				},
				__("View")
			);
		}
		setup_barcode_generate(frm);
		if (!frm._barcode_field) {
			frm._barcode_field = new erpnext.BarcodeField({
				frm,
				fieldname: "barcode",
				barcode_type: "CODE128",
				format: "CODE128",
			});
		}
		frm._barcode_field.refresh();
		render_workplace_script_link(frm);
		setup_workplace_print_labels(frm);
	},
	barcode(frm) {
		frm._barcode_field && frm._barcode_field.refresh();
	},
});

function setup_workplace_print_labels(frm) {
	if (frm.is_new()) return;
	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Label Template",
			filters: { reference_doctype: "Workplace" },
			fields: ["name"],
		},
		callback: function (r) {
			let templates = (r.message || []).map((t) => ({ label_template: t.name }));
			if (!templates.length) return;
			frm.page.add_menu_item(__("Print Labels"), function () {
				erpnext.utils.open_simple_label_print_dialog({
					doctype: "Workplace",
					doc_name: frm.doc.name,
					label_templates: templates,
				});
			});
		},
	});
}

function render_workplace_script_link(frm) {
	if (frm.is_new()) return;

	frappe.db.get_value("Workplace Script", { workplace: frm.doc.name, is_active: 1 }, "name").then((r) => {
		const name = r?.message?.name;
		if (name && frm.doc.workplace_script !== name) {
			frm.set_value("workplace_script", name);
		} else if (!name && frm.doc.workplace_script) {
			frm.set_value("workplace_script", null);
		}
	});
}

function setup_barcode_generate(frm) {
	const $wrapper = frm.fields_dict.barcode.$wrapper;
	$wrapper.find(".btn-generate-barcode").remove();

	if (frm.doc.barcode) return;

	const $btn = $(`<button class="btn btn-xs btn-default btn-generate-barcode" style="margin-top: 6px;">
		${__("Generate Barcode")}
	</button>`);

	$wrapper.find(".help-box").before($btn);

	$btn.on("click", () => {
		const hash = Array.from(crypto.getRandomValues(new Uint8Array(4)))
			.map((b) => b.toString(16).padStart(2, "0"))
			.join("")
			.toUpperCase();
		frm.set_value("barcode", `WP-${hash}`);
		frm.dirty();
	});
}
