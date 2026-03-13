frappe.ui.form.on("Label Template", {
	refresh(frm) {
		frm.trigger("render_preview");
		frm.trigger("_load_source_field_options");

		if (frm.is_new()) return;

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

	zpl_template(frm) {
		frm.trigger("render_preview");
	},

	html_template(frm) {
		frm.trigger("render_preview");
	},

	preview_data(frm) {
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
			`<div class="text-muted text-center" style="padding:20px;">${__("Select a Label Size to see preview")}</div>`
		);
		return;
	}

	let template = frm.doc.template_type === "EZPL" ? frm.doc.zpl_template : frm.doc.html_template;
	if (!template) {
		$wrapper.html(
			`<div class="text-muted text-center" style="padding:20px;">${__("Enter template to see preview")}</div>`
		);
		return;
	}

	frappe.call({
		method: "erpnext.manufacturing.doctype.label_template.label_template.render_preview",
		args: {
			template_type: frm.doc.template_type,
			zpl_template: frm.doc.zpl_template || "",
			html_template: frm.doc.html_template || "",
			preview_data: frm.doc.preview_data || "",
			label_size: frm.doc.label_size,
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

			if (data.type === "ezpl_parsed") {
				let canvas_id = "label-preview-canvas-" + Date.now();
				$wrapper.html(`
					<div class="label-preview-container" style="padding:10px;">
						${info_html}
						<div style="display:inline-block; border:1px solid var(--border-color); background:#fff; border-radius:4px; overflow:hidden;">
							<canvas id="${canvas_id}" width="${cw}" height="${ch}" style="width:${pw * scale}px; height:${ph * scale}px;"></canvas>
						</div>
						<div style="margin-top:8px;">
							<details>
								<summary style="cursor:pointer; font-size:11px; color:var(--text-muted);">${__("Show rendered EZPL")}</summary>
								<pre style="font-size:10px; max-height:200px; overflow:auto; margin-top:4px; background:var(--bg-color); padding:8px; border-radius:4px;">${frappe.utils.escape_html(data.rendered)}</pre>
							</details>
						</div>
					</div>
				`);

				let canvas = document.getElementById(canvas_id);
				if (canvas) {
					_draw_ezpl_preview(canvas, data.elements, data.width_mm, data.height_mm, scale, PX_PER_MM);
				}
			} else if (data.type === "html_image") {
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

function _draw_ezpl_preview(canvas, elements, width_mm, height_mm, scale, PX_PER_MM) {
	let ctx = canvas.getContext("2d");
	let w = canvas.width;
	let h = canvas.height;

	ctx.fillStyle = "#ffffff";
	ctx.fillRect(0, 0, w, h);

	ctx.strokeStyle = "#e0e0e0";
	ctx.lineWidth = 1;
	ctx.strokeRect(0, 0, w, h);

	let dot_to_px = (PX_PER_MM * scale) / 8;

	for (let el of elements) {
		let px = el.x * dot_to_px;
		let py = el.y * dot_to_px;

		if (el.type === "text") {
			let base_size = 10;
			let font_size = base_size * (el.v_mult || 1) * scale * 0.9;
			ctx.fillStyle = "#000000";
			ctx.font = `${font_size}px monospace`;
			ctx.textBaseline = "top";

			let char_w = font_size * 0.6 * (el.h_mult || 1) / (el.v_mult || 1);
			for (let i = 0; i < el.text.length; i++) {
				ctx.fillText(el.text[i], px + i * char_w, py);
			}
		} else if (el.type === "barcode") {
			_draw_code128(ctx, el.text || "", px, py, el, dot_to_px, scale);
		} else if (el.type === "qrcode") {
			let size = (el.module_size || 5) * dot_to_px * 20;
			ctx.fillStyle = "#000000";
			let cell = size / 10;
			for (let r = 0; r < 10; r++) {
				for (let c = 0; c < 10; c++) {
					if ((r < 3 && c < 3) || (r < 3 && c > 6) || (r > 6 && c < 3) || (r + c) % 3 === 0) {
						ctx.fillRect(px + c * cell, py + r * cell, cell, cell);
					}
				}
			}
		} else if (el.type === "line") {
			ctx.fillStyle = "#000000";
			ctx.fillRect(px, py, (el.length || 100) * dot_to_px, (el.thickness || 2) * dot_to_px);
		} else if (el.type === "box") {
			ctx.strokeStyle = "#000000";
			ctx.lineWidth = (el.thickness || 2) * dot_to_px;
			ctx.strokeRect(px, py, (el.box_w || 100) * dot_to_px, (el.box_h || 50) * dot_to_px);
		}
	}
}

// Code 128B encoder + renderer
const CODE128B_START = 104;
const CODE128B_STOP = [2, 3, 3, 1, 1, 1, 2];

const CODE128_PATTERNS = [
	[2,1,2,2,2,2],[2,2,2,1,2,2],[2,2,2,2,2,1],[1,2,1,2,2,3],[1,2,1,3,2,2],
	[1,3,1,2,2,2],[1,2,2,2,1,3],[1,2,2,3,1,2],[1,3,2,2,1,2],[2,2,1,2,1,3],
	[2,2,1,3,1,2],[2,3,1,2,1,2],[1,1,2,2,3,2],[1,2,2,1,3,2],[1,2,2,2,3,1],
	[1,1,3,2,2,2],[1,2,3,1,2,2],[1,2,3,2,2,1],[2,2,3,2,1,1],[2,2,1,1,3,2],
	[2,2,1,2,3,1],[2,1,3,2,1,2],[2,2,3,1,1,2],[3,1,2,1,3,1],[3,1,1,2,2,2],
	[3,2,1,1,2,2],[3,2,1,2,2,1],[3,1,2,2,1,2],[3,2,2,1,1,2],[3,2,2,2,1,1],
	[2,1,2,1,2,3],[2,1,2,3,2,1],[2,3,2,1,2,1],[1,1,1,3,2,3],[1,3,1,1,2,3],
	[1,3,1,3,2,1],[1,1,2,3,1,3],[1,3,2,1,1,3],[1,3,2,3,1,1],[2,1,1,3,1,3],
	[2,3,1,1,1,3],[2,3,1,3,1,1],[1,1,2,1,3,3],[1,1,2,3,3,1],[1,3,2,1,3,1],
	[1,1,3,1,2,3],[1,1,3,3,2,1],[1,3,3,1,2,1],[3,1,3,1,2,1],[2,1,1,3,3,1],
	[2,3,1,1,3,1],[2,1,3,1,1,3],[2,1,3,3,1,1],[2,1,3,1,3,1],[3,1,1,1,2,3],
	[3,1,1,3,2,1],[3,3,1,1,2,1],[3,1,2,1,1,3],[3,1,2,3,1,1],[3,3,2,1,1,1],
	[3,1,4,1,1,1],[2,2,1,4,1,1],[4,3,1,1,1,1],[1,1,1,2,2,4],[1,1,1,4,2,2],
	[1,2,1,1,2,4],[1,2,1,4,2,1],[1,4,1,1,2,2],[1,4,1,2,2,1],[1,1,2,2,1,4],
	[1,1,2,4,1,2],[1,2,2,1,1,4],[1,2,2,4,1,1],[1,4,2,1,1,2],[1,4,2,2,1,1],
	[2,4,1,2,1,1],[2,2,1,1,1,4],[4,1,3,1,1,1],[2,4,1,1,1,2],[1,3,4,1,1,1],
	[1,1,1,2,4,2],[1,2,1,1,4,2],[1,2,1,2,4,1],[1,1,4,2,1,2],[1,2,4,1,1,2],
	[1,2,4,2,1,1],[4,1,1,2,1,2],[4,2,1,1,1,2],[4,2,1,2,1,1],[2,1,2,1,4,1],
	[2,1,4,1,2,1],[4,1,2,1,2,1],[1,1,1,1,4,3],[1,1,1,3,4,1],[1,3,1,1,4,1],
	[1,1,4,1,1,3],[1,1,4,3,1,1],[4,1,1,1,1,3],[4,1,1,3,1,1],[1,1,3,1,4,1],
	[1,1,4,1,3,1],[3,1,1,1,4,1],[4,1,1,1,3,1],[2,1,1,4,1,2],[2,1,1,2,1,4],
	[2,1,1,2,3,2],[2,3,3,1,1,1,2],
];

function _encode_code128b(text) {
	let codes = [CODE128B_START];
	let checksum = CODE128B_START;
	for (let i = 0; i < text.length; i++) {
		let val = text.charCodeAt(i) - 32;
		if (val < 0 || val > 94) val = 0;
		codes.push(val);
		checksum += val * (i + 1);
	}
	codes.push(checksum % 103);
	return codes;
}

function _draw_code128(ctx, text, px, py, el, dot_to_px, scale) {
	let codes = _encode_code128b(text);
	let narrow = (el.narrow || 2) * dot_to_px;
	let bar_h = (el.height || 80) * dot_to_px;

	ctx.fillStyle = "#000000";
	let bx = px;

	for (let ci = 0; ci < codes.length; ci++) {
		let pattern = CODE128_PATTERNS[codes[ci]];
		if (!pattern) continue;
		for (let pi = 0; pi < pattern.length; pi++) {
			let w = pattern[pi] * narrow;
			if (pi % 2 === 0) {
				ctx.fillRect(bx, py, w, bar_h);
			}
			bx += w;
		}
	}

	// stop pattern
	for (let pi = 0; pi < CODE128B_STOP.length; pi++) {
		let w = CODE128B_STOP[pi] * narrow;
		if (pi % 2 === 0) {
			ctx.fillRect(bx, py, w, bar_h);
		}
		bx += w;
	}

	let label_size = 7 * scale;
	ctx.font = `${label_size}px monospace`;
	ctx.textBaseline = "top";
	ctx.fillStyle = "#000000";
	let text_w = ctx.measureText(text).width;
	let barcode_w = bx - px;
	let text_x = px + (barcode_w - text_w) / 2;
	ctx.fillText(text, text_x, py + bar_h + 1 * scale);
}
