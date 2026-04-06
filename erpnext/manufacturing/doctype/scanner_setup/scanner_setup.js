frappe.ui.form.on("Scanner Setup", {
	regenerate_api_key(frm) {
		if (frm.is_new()) {
			frappe.msgprint(__("Please save the document first."));
			return;
		}
		frappe.confirm(
			__(
				"Are you sure you want to regenerate the API key? The old key will stop working immediately."
			),
			function () {
				frappe.call({
					method: "erpnext.manufacturing.doctype.scanner_setup.scanner_setup.regenerate_api_key",
					args: { scanner_name: frm.doc.name },
					callback: function (r) {
						if (!r.message) return;
						const { preview, key, qr_svg } = r.message;

						frm.set_value("api_key_preview", preview);
						frm.refresh_fields();

						const d = new frappe.ui.Dialog({
							title: __("API Key Regenerated"),
							indicator: "green",
							size: "small",
						});

						d.$body.html(`
							<div style="text-align: center; padding: 15px;">
								<div style="margin-bottom: 15px;">
									${qr_svg}
								</div>
								<p style="font-size: 11px; word-break: break-all; font-family: monospace;
									background: var(--bg-color); padding: 8px; border-radius: 4px;">
									${key}
								</p>
								<p class="text-muted" style="font-size: 12px;">
									Scan the QR code or copy the key. It won't be shown again.
								</p>
							</div>
						`);

						d.show();
					},
				});
			}
		);
	},
});
