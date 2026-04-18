frappe.pages["scanner-test"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Scanner Test"),
		single_column: true,
	});

	new ScannerTest(page);
};

class ScannerTest {
	constructor(page) {
		this.page = page;
		this.scanner_key = null;
		this.test_steps = [];
		this.current_step = -1;
		this.make();
	}

	make() {
		this.page.main.html(`
			<div class="scanner-test-container" style="max-width: 800px; margin: 0 auto;">
				<div class="scanner-select-area"></div>
				<div class="scanner-display-area" style="margin-top: 15px; display: none;">
					<label class="control-label" style="font-size: 11px;">${__("Scanner Display")}</label>
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
						<div style="margin-bottom: 4px; color: var(--text-muted);">${__("Endpoint")}:</div>
						<div class="endpoint-url" style="word-break: break-all;"></div>
					</div>
				</div>

				<div class="test-case-area" style="margin-top: 15px;"></div>
				<div class="test-steps-area" style="margin-top: 10px; display: none;">
					<div class="test-steps-list" style="
						font-family: monospace;
						font-size: 12px;
						background: var(--bg-color);
						border: 1px solid var(--border-color);
						border-radius: 4px;
						padding: 8px;
						max-height: 200px;
						overflow-y: auto;
					"></div>
					<div style="margin-top: 8px;">
						<button class="btn btn-primary btn-sm btn-step-next">${__("Send Next Step")}</button>
						<button class="btn btn-success btn-sm btn-step-all" style="margin-left: 6px;">${__("Run All")}</button>
						<button class="btn btn-default btn-sm btn-step-reset" style="margin-left: 6px;">${__("Reset")}</button>
						<span class="step-counter text-muted" style="margin-left: 12px; font-size: 12px;"></span>
					</div>
				</div>

				<div class="scan-input-area" style="margin-top: 15px;"></div>
				<div style="margin-top: 15px;">
					<button class="btn btn-primary btn-send-scan" disabled>${__("Send Scan")}</button>
					<button class="btn btn-default btn-clear-log" style="margin-left: 8px;">${__("Clear Log")}</button>
				</div>
				<div class="scan-log-area" style="margin-top: 20px;">
					<h5>${__("Response Log")}</h5>
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
		this.make_test_case_select();
		this.make_scan_input();
		this.bind_events();
	}

	make_scanner_select() {
		this.scanner_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Link",
				fieldname: "scanner",
				label: __("Scanner"),
				options: "Scanner",
				reqd: 1,
				change: () => this.on_scanner_change(),
			},
			parent: this.page.main.find(".scanner-select-area"),
			render_input: true,
		});
	}

	make_test_case_select() {
		this.test_case_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Link",
				fieldname: "test_case",
				label: __("Test Case"),
				options: "Scan Test Case",
				change: () => this.on_test_case_change(),
			},
			parent: this.page.main.find(".test-case-area"),
			render_input: true,
		});
	}

	make_scan_input() {
		this.data_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Data",
				fieldname: "scan_data",
				label: __("Scan Data"),
				placeholder: __("Barcode / Job Card / serial number / workplace / employee badge..."),
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

		this.page.main.find(".btn-step-next").on("click", () => this.run_next_step());
		this.page.main.find(".btn-step-all").on("click", () => this.run_all_steps());
		this.page.main.find(".btn-step-reset").on("click", () => this.reset_steps());
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
					frappe.show_alert({ message: __("No scanner key found"), indicator: "red" });
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

	on_test_case_change() {
		const name = this.test_case_field.get_value();
		const $area = this.page.main.find(".test-steps-area");
		if (!name) {
			$area.hide();
			this.test_steps = [];
			this.current_step = -1;
			return;
		}

		frappe.call({
			method: "frappe.client.get",
			args: { doctype: "Scan Test Case", name: name },
			callback: (r) => {
				const steps_raw = (r.message.steps || "").split("\n");
				this.test_steps = steps_raw
					.map((l) => l.trim())
					.filter((l) => l && !l.startsWith("#"));
				this.current_step = -1;
				this.render_steps();
				$area.show();
			},
		});
	}

	render_steps() {
		const $list = this.page.main.find(".test-steps-list");
		let html = "";
		this.test_steps.forEach((step, i) => {
			let style = "padding: 3px 6px; border-radius: 3px;";
			if (i < this.current_step + 1) {
				style += " color: var(--text-muted); text-decoration: line-through;";
			} else if (i === this.current_step + 1) {
				style += " background: var(--yellow-highlight-color, rgba(255,255,0,0.1)); font-weight: bold;";
			}
			html += `<div style="${style}">${i + 1}. ${frappe.utils.escape_html(step)}</div>`;
		});
		$list.html(html);

		const done = this.current_step + 1;
		const total = this.test_steps.length;
		this.page.main.find(".step-counter").text(`${done} / ${total}`);

		const all_done = done >= total;
		this.page.main.find(".btn-step-next").prop("disabled", all_done);
		this.page.main.find(".btn-step-all").prop("disabled", all_done);
	}

	run_next_step() {
		if (!this.scanner_key) {
			frappe.show_alert({ message: __("Select a scanner first"), indicator: "orange" });
			return;
		}
		const next = this.current_step + 1;
		if (next >= this.test_steps.length) return;

		const data = this.test_steps[next];
		this.current_step = next;
		this.render_steps();
		this._send(data);
	}

	run_all_steps() {
		if (!this.scanner_key) {
			frappe.show_alert({ message: __("Select a scanner first"), indicator: "orange" });
			return;
		}
		this._run_from(this.current_step + 1);
	}

	_run_from(idx) {
		if (idx >= this.test_steps.length) return;

		const data = this.test_steps[idx];
		this.current_step = idx;
		this.render_steps();

		this._send(data, () => {
			setTimeout(() => this._run_from(idx + 1), 500);
		});
	}

	reset_steps() {
		this.current_step = -1;
		this.render_steps();
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
			frappe.show_alert({ message: __("Enter scan data"), indicator: "orange" });
			return;
		}
		if (!this.scanner_key) {
			frappe.show_alert({ message: __("Select a scanner first"), indicator: "orange" });
			return;
		}

		this._send(data);
		this.data_field.set_value("");
		this.data_field.$input.focus();
	}

	_send(data, callback) {
		const ts = new Date().toLocaleTimeString();
		this.log_entry(ts, "\u2192", `"${data}"`, "blue");

		frappe.call({
			method: "erpnext.manufacturing.doctype.scanner.scanner_api.handle_scan",
			args: {
				scanner_key: this.scanner_key,
				data: data,
			},
			callback: (r) => {
				const res = r.message || r;
				const color = res.success ? "green" : "red";
				this.log_entry(ts, "\u2190", JSON.stringify(res, null, 2), color);
				this.update_display(res.message || res.error);
				if (callback) callback(res);
			},
			error: (r) => {
				this.log_entry(ts, "\u2190", `HTTP ERROR: ${JSON.stringify(r)}`, "red");
				if (callback) callback(null);
			},
		});
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
