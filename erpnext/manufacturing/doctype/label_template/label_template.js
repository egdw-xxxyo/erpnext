frappe.ui.form.on("Label Template", {
	refresh(frm) {
		frm.trigger("render_preview");
		frm.trigger("_load_source_field_options");
		frm.trigger("_add_template_help");

		if (frm.is_new()) return;

		frm.add_custom_button(__("Print"), () => {
			_print_with_preview(frm);
		}, __("Actions"));

		frm.add_custom_button(__("Test Print"), () => {
			let d = new frappe.ui.Dialog({
				title: __("Test Print"),
				fields: [
					{
						fieldname: "printer",
						fieldtype: "Link",
						label: __("Printer"),
						options: "Label Printer",
						reqd: 1,
						get_query() {
							return { filters: { is_enabled: 1 } };
						},
					},
				],
				primary_action_label: __("Print"),
				primary_action(values) {
					d.hide();
					frappe.call({
						method: "erpnext.manufacturing.doctype.label_printer.label_printer.test_print",
						args: {
							printer_name: values.printer,
							template_name: frm.doc.name,
						},
						freeze: true,
						freeze_message: __("Sending to printer..."),
						callback(r) {
							if (r.message && r.message.success) {
								frappe.show_alert({ message: __("Label sent to printer!"), indicator: "green" });
							}
						},
					});
				},
			});
			d.show();
		}, __("Actions"));
	},

	reference_doctype(frm) {
		frm.set_value("source_field", "");
		frm.trigger("_load_source_field_options");
	},

	_load_source_field_options(frm) {
		const dt = frm.doc.reference_doctype;
		if (!dt) {
			frm.set_df_property("source_field", "options", [""]);
			return;
		}
		frappe.model.with_doctype(dt, () => {
			const fields = frappe.get_meta(dt).fields || [];
			const opts = fields
				.filter(
					(f) =>
						["Small Text", "Long Text", "Text", "Code", "Data"].includes(f.fieldtype)
				)
				.map((f) => ({
					label: `${f.label} (${f.fieldname})`,
					value: f.fieldname,
				}));
			opts.unshift({ label: "", value: "" });
			frm.set_df_property("source_field", "options", opts);
		});
	},

	template_type(frm) {
		frm.trigger("render_preview");
	},

	label_size(frm) {
		frm.trigger("render_preview");
	},

	html_template(frm) {
		frm.trigger("render_preview");
	},

	after_save(frm) {
		frm.trigger("_add_template_help");
	},

	_add_template_help(frm) {
		const $field = frm.fields_dict["html_template"];
		if (!$field || !$field.$wrapper) return;

		if ($field.$wrapper.find(".template-help-btn").length) return;

		const $btn = $(`<button class="btn btn-xs btn-default template-help-btn" style="margin-top:4px;">
			<svg class="icon icon-sm" style="vertical-align:middle;margin-right:2px;">
				<use href="#icon-help"></use>
			</svg>
			${__("Template Reference")}
		</button>`);

		$btn.on("click", () => _show_template_help(frm));
		$field.$wrapper.append($btn);
	},

	preview_data(frm) {
		frm.trigger("render_preview");
	},

	padding_top_mm(frm) { frm.trigger("render_preview"); },
	padding_right_mm(frm) { frm.trigger("render_preview"); },
	padding_bottom_mm(frm) { frm.trigger("render_preview"); },
	padding_left_mm(frm) { frm.trigger("render_preview"); },

	render_preview(frm) {
		if (frm._preview_timer) clearTimeout(frm._preview_timer);
		frm._preview_timer = setTimeout(() => _do_render_preview(frm), 500);
	},
});

function _do_render_preview(frm) {
	let $wrapper = frm.fields_dict.preview_html && frm.fields_dict.preview_html.$wrapper;
	if (!$wrapper) return;

	if (!frm.doc.label_size) {
		$wrapper.html(
			`<div class="text-muted text-center" style="padding:20px;">${__("Select a Label Size to see preview")}</div>`
		);
		return;
	}

	if (!frm.doc.html_template) {
		$wrapper.html(
			`<div class="text-muted text-center" style="padding:20px;">${__("Enter template to see preview")}</div>`
		);
		return;
	}

	frappe.call({
		method: "erpnext.manufacturing.doctype.label_template.label_template.render_preview",
		args: {
			html_template: frm.doc.html_template || "",
			preview_data: frm.doc.preview_data || "",
			label_size: frm.doc.label_size,
			padding_top_mm: frm.doc.padding_top_mm || 0,
			padding_right_mm: frm.doc.padding_right_mm || 0,
			padding_bottom_mm: frm.doc.padding_bottom_mm || 0,
			padding_left_mm: frm.doc.padding_left_mm || 0,
		},
		callback(r) {
			if (!r.message) return;
			let data = r.message;

			let PX_PER_MM = 3.78;
			let pw = Math.round(data.width_mm * PX_PER_MM);
			let ph = Math.round(data.height_mm * PX_PER_MM);

			let scale = 3;
			let cw = pw * scale;
			let ch = ph * scale;

			let info_html = `<div class="label-preview-info" style="font-size:11px;color:var(--text-muted);margin-bottom:6px;">
				${data.width_mm} × ${data.height_mm} mm &nbsp;|&nbsp; ${data.width_dots} × ${data.height_dots} dots @ ${data.dpi} DPI
			</div>`;

			if (data.type === "html_image") {
				$wrapper.html(`
					<div class="label-preview-container" style="padding:10px;">
						${info_html}
						<div style="display:inline-block; border:1px solid var(--border-color); background:#fff; border-radius:4px; overflow:hidden;">
							<img src="data:image/png;base64,${data.image_base64}"
								style="width:${cw}px; height:${ch}px; display:block; image-rendering:pixelated;" />
						</div>
						<div style="margin-top:8px;">
							<details>
								<summary style="cursor:pointer; font-size:11px; color:var(--text-muted);">${__("Show HTML source")}</summary>
								<pre style="font-size:10px; max-height:200px; overflow:auto; margin-top:4px; background:var(--bg-color); padding:8px; border-radius:4px;">${frappe.utils.escape_html(data.html)}</pre>
							</details>
						</div>
					</div>
				`);
			}
		},
	});
}

