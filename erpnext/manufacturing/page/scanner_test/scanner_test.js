frappe.pages["scanner-test"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Scanner Test",
		single_column: true,
	});

	new ScannerTest(page);
};

class ScannerTest {
	constructor(page) {
		this.page = page;
		this.scanner_key = null;
		this.make();
	}

	make() {
		this.page.main.html(`
			<div class="scanner-test-container" style="max-width: 800px; margin: 0 auto;">
				<div class="scanner-select-area"></div>
				<div class="scanner-status" style="margin-top: 15px; display: none;">
					<div class="alert alert-info" style="margin-bottom: 0;"></div>
				</div>

				<div class="endpoint-area" style="margin-top: 15px; display: none;">
					<div style="background: var(--bg-color); border: 1px solid var(--border-color);
						border-radius: 4px; padding: 12px; font-family: monospace; font-size: 12px;">
						<div style="margin-bottom: 4px; color: var(--text-muted);">Endpoint:</div>
						<div class="endpoint-url" style="word-break: break-all;"></div>
					</div>
				</div>

				<div class="scan-input-area" style="margin-top: 15px;"></div>
				<div class="employee-barcode-area" style="margin-top: 10px;"></div>
				<div style="margin-top: 15px;">
					<button class="btn btn-primary btn-send-scan" disabled>Send Scan</button>
					<button class="btn btn-default btn-clear-log" style="margin-left: 8px;">Clear Log</button>
				</div>
				<div class="scan-log-area" style="margin-top: 20px;">
					<h5>Response Log</h5>
					<div class="scan-log" style="
						font-family: monospace;
						font-size: 12px;
						background: var(--bg-color);
						border: 1px solid var(--border-color);
						border-radius: 4px;
						padding: 10px;
						max-height: 500px;
						overflow-y: auto;
					"></div>
				</div>
			</div>
		`);

		this.make_scanner_select();
		this.make_scan_input();
		this.make_employee_barcode();
		this.bind_events();
	}

	make_scanner_select() {
		this.scanner_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Link",
				fieldname: "scanner",
				label: "Scanner",
				options: "Scanner Setup",
				reqd: 1,
				change: () => this.on_scanner_change(),
			},
			parent: this.page.main.find(".scanner-select-area"),
			render_input: true,
		});
	}

	make_scan_input() {
		this.data_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Data",
				fieldname: "scan_data",
				label: "Scan Data",
				placeholder: "Barcode / Job Card / serial number / workplace / employee badge...",
			},
			parent: this.page.main.find(".scan-input-area"),
			render_input: true,
		});
	}

	make_employee_barcode() {
		this.employee_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Link",
				fieldname: "employee_lookup",
				label: "Employee (for badge barcode)",
				options: "Employee",
				change: () => this.on_employee_change(),
			},
			parent: this.page.main.find(".employee-barcode-area"),
			render_input: true,
		});

		this.$barcode_preview = $('<div class="barcode-employee-preview" style="margin-top: 8px;"></div>');
		this.page.main.find(".employee-barcode-area").append(this.$barcode_preview);
	}

	on_employee_change() {
		const emp = this.employee_field.get_value();
		if (!emp) {
			this.$barcode_preview.empty();
			return;
		}

		frappe.db.get_value("Employee", emp, "attendance_device_id").then((r) => {
			const badge_id = r.message?.attendance_device_id;
			if (!badge_id) {
				this.$barcode_preview.html(
					'<span class="text-muted">No attendance_device_id set on this employee</span>'
				);
				return;
			}

			frappe.call({
				method: "erpnext.manufacturing.doctype.scanner_setup.scanner_setup.render_barcode_svg",
				args: { data: badge_id },
				callback: (r) => {
					if (r.message) {
						this.$barcode_preview.html(r.message);
					}
				},
			});
		});
	}

	bind_events() {
		const $send = this.page.main.find(".btn-send-scan");
		const $clear = this.page.main.find(".btn-clear-log");

		$send.on("click", () => this.send_scan());
		$clear.on("click", () => this.page.main.find(".scan-log").empty());

		this.page.main.find(".scan-input-area").on("keydown", "input", (e) => {
			if (e.key === "Enter" && !$send.prop("disabled")) {
				this.send_scan();
			}
		});
	}

	on_scanner_change() {
		const scanner_name = this.scanner_field.get_value();
		const $status = this.page.main.find(".scanner-status");
		const $send = this.page.main.find(".btn-send-scan");
		const $endpoint = this.page.main.find(".endpoint-area");
		if (!scanner_name) {
			$status.hide();
			$endpoint.hide();
			$send.prop("disabled", true);
			this.scanner_key = null;
			return;
		}

		frappe.call({
			method: "erpnext.manufacturing.doctype.scanner_setup.scanner_setup.get_scanner_key",
			args: { scanner_name: scanner_name },
			callback: (r) => {
				if (!r.message) {
					frappe.show_alert({ message: "No scanner key found", indicator: "red" });
					return;
				}
				this.scanner_key = r.message;
				this.update_status({ workplace: null, employee: null });
				$send.prop("disabled", false);

				const base = window.location.origin;
				const url = `${base}/api/method/erpnext.manufacturing.doctype.scanner_setup.scanner_api.handle_scan?scanner_key=${this.scanner_key}&data=<BARCODE>`;
				$endpoint.find(".endpoint-url").text(url);
				$endpoint.show();
			},
		});
	}

	update_status(res) {
		const $status = this.page.main.find(".scanner-status");
		const scanner = this.scanner_field.get_value();
		const wp = res.workplace || "—";
		const emp = res.employee || "—";
		const mode = res.mode ? ` | Mode: ${res.mode}` : "";
		$status.find(".alert").html(
			`<strong>${scanner}</strong> &mdash; Workplace: <strong>${wp}</strong> | Employee: <strong>${emp}</strong>${mode}`
		);
		$status.show();

		if (res.prompt) {
			this.data_field.set_description(
				`<span style="color: var(--primary);">${res.prompt}</span>`
			);
		} else {
			this.data_field.set_description("");
		}
	}

	send_scan() {
		const data = this.data_field.get_value();
		if (!data) {
			frappe.show_alert({ message: "Enter scan data", indicator: "orange" });
			return;
		}
		if (!this.scanner_key) {
			frappe.show_alert({ message: "Select a scanner first", indicator: "orange" });
			return;
		}

		const ts = new Date().toLocaleTimeString();
		this.log_entry(ts, "→", `"${data}"`, "blue");

		frappe.call({
			method: "erpnext.manufacturing.doctype.scanner_setup.scanner_api.handle_scan",
			args: {
				scanner_key: this.scanner_key,
				data: data,
			},
			callback: (r) => {
				const res = r.message || r;
				const color = res.success ? "green" : "red";
				this.log_entry(ts, "←", JSON.stringify(res, null, 2), color);
				this.update_status(res);
			},
			error: (r) => {
				this.log_entry(ts, "←", `HTTP ERROR: ${JSON.stringify(r)}`, "red");
			},
		});

		this.data_field.set_value("");
		this.data_field.$input.focus();
	}

	log_entry(ts, arrow, text, color) {
		const $log = this.page.main.find(".scan-log");
		const colorMap = {
			blue: "var(--blue-500)",
			green: "var(--green-600)",
			red: "var(--red-600)",
		};
		$log.prepend(
			`<div style="margin-bottom: 6px; color: ${colorMap[color] || "inherit"}; white-space: pre-wrap;">[${ts}] ${arrow} ${frappe.utils.escape_html(text)}</div>`
		);
	}
}
