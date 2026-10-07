function check_message_fit(msg, rows, chars) {
	if (!msg || !rows || !chars) return null;
	const lines = String(msg).split("\n");
	const over_lines = lines.length > rows;
	const long = lines.map((l, i) => ({ i: i + 1, len: l.length })).filter((x) => x.len > chars);
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

function open_scan_dialog(frm) {
	frappe
		.call({
			method: "erpnext.devices.doctype.scanner.scanner.get_scanner_key",
			args: { scanner_name: frm.doc.name },
		})
		.then((r) => {
			if (!r.message) {
				frappe.show_alert({ message: __("No scanner key found"), indicator: "red" });
				return;
			}
			show_scan_dialog(frm, r.message);
		});
}

function show_scan_dialog(frm, scanner_key) {
	const SAME_CODE_GAP_MS = 2000;
	let busy = false;
	let sent_any = false;
	let last_text = null;
	let last_seen = 0;
	let camera = null;
	let closed = false;

	const dialog = new frappe.ui.Dialog({
		title: __("Scan Code"),
		fields: [
			{ fieldtype: "HTML", fieldname: "camera_area" },
			{
				fieldtype: "Data",
				fieldname: "scan_data",
				label: __("Scan Data"),
				placeholder: __("Type a code and press Enter"),
			},
			{ fieldtype: "HTML", fieldname: "reply_area" },
		],
		primary_action_label: __("Send"),
		primary_action: () => {
			const field = dialog.get_field("scan_data");
			send(field.get_value());
			field.set_value("");
			field.$input.focus();
		},
		on_page_show: () => start_camera(),
		on_hide: () => {
			closed = true;
			if (camera) camera.stop_scan();
			if (sent_any) frm.reload_doc();
		},
	});

	const $camera = dialog.get_field("camera_area").$wrapper;
	const $reply = dialog.get_field("reply_area").$wrapper;
	$camera.html(`<div class="scanner-cam-view" style="max-width: 420px; margin: 0 auto;"></div>
		<div class="scanner-cam-hint text-muted small text-center" style="margin: 6px 0 10px;"></div>`);
	$reply.html(`<div class="scanner-reply" style="display: none; white-space: pre-wrap; font-family: monospace;
			font-size: 13px; padding: 8px 10px; border-radius: 4px; border: 1px solid var(--border-color);"></div>
		<div class="scanner-reply-log small" style="margin-top: 8px; max-height: 160px; overflow-y: auto;"></div>`);

	const hint = (text) => $camera.find(".scanner-cam-hint").text(text);

	const show_reply = (text, ok, reply) => {
		const colour = ok ? "var(--green-600)" : "var(--red-600)";
		$reply
			.find(".scanner-reply")
			.css({ display: "block", color: colour })
			.text(reply || "");
		$reply.find(".scanner-reply-log").prepend(
			`<div><i class="fa ${ok ? "fa-check" : "fa-times"}" style="color: ${colour};"></i>
				${frappe.utils.escape_html(text)}</div>`
		);
	};

	const send = (text) => {
		text = (text || "").trim();
		if (!text || busy) return;
		busy = true;
		const url =
			"/api/method/erpnext.devices.doctype.scanner.scanner_api.handle_scan" +
			`?scanner_key=${encodeURIComponent(scanner_key)}&data=${encodeURIComponent(text)}`;
		fetch(url, { credentials: "omit", headers: { Accept: "application/json" } })
			.then((res) => res.json())
			.then((body) => {
				const res = body.message || {};
				sent_any = true;
				show_reply(text, !!res.success, res.message || res.error || __("No reply from the scanner"));
			})
			.catch(() => show_reply(text, false, __("No connection to the server")))
			.finally(() => {
				busy = false;
				last_text = text;
				last_seen = Date.now();
			});
	};

	const on_camera_scan = (result) => {
		const text = result?.decodedText;
		if (!text || busy) return;
		const now = Date.now();
		if (text === last_text && now - last_seen < SAME_CODE_GAP_MS) {
			last_seen = now;
			return;
		}
		send(text);
	};

	const start_camera = () => {
		if (camera || closed) return;
		if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
			hint(__("The camera works only over HTTPS. Type the code instead."));
			return;
		}
		navigator.mediaDevices
			.getUserMedia({ video: { facingMode: "environment" } })
			.then((stream) => {
				stream.getTracks().forEach((track) => track.stop());
				if (closed) return;
				camera = new frappe.ui.Scanner({
					container: $camera.find(".scanner-cam-view"),
					multiple: true,
					on_scan: on_camera_scan,
				});
				camera.load_lib().then(() => {
					if (!closed) camera.start_scan();
				});
				hint(__("Point the camera at a barcode or QR code"));
			})
			.catch(() => hint(__("Camera is not available. Type the code instead.")));
	};

	dialog.show();
}

frappe.ui.form.on("Scanner", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Scan Code"), () => open_scan_dialog(frm));

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

		const endpoint_url = `${window.location.origin}/api/method/erpnext.devices.doctype.scanner.scanner_api.handle_scan`;

		frappe.call({
			method: "erpnext.devices.doctype.scanner.scanner.get_config_barcodes",
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
		frappe.confirm("Згенерувати новий API ключ? Старий ключ перестане працювати негайно.", function () {
			frappe.call({
				method: "erpnext.devices.doctype.scanner.scanner.regenerate_api_key",
				args: { scanner_name: frm.doc.name },
				callback: function (r) {
					if (!r.message) return;
					frm.set_value("api_key", r.message.api_key);
					frm.refresh_fields();
					frm.reload_doc();
				},
			});
		});
	},
});

frappe.ui.form.on("Scanner Scan Log Entry", {
	form_render(frm) {
		mark_oversize_scan_logs(frm);
	},
});