function _print_with_preview(frm) {
	frappe.call({
		method: "erpnext.manufacturing.doctype.label_template.label_template.render_preview",
		args: {
			html_template: frm.doc.html_template || "",
			field_mapping: frm.doc.field_mapping || "",
			preview_data: frm.doc.preview_data || "",
			label_size: frm.doc.label_size,
			padding_top_mm: frm.doc.padding_top_mm || 0,
			padding_right_mm: frm.doc.padding_right_mm || 0,
			padding_bottom_mm: frm.doc.padding_bottom_mm || 0,
			padding_left_mm: frm.doc.padding_left_mm || 0,
		},
		freeze: true,
		freeze_message: __("Rendering..."),
		callback(r) {
			if (!r.message) {
				frappe.msgprint(__("Nothing to print. Set a Label Size and template."));
				return;
			}
			let data = r.message;
			let PX_PER_MM = 3.78;
			let pw = Math.round(data.width_mm * PX_PER_MM);
			let ph = Math.round(data.height_mm * PX_PER_MM);

			let body_content = `<img src="data:image/png;base64,${data.image_base64}" style="width:${pw}px;height:${ph}px;display:block;" />`;

			let win = window.open("", "_blank");
			win.document.write(`<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>${frm.doc.template_name}</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: #fff; }
@media print {
  @page { size: ${data.width_mm}mm ${data.height_mm}mm; margin: 0; }
  body { width: ${data.width_mm}mm; height: ${data.height_mm}mm; overflow: hidden; }
}
</style>
</head>
<body>${body_content}</body>
</html>`);
			win.document.close();
			win.onload = () => win.print();
		},
	});
}

function _show_template_help(frm) {
	_show_html_template_help(frm);
}

function _show_html_template_help(frm) {
	frappe.call({
		method: "erpnext.manufacturing.doctype.label_template.label_template.get_template_reference",
		freeze: true,
		callback(r) {
			if (!r.message) return;
			_render_html_help_dialog(r.message);
		},
	});
}

function _render_html_help_dialog(data) {
	const reference_html = data.reference_html || "";
	const examples = data.examples || [];

	const examples_by_category = {};
	for (const ex of examples) {
		(examples_by_category[ex.category] = examples_by_category[ex.category] || []).push(ex);
	}

	let examples_html = "";
	if (examples.length) {
		examples_html += `<h2>${__("Приклади")}</h2>`;
		for (const cat of Object.keys(examples_by_category)) {
			examples_html += `<h3>${frappe.utils.escape_html(cat)}</h3>`;
			for (const ex of examples_by_category[cat]) {
				const title = frappe.utils.escape_html(ex.title);
				const desc = ex.description_uk
					? `<p>${frappe.utils.escape_html(ex.description_uk)}</p>`
					: "";
				const notes = ex.notes
					? `<p style="font-style:italic;color:var(--text-muted);">${frappe.utils.escape_html(ex.notes)}</p>`
					: "";
				const snippet_id = "snippet-" + Math.random().toString(36).slice(2, 9);
				const snippet = frappe.utils.escape_html(ex.html_snippet || "");
				examples_html += `
					<div style="margin-bottom:16px;border:1px solid var(--border-color);border-radius:4px;padding:10px;">
						<div style="display:flex;justify-content:space-between;align-items:center;">
							<strong>${title}</strong>
							<button class="btn btn-xs btn-default" data-copy-target="${snippet_id}">
								${__("Copy")}
							</button>
						</div>
						${desc}
						<pre id="${snippet_id}" style="font-size:11px;background:var(--bg-color);padding:8px;border-radius:4px;margin:8px 0 0;max-height:240px;overflow:auto;">${snippet}</pre>
						${notes}
					</div>
				`;
			}
		}
	}

	const d = new frappe.ui.Dialog({ title: __("Template Reference"), size: "large" });
	d.$body.html(`
		<div style="padding:0 15px 15px;font-size:13px;line-height:1.55;">
			${reference_html}
			${examples_html}
		</div>
	`);
	d.$body.on("click", "[data-copy-target]", function () {
		const id = $(this).attr("data-copy-target");
		const text = document.getElementById(id)?.innerText || "";
		navigator.clipboard.writeText(text).then(() => {
			frappe.show_alert({ message: __("Copied"), indicator: "green" });
		});
	});
	d.show();
}

