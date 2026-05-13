frappe.ui.form.on("Scanner", {
	refresh(frm) {
		if (frm.is_new()) return;

		const qr_svg = frm.doc.__onload?.qr_svg;
		if (qr_svg) {
			frm.fields_dict.scanner_key_html.$wrapper.html(`
				<div style="text-align: center; padding: 10px 0;">
					${qr_svg}
				</div>
			`);
		}

		frm.fields_dict.config_barcodes_html.$wrapper.html(
			`<div class="text-muted text-center" style="padding: 20px;">${__("Loading...")}</div>`
		);

		const endpoint_url = `${window.location.origin}/api/method/erpnext.manufacturing.doctype.scanner.scanner_api.handle_scan`;

		frappe.call({
			method: "erpnext.manufacturing.doctype.scanner.scanner.get_config_barcodes",
			args: { scanner_name: frm.doc.name, endpoint_url: endpoint_url },
			callback: (r) => {
				if (!r.message) return;
				const d = r.message;

				frm.fields_dict.config_barcodes_html.$wrapper.html(`
					<p class="text-muted" style="font-size: 12px;">
						${__("Scan this QR code with the physical scanner to configure both the server URL and API key in one step.")}
					</p>
					<div style="display: flex; justify-content: center;">
						<div style="min-width: 280px; max-width: 400px; border: 1px solid var(--border-color);
							border-radius: 4px; padding: 15px; text-align: center;">
							<div style="font-weight: 600; margin-bottom: 8px;">CFG-SCANNER</div>
							<div>${d.config_qr}</div>
							<div class="text-muted" style="font-size: 10px; margin-top: 8px; word-break: break-all;">
								${d.endpoint_url}
							</div>
							<div style="font-family: monospace; font-size: 14px; margin-top: 6px;">
								${d.api_key}
							</div>
						</div>
					</div>
				`);
			},
		});
	},

	regenerate_api_key(frm) {
		if (frm.is_new()) {
			frappe.msgprint(__("Please save the document first."));
			return;
		}
		frappe.confirm(
			__("Regenerate API key? The old key will stop working immediately."),
			function () {
				frappe.call({
					method: "erpnext.manufacturing.doctype.scanner.scanner.regenerate_api_key",
					args: { scanner_name: frm.doc.name },
					callback: function (r) {
						if (!r.message) return;
						frm.set_value("api_key", r.message.api_key);
						frm.fields_dict.scanner_key_html.$wrapper.html(`
							<div style="text-align: center; padding: 10px 0;">
								${r.message.qr_svg}
							</div>
						`);
						frm.refresh_fields();
						frm.reload_doc();
					},
				});
			}
		);
	},
});
