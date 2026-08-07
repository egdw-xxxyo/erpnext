frappe.ui.form.on("Label Template", {
	refresh(frm) {
		frm.trigger("render_preview");
		frm.trigger("_load_source_field_options");
		frm.trigger("_add_template_help");

		if (frm.is_new()) return;

		frm.add_custom_button(
			__("Print"),
			() => {
				_print_with_preview(frm);
			},
			__("Actions")
		);

		frm.add_custom_button(
			__("Test Print"),
			() => {
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
							method: "erpnext.devices.doctype.label_printer.label_printer.test_print",
							args: {
								printer_name: values.printer,
								template_name: frm.doc.name,
							},
							freeze: true,
							freeze_message: __("Sending to printer..."),
							callback(r) {
								if (r.message && r.message.success) {
									frappe.show_alert({
										message: __("Label sent to printer!"),
										indicator: "green",
									});
								}
							},
						});
					},
				});
				d.show();
			},
			__("Actions")
		);
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
				.filter((f) => ["Small Text", "Long Text", "Text", "Code", "Data"].includes(f.fieldtype))
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

		const $fbtn =
			$(`<button class="btn btn-xs btn-default available-fields-btn" style="margin-top:4px;margin-left:4px;">
			<svg class="icon icon-sm" style="vertical-align:middle;margin-right:2px;">
				<use href="#icon-list"></use>
			</svg>
			${__("Available Fields")}
		</button>`);
		$fbtn.on("click", () => _show_available_fields(frm));
		$field.$wrapper.append($fbtn);
	},

	preview_data(frm) {
		frm.trigger("render_preview");
	},

	padding_top_mm(frm) {
		frm.trigger("render_preview");
	},
	padding_right_mm(frm) {
		frm.trigger("render_preview");
	},
	padding_bottom_mm(frm) {
		frm.trigger("render_preview");
	},
	padding_left_mm(frm) {
		frm.trigger("render_preview");
	},

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
			`<div class="text-muted text-center" style="padding:20px;">${__(
				"Select a Label Size to see preview"
			)}</div>`
		);
		return;
	}

	if (!frm.doc.html_template) {
		$wrapper.html(
			`<div class="text-muted text-center" style="padding:20px;">${__(
				"Enter template to see preview"
			)}</div>`
		);
		return;
	}

	frappe.call({
		method: "erpnext.devices.doctype.label_template.label_template.render_preview",
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
								<pre style="font-size:10px; max-height:200px; overflow:auto; margin-top:4px; background:var(--bg-color); padding:8px; border-radius:4px;">${frappe.utils.escape_html(
									data.html
								)}</pre>
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
		method: "erpnext.devices.doctype.label_template.label_template.render_preview",
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
		method: "erpnext.devices.doctype.label_template.label_template.get_template_reference",
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
				const desc = ex.description_uk ? `<p>${frappe.utils.escape_html(ex.description_uk)}</p>` : "";
				const notes = ex.notes
					? `<p style="font-style:italic;color:var(--text-muted);">${frappe.utils.escape_html(
							ex.notes
					  )}</p>`
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

const FIELD_PICKER_RENDERABLE_TYPES = [
	"Data",
	"Small Text",
	"Long Text",
	"Text",
	"Text Editor",
	"Code",
	"Link",
	"Dynamic Link",
	"Select",
	"Read Only",
	"Password",
	"Int",
	"Float",
	"Currency",
	"Percent",
	"Check",
	"Date",
	"Datetime",
	"Time",
	"Duration",
	"Barcode",
	"Attach",
	"Attach Image",
	"Color",
];

function _is_renderable_field(f) {
	return FIELD_PICKER_RENDERABLE_TYPES.includes(f.fieldtype);
}

async function _show_available_fields(frm) {
	const dt = frm.doc.reference_doctype;
	if (!dt) {
		_render_available_fields_dialog({ no_doctype: true, frm });
		return;
	}

	frappe.dom.freeze(__("Loading fields..."));
	try {
		await new Promise((res) => frappe.model.with_doctype(dt, res));
		const meta = frappe.get_meta(dt) || { fields: [] };

		const link_fields = (meta.fields || []).filter((f) => f.fieldtype === "Link" && f.options);
		const child_fields = (meta.fields || []).filter((f) => f.fieldtype === "Table" && f.options);

		const linked_metas = {};
		for (const lf of link_fields) {
			await new Promise((res) => frappe.model.with_doctype(lf.options, res));
			linked_metas[lf.fieldname] = {
				doctype: lf.options,
				meta: frappe.get_meta(lf.options) || { fields: [] },
			};
		}

		const child_metas = {};
		for (const cf of child_fields) {
			await new Promise((res) => frappe.model.with_doctype(cf.options, res));
			child_metas[cf.fieldname] = {
				doctype: cf.options,
				meta: frappe.get_meta(cf.options) || { fields: [] },
			};
		}

		let preview_keys = [];
		let preview_data = null;
		try {
			preview_data = JSON.parse(frm.doc.preview_data || "{}");
			const meta_fns = new Set((meta.fields || []).map((f) => f.fieldname));
			meta_fns.add("name");
			preview_keys = Object.keys(preview_data).filter((k) => !meta_fns.has(k));
		} catch (e) {
			preview_data = null;
		}

		let mapping_keys = [];
		try {
			const fm = JSON.parse(frm.doc.field_mapping || "{}");
			mapping_keys = Object.keys(fm).map((k) => ({ key: k, cfg: fm[k] }));
		} catch (e) {
			// ignore malformed data, fall back to defaults
		}

		let spec_keys = [];
		const item_code = preview_data && preview_data.item_code;
		if (item_code) {
			try {
				const r = await frappe.call({
					method: "erpnext.devices.doctype.label_template.label_template.get_available_spec_keys",
					args: { item_code },
				});
				spec_keys = r.message || [];
			} catch (e) {
				// ignore malformed data, fall back to defaults
			}
		}

		_render_available_fields_dialog({
			frm,
			dt,
			meta,
			linked_metas,
			child_metas,
			preview_keys,
			mapping_keys,
			spec_keys,
		});
	} finally {
		frappe.dom.unfreeze();
	}
}

function _field_row_html(expr, label, fieldtype) {
	const id = "fpx-" + Math.random().toString(36).slice(2, 9);
	const safe_expr = frappe.utils.escape_html(expr);
	const safe_label = frappe.utils.escape_html(label || "");
	const ft = fieldtype
		? `<span style="color:var(--text-muted);font-size:11px;margin-left:6px;">${frappe.utils.escape_html(
				fieldtype
		  )}</span>`
		: "";
	return `
		<div class="fpx-row" data-search="${frappe.utils.escape_html((expr + " " + label).toLowerCase())}"
			style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding:4px 8px;border-bottom:1px solid var(--border-color);">
			<div style="flex:1;min-width:0;">
				<code id="${id}" style="font-size:12px;">${safe_expr}</code>
				${safe_label ? `<span style="color:var(--text-muted);margin-left:8px;">${safe_label}</span>` : ""}
				${ft}
			</div>
			<button class="btn btn-xs btn-default" data-copy-target="${id}">${__("Copy")}</button>
		</div>`;
}

function _section_html(title, body_html, extra_html) {
	return `
		<div class="fpx-section" style="margin-top:14px;">
			<div style="font-weight:600;margin-bottom:4px;">${title}</div>
			${extra_html || ""}
			<div style="border:1px solid var(--border-color);border-radius:4px;">${body_html}</div>
		</div>`;
}

function _render_available_fields_dialog(ctx) {
	const d = new frappe.ui.Dialog({ title: __("Available Fields"), size: "large" });

	if (ctx.no_doctype) {
		d.$body.html(`<div style="padding:15px;">
			<p>${__("No Reference DocType is set on this template.")}</p>
			<p>${__(
				"For Raw Data templates, available keys are defined in the document(s) you pass at print time, or via Field Mapping."
			)}</p>
		</div>`);
		d.show();
		return;
	}

	const { frm, dt, meta, linked_metas, child_metas, preview_keys, mapping_keys, spec_keys } = ctx;

	const direct = (meta.fields || [])
		.filter(_is_renderable_field)
		.map((f) => _field_row_html(`{{ doc.${f.fieldname} }}`, f.label || "", f.fieldtype))
		.join("");

	let direct_section = _section_html(
		`${__(
			"Document fields"
		)} <span style="color:var(--text-muted);font-weight:400;">— ${frappe.utils.escape_html(dt)}</span>`,
		direct || `<div style="padding:8px;color:var(--text-muted);">${__("(none)")}</div>`
	);

	let child_section = "";
	const child_fns = Object.keys(child_metas || {});
	if (child_fns.length) {
		let body = "";
		for (const fn of child_fns) {
			const cm = child_metas[fn];
			const loop_id = "fpx-" + Math.random().toString(36).slice(2, 9);
			const loop = `{% for row in doc.${fn} %}\n  {{ row.fieldname }}\n{% endfor %}`;
			const inner = (cm.meta.fields || [])
				.filter(_is_renderable_field)
				.map((f) => _field_row_html(`{{ row.${f.fieldname} }}`, f.label || "", f.fieldtype))
				.join("");
			body += `
				<details style="border-bottom:1px solid var(--border-color);">
					<summary style="cursor:pointer;padding:6px 8px;">
						<code>doc.${fn}</code>
						<span style="color:var(--text-muted);margin-left:6px;">${__("Table")} → ${frappe.utils.escape_html(
				cm.doctype
			)}</span>
					</summary>
					<div style="padding:6px 8px;display:flex;align-items:center;gap:8px;">
						<pre id="${loop_id}" style="flex:1;margin:0;font-size:11px;background:var(--bg-color);padding:6px;border-radius:4px;">${frappe.utils.escape_html(
				loop
			)}</pre>
						<button class="btn btn-xs btn-default" data-copy-target="${loop_id}">${__("Copy loop")}</button>
					</div>
					${inner || `<div style="padding:6px 8px;color:var(--text-muted);">${__("(no renderable fields)")}</div>`}
				</details>`;
		}
		child_section = _section_html(__("Child tables"), body);
	}

	let linked_section = "";
	const link_fns = Object.keys(linked_metas || {});
	if (link_fns.length) {
		let body = "";
		for (const fn of link_fns) {
			const lm = linked_metas[fn];
			const var_id = "fpx-" + Math.random().toString(36).slice(2, 9);
			const setline = `{% set ${fn} = frappe.get_doc("${lm.doctype}", doc.${fn}) if doc.${fn} else None %}`;
			const inner = (lm.meta.fields || [])
				.filter(_is_renderable_field)
				.map((f) => _field_row_html(`{{ ${fn}.${f.fieldname} }}`, f.label || "", f.fieldtype))
				.join("");
			body += `
				<details style="border-bottom:1px solid var(--border-color);">
					<summary style="cursor:pointer;padding:6px 8px;">
						<code>doc.${fn}</code>
						<span style="color:var(--text-muted);margin-left:6px;">${__("Link")} → ${frappe.utils.escape_html(
				lm.doctype
			)}</span>
					</summary>
					<div style="padding:6px 8px;display:flex;align-items:center;gap:8px;">
						<pre id="${var_id}" style="flex:1;margin:0;font-size:11px;background:var(--bg-color);padding:6px;border-radius:4px;">${frappe.utils.escape_html(
				setline
			)}</pre>
						<button class="btn btn-xs btn-default" data-copy-target="${var_id}">${__("Copy")}</button>
					</div>
					${inner || `<div style="padding:6px 8px;color:var(--text-muted);">${__("(no renderable fields)")}</div>`}
				</details>`;
		}
		linked_section = _section_html(__("Linked documents (one-level)"), body);
	}

	let spec_section = "";
	if (spec_keys && spec_keys.length) {
		const body = spec_keys
			.map((s) => _field_row_html(`{{ doc.${s.key} }}`, s.param, "Spec param"))
			.join("");
		spec_section = _section_html(
			__("Spec params"),
			body,
			`<div style="color:var(--text-muted);font-size:11px;margin-bottom:4px;">${__(
				"Flattened from the item's specification."
			)}</div>`
		);
	}

	let mapping_section = "";
	if (mapping_keys && mapping_keys.length) {
		const body = mapping_keys
			.map((m) => {
				const src = m.cfg && m.cfg.source ? `${m.cfg.source}:${m.cfg.param || ""}` : "";
				return _field_row_html(`{{ doc.${m.key} }}`, src, "Field Mapping");
			})
			.join("");
		mapping_section = _section_html(__("Field Mapping aliases"), body);
	}

	let preview_section = "";
	if (preview_keys && preview_keys.length) {
		const body = preview_keys.map((k) => _field_row_html(`{{ doc.${k} }}`, "", "preview-only")).join("");
		preview_section = _section_html(
			__("Runtime / preview-only keys"),
			body,
			`<div style="color:var(--text-muted);font-size:11px;margin-bottom:4px;">${__(
				"Seen in preview_data but not in doctype meta. Make sure they exist at runtime."
			)}</div>`
		);
	}

	const helpers_section = _section_html(
		__("Helpers"),
		[
			_field_row_html(`{{ _("Hello") }}`, __("Translate"), ""),
			_field_row_html(`{{ frappe.utils.formatdate(doc.posting_date) }}`, __("Format date"), ""),
			_field_row_html(`<barcode type="code128" data="{{ doc.name }}" />`, __("Barcode tag"), ""),
			_field_row_html(`<attachment fieldname="image" />`, __("Attachment tag"), ""),
		].join("")
	);

	d.$body.html(`
		<div style="padding:0 15px 15px;font-size:13px;">
			<div style="position:sticky;top:0;background:var(--card-bg);padding:10px 0;z-index:1;border-bottom:1px solid var(--border-color);">
				<input type="text" class="form-control fpx-search" placeholder="${__("Filter fields...")}" />
			</div>
			${direct_section}
			${child_section}
			${linked_section}
			${spec_section}
			${mapping_section}
			${preview_section}
			${helpers_section}
		</div>
	`);

	d.$body.on("click", "[data-copy-target]", function () {
		const id = $(this).attr("data-copy-target");
		const text = document.getElementById(id)?.innerText || "";
		navigator.clipboard.writeText(text).then(() => {
			frappe.show_alert({ message: __("Copied"), indicator: "green" });
		});
	});

	d.$body.on("input", ".fpx-search", function () {
		const q = ($(this).val() || "").toLowerCase().trim();
		d.$body.find(".fpx-row").each(function () {
			const hay = $(this).attr("data-search") || "";
			$(this).toggle(!q || hay.indexOf(q) !== -1);
		});
	});

	d.show();
}
