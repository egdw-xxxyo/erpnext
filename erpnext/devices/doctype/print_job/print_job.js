frappe.ui.form.on("Print Job", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.status === "Queued" || frm.doc.status === "Failed") {
			frm.add_custom_button(__("Print Now"), () => {
				let send = () => {
					frappe.call({
						method: "erpnext.manufacturing.doctype.label_printer.label_printer.print_label",
						args: { print_job_name: frm.doc.name, label_printer: frm.doc.label_printer },
						freeze: true,
						freeze_message: __("Sending to printer..."),
						callback(r) {
							if (r.message && r.message.success) {
								frappe.show_alert({ message: __("Label printed!"), indicator: "green" });
							}
							frm.reload_doc();
						},
					});
				};
				if (frm.is_dirty()) {
					frm.save().then(send);
				} else {
					send();
				}
			}).addClass("btn-primary");
		}

		if (frm.doc.status === "Queued") {
			frm.add_custom_button(__("Cancel"), () => {
				frappe.call({
					method: "erpnext.manufacturing.doctype.label_printer.label_printer.cancel_print_job",
					args: { print_job_name: frm.doc.name },
					callback() {
						frm.reload_doc();
					},
				});
			});
		}

		_render_job_preview(frm);
	},
});

function _render_job_preview(frm) {
	let $wrapper = frm.fields_dict.preview_html && frm.fields_dict.preview_html.$wrapper;
	if (!$wrapper) return;

	if (!frm.doc.raw_data) {
		$wrapper.html(`<div class="text-muted" style="padding:12px;">${__("No data to preview")}</div>`);
		return;
	}

	$wrapper.html(`<div class="text-muted" style="padding:12px;">${__("Rendering preview...")}</div>`);

	frappe.call({
		method: "erpnext.manufacturing.doctype.label_template.label_template.render_job_preview",
		args: { print_job_name: frm.doc.name },
		callback(r) {
			if (!r.message) {
				$wrapper.html(`<div class="text-muted" style="padding:12px;">${__("Preview not available")}</div>`);
				return;
			}
			let data = r.message;
			if (data.type !== "html_image") {
				$wrapper.html(`<div class="text-muted" style="padding:12px;">${__("Preview not available for this template type")}</div>`);
				return;
			}
			let PX_PER_MM = 3.78;
			let scale = 3;
			let cw = Math.round(data.width_mm * PX_PER_MM) * scale;
			let ch = Math.round(data.height_mm * PX_PER_MM) * scale;
			$wrapper.html(`
				<div style="padding:10px;">
					<div style="font-size:11px;color:var(--text-muted);margin-bottom:6px;">
						${data.width_mm} × ${data.height_mm} mm
					</div>
					<div style="display:inline-block; border:1px solid var(--border-color); background:#fff; border-radius:4px; overflow:hidden;">
						<img src="data:image/png;base64,${data.image_base64}"
							style="width:${cw}px; height:${ch}px; display:block; image-rendering:pixelated;" />
					</div>
				</div>
			`);
		},
	});
}
