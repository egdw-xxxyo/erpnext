frappe.ui.form.on("Label Printer", {
	refresh(frm) {
		_render_check_connection(frm);

		if (frm.is_new()) return;

		frm.add_custom_button(__("Check Status"), () => {
			frappe.call({
				method: "erpnext.devices.doctype.label_printer.label_printer.check_status",
				args: { printer_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Checking printer status..."),
				callback(r) {
					if (r.message) {
						let status = r.message.status || {};
						let info = r.message.identification || {};
						frappe.msgprint({
							title: __("Printer Status"),
							indicator: status.status === "Ready" ? "green" : "red",
							message: `
								<b>${__("Status")}:</b> ${status.status || "Unknown"}<br>
								<b>${__("Model")}:</b> ${info.model || "-"}<br>
								<b>${__("Firmware")}:</b> ${info.firmware || "-"}<br>
								<b>${__("Memory")}:</b> ${info.memory || "-"}
							`,
						});
					}
					frm.reload_doc();
				},
			});
		}, __("Actions"));

		frm.add_custom_button(__("Get Full Info"), () => {
			frappe.call({
				method: "erpnext.devices.doctype.label_printer.label_printer.get_printer_info",
				args: { printer_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Getting printer info..."),
				callback(r) {
					if (r.message) {
						frappe.msgprint({
							title: __("Full Printer Info"),
							message: `<pre>${JSON.stringify(r.message, null, 2)}</pre>`,
						});
					}
					frm.reload_doc();
				},
			});
		}, __("Actions"));

		frm.add_custom_button(__("Beep"), () => {
			frappe.call({
				method: "erpnext.devices.doctype.label_printer.label_printer.beep",
				args: { printer_name: frm.doc.name },
				callback(r) {
					if (r.message && r.message.success) {
						frappe.show_alert({ message: __("Beep sent!"), indicator: "green" });
					}
				},
			});
		}, __("Actions"));

		frm.add_custom_button(__("Calibration Print"), () => {
			frappe.call({
				method: "erpnext.devices.doctype.label_printer.label_printer.print_calibration_label",
				args: { printer_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Printing calibration label..."),
				callback(r) {
					if (r.message && r.message.success) {
						frappe.show_alert({
							message: __("Calibration label sent! Current offset: X={0}, Y={1}",
								[r.message.offset_x, r.message.offset_y]),
							indicator: "green",
						});
					}
				},
			});
		}, __("Actions"));

		frm.add_custom_button(__("Clear Memory"), () => {
			frappe.confirm(
				__("Erase all stored images from printer memory?"),
				() => {
					frappe.call({
						method: "erpnext.devices.doctype.label_printer.label_printer.clear_printer_memory",
						args: { printer_name: frm.doc.name },
						freeze: true,
						freeze_message: __("Clearing printer memory..."),
						callback(r) {
							if (r.message && r.message.success) {
								frappe.show_alert({ message: __("Printer memory cleared!"), indicator: "green" });
							}
						},
					});
				}
			);
		}, __("Actions"));

		frm.add_custom_button(__("Print Queue"), () => {
			frappe.set_route("List", "Print Job");
		});

		frm.add_custom_button(__("Send Command"), () => {
			let d = new frappe.ui.Dialog({
				title: __("Send Raw Command"),
				fields: [
					{
						fieldname: "command",
						fieldtype: "Data",
						label: __("Command"),
						reqd: 1,
						description: __("e.g. ~HS (status), ~HI (info), ~HD (diagnostics)"),
					},
				],
				primary_action_label: __("Send"),
				primary_action(values) {
					d.hide();
					frappe.call({
						method: "erpnext.devices.doctype.label_printer.label_printer.send_raw_command",
						args: { printer_name: frm.doc.name, command: values.command },
						callback(r) {
							if (r.message) {
								frappe.msgprint({
									title: __("Command Response"),
									message: `<b>${__("Command")}:</b> ${r.message.command}<br><pre>${r.message.response || "(no response)"}</pre>`,
								});
							}
						},
					});
				},
			});
			d.show();
		}, __("Actions"));
	},
});

function _render_check_connection(frm) {
	let $wrapper = frm.fields_dict.check_connection_html && frm.fields_dict.check_connection_html.$wrapper;
	if (!$wrapper) return;

	$wrapper.html(`
		<div style="margin-top:10px;">
			<button class="btn btn-sm btn-default btn-check-conn">
				${__("Check Connection")}
			</button>
			<span class="conn-result" style="margin-left:10px;"></span>
		</div>
	`);

	$wrapper.find(".btn-check-conn").on("click", function () {
		let $btn = $(this);
		let $result = $wrapper.find(".conn-result");

		if (frm.is_new() || !frm.doc.ip_address) {
			$result.html(`<span class="text-muted">${__("Save the printer first")}</span>`);
			return;
		}

		console.log("[Label Printer] Checking connection to", frm.doc.ip_address, ":", frm.doc.port);
		$btn.prop("disabled", true).text(__("Checking..."));
		$result.html("");

		let t0 = performance.now();

		frappe.call({
			method: "erpnext.devices.doctype.label_printer.label_printer.check_connection",
			args: { printer_name: frm.doc.name },
			callback(r) {
				let elapsed = ((performance.now() - t0) / 1000).toFixed(1);
				console.log("[Label Printer] Response in", elapsed + "s:", r.message);
				$btn.prop("disabled", false).text(__("Check Connection"));

				if (r.message) {
					let ok = r.message.connected;
					let status = r.message.status || "Unknown";
					let info = r.message.identification || {};
					let detail = [info.model, info.firmware].filter(Boolean).join(" ");
					$result.html(`
						<span class="indicator-pill ${ok ? "green" : "red"}">${status}</span>
						<span class="text-muted" style="margin-left:6px;">${detail} (${elapsed}s)</span>
					`);
				}
			},
			error(r) {
				let elapsed = ((performance.now() - t0) / 1000).toFixed(1);
				console.error("[Label Printer] Connection check failed in", elapsed + "s:", r);
				$btn.prop("disabled", false).text(__("Check Connection"));
				$result.html(`<span class="indicator-pill red">${__("Connection failed")} (${elapsed}s)</span>`);
			},
		});
	});
}
