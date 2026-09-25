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
		render_production_lines(frm);
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

function render_production_lines(frm) {
	if (frm.is_new()) return;

	// The binding lives on `Production Line.workplaces`; show it here read-only so the bench
	// tells you which line it runs, without a second field to keep in sync.
	frappe.call({
		method: "erpnext.manufacturing.doctype.production_line.production_line.lines_for_workplace",
		args: { workplace: frm.doc.name },
		callback(r) {
			const lines = r.message || [];
			if (!lines.length) return;
			lines.forEach((line) => {
				frm.dashboard.add_indicator(
					__("Production Line: {0}", [line.line_name || line.name]),
					line.enabled ? "blue" : "gray"
				);
			});
		},
	});
}

function render_workplace_script_link(frm) {
	if (frm.is_new()) return;

	frappe.call({
		method: "erpnext.devices.doctype.workplace_script.workplace_script.script_for_workplace",
		args: { workplace: frm.doc.name, include_default: 0 },
		callback(r) {
			const name = r.message || null;
			if (name !== (frm.doc.workplace_script || null)) {
				frm.set_value("workplace_script", name);
			}
		},
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
