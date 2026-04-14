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
				<div class="scanner-display-area" style="margin-top: 15px; display: none;">
					<label class="control-label" style="font-size: 11px;">Scanner Display</label>
					<div class="scanner-display" style="
						display: inline-block;
						background: #1a1a2e;
						color: #00ff88;
						font-family: 'Courier New', monospace;
						font-size: 13px;
						font-weight: bold;
						padding: 8px 10px;
						border-radius: 4px;
						border: 2px solid #333;
						box-shadow: inset 0 0 10px rgba(0,0,0,0.5);
						line-height: 1.3;
						letter-spacing: 0.5px;
						white-space: pre;
						overflow: hidden;
					"></div>
				</div>

				<div class="endpoint-area" style="margin-top: 15px; display: none;">
					<div style="background: var(--bg-color); border: 1px solid var(--border-color);
						border-radius: 4px; padding: 12px; font-family: monospace; font-size: 12px;">
						<div style="margin-bottom: 4px; color: var(--text-muted);">Endpoint:</div>
						<div class="endpoint-url" style="word-break: break-all;"></div>
					</div>
				</div>

				<div class="scan-input-area" style="margin-top: 15px;"></div>
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
		this.bind_events();
	}

	make_scanner_select() {
		this.scanner_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Link",
				fieldname: "scanner",
				label: "Scanner",
				options: "Scanner",
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
		const $send = this.page.main.find(".btn-send-scan");
		const $endpoint = this.page.main.find(".endpoint-area");
		const $display_area = this.page.main.find(".scanner-display-area");
		if (!scanner_name) {
			$endpoint.hide();
			$display_area.hide();
			$send.prop("disabled", true);
			this.scanner_key = null;
			this.display_config = null;
			return;
		}

		frappe.call({
			method: "erpnext.manufacturing.doctype.scanner.scanner.get_scanner_key",
			args: { scanner_name: scanner_name },
			callback: (r) => {
				if (!r.message) {
					frappe.show_alert({ message: "No scanner key found", indicator: "red" });
					return;
				}
				this.scanner_key = r.message;
				$send.prop("disabled", false);

				const base = window.location.origin;
				const url = `${base}/api/method/erpnext.manufacturing.doctype.scanner.scanner_api.handle_scan?scanner_key=${this.scanner_key}&data=<BARCODE>`;
				$endpoint.find(".endpoint-url").text(url);
				$endpoint.show();
			},
		});

		frappe.call({
			method: "erpnext.manufacturing.doctype.scanner.scanner.get_display_config",
			args: { scanner_name: scanner_name },
			callback: (r) => {
				this.display_config = r.message || { rows: 10, cols: 20 };
				this.init_display();
			},
		});
	}

	init_display() {
		const $area = this.page.main.find(".scanner-display-area");
		const $display = this.page.main.find(".scanner-display");
		const { rows, cols } = this.display_config;

		const empty_lines = [];
		for (let i = 0; i < rows; i++) {
			empty_lines.push(" ".repeat(cols));
		}
		$display.text(empty_lines.join("\n"));
		$area.show();
	}

	update_display(message) {
		if (!this.display_config) return;
		const $display = this.page.main.find(".scanner-display");
		const { rows, cols } = this.display_config;

		const raw_lines = (message || "").split("\n");
		const display_lines = [];
		for (let i = 0; i < rows; i++) {
			const line = raw_lines[i] || "";
			display_lines.push(line.substring(0, cols).padEnd(cols));
		}
		$display.text(display_lines.join("\n"));
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
			method: "erpnext.manufacturing.doctype.scanner.scanner_api.handle_scan",
			args: {
				scanner_key: this.scanner_key,
				data: data,
			},
			callback: (r) => {
				const res = r.message || r;
				const color = res.success ? "green" : "red";
				this.log_entry(ts, "←", JSON.stringify(res, null, 2), color);
				this.update_display(res.message || res.error);
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
