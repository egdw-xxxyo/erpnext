function check_message_fit(msg, rows, chars) {
	if (!msg || !rows || !chars) return null;
	const lines = String(msg).split("\n");
	const over_lines = lines.length > rows;
	const long = lines
		.map((l, i) => ({ i: i + 1, len: l.length }))
		.filter((x) => x.len > chars);
	if (!over_lines && long.length === 0) return null;
	const parts = [];
	if (over_lines) parts.push(__("Lines: {0} (limit {1})", [lines.length, rows]));
	if (long.length) {
		const detail = long.map((x) => __("line {0}: {1} chars", [x.i, x.len])).join(", ");
		parts.push(__("Too long: {0} (limit {1})", [detail, chars]));
	}
	return parts.join("\n");
}

function mark_oversize_scan_logs(frm) {
	const grid = frm.fields_dict.scan_logs?.grid;
	if (!grid) return;
	const rows = frm._scanner_cfg_rows;
	const chars = frm._scanner_cfg_chars;
	if (!rows || !chars) return;
	(grid.grid_rows || []).forEach((gr) => {
		const warn = check_message_fit(gr.doc?.result_message, rows, chars);
		const $row = gr.row || gr.wrapper;
		if (!$row) return;
		$row.find(".scanner-overflow-warn").remove();
		$row.css("border-left", "");
		if (!warn) return;
		$row.css("border-left", "3px solid var(--red-500, #e24c4c)");
		const $cell = $row.find('[data-fieldname="result_message"]').first();
		const $target = $cell.length ? $cell : $row;
		$target.prepend(
			`<span class="scanner-overflow-warn" title="${frappe.utils.escape_html(warn)}" ` +
				`style="color: var(--red-500, #e24c4c); margin-right: 4px; cursor: help;">⚠</span>`
		);
	});
}

frappe.ui.form.on("Scanner", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.scanner_configuration) {
			frappe.db
				.get_value("Scanner Configuration", frm.doc.scanner_configuration, [
					"display_rows",
					"display_chars_per_row",
				])
				.then((r) => {
					frm._scanner_cfg_rows = r.message?.display_rows;
					frm._scanner_cfg_chars = r.message?.display_chars_per_row;
					mark_oversize_scan_logs(frm);
				});
		} else {
			frm._scanner_cfg_rows = null;
			frm._scanner_cfg_chars = null;
		}

		setTimeout(() => mark_oversize_scan_logs(frm), 300);

		frm.fields_dict.config_barcodes_html.$wrapper.html(
			`<div class="text-muted text-center" style="padding: 20px;">Завантаження...</div>`
		);

		const endpoint_url = `${window.location.origin}/api/method/erpnext.manufacturing.doctype.scanner.scanner_api.handle_scan`;

		frappe.call({
			method: "erpnext.manufacturing.doctype.scanner.scanner.get_config_barcodes",
			args: { scanner_name: frm.doc.name, endpoint_url: endpoint_url },
			callback: (r) => {
				if (!r.message) return;
				const d = r.message;

				frm.fields_dict.config_barcodes_html.$wrapper.html(`
					<style>
						.scanner-cfg-qr svg {
							display: block;
							margin: 0 auto;
							width: 420px !important;
							height: 420px !important;
						}
					</style>
					<div style="display: flex; justify-content: center;">
						<div style="min-width: 480px; max-width: 600px; border: 1px solid var(--border-color);
							border-radius: 6px; padding: 24px; text-align: center;">
							<div style="font-weight: 700; font-size: 18px; margin-bottom: 16px;">CFG-SCANNER</div>
							<div class="scanner-cfg-qr">${d.config_qr}</div>
							<div class="text-muted" style="font-size: 11px; margin-top: 16px; word-break: break-all;">
								${d.endpoint_url}
							</div>
							<div style="font-family: monospace; font-size: 14px; margin-top: 8px;">
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
			frappe.msgprint("Спочатку збережіть документ.");
			return;
		}
		frappe.confirm(
			"Згенерувати новий API ключ? Старий ключ перестане працювати негайно.",
			function () {
				frappe.call({
					method: "erpnext.manufacturing.doctype.scanner.scanner.regenerate_api_key",
					args: { scanner_name: frm.doc.name },
					callback: function (r) {
						if (!r.message) return;
						frm.set_value("api_key", r.message.api_key);
						frm.refresh_fields();
						frm.reload_doc();
					},
				});
			}
		);
	},
});

frappe.ui.form.on("Scanner Scan Log Entry", {
	form_render(frm) {
		mark_oversize_scan_logs(frm);
	},
});
