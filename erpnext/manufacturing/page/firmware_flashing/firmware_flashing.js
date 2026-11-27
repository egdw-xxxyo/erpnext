const FLASH_API = "erpnext.manufacturing.flashing";

frappe.pages["firmware-flashing"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Firmware Flashing"),
		single_column: true,
	});
	new FirmwareFlashing({ wrapper: $(wrapper).find(".layout-main-section"), page });
};

class FirmwareFlashing {
	constructor({ wrapper, page }) {
		this.page = page;
		this.$root = $('<div class="firmware-flashing"></div>').appendTo(wrapper);
		this.workplace = localStorage.getItem("firmware_flashing_workplace") || "";
		this.current = null;
		this.busy = false;

		this.workplace_field = page.add_field({
			fieldname: "workplace",
			label: __("Workplace"),
			fieldtype: "Select",
			change: () => {
				this.workplace = this.workplace_field.get_value() || "";
				localStorage.setItem("firmware_flashing_workplace", this.workplace);
				this.refresh();
			},
		});
		page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");

		frappe.call({
			method: "erpnext.manufacturing.page.workplace_portal.workplace_portal.get_workplaces",
			callback: (r) => {
				const rows = r.message || [];
				const options = [""].concat(rows.map((w) => w.name));
				this.workplace_field.df.options = options.join("\n");
				this.workplace_field.refresh();
				if (this.workplace && options.includes(this.workplace)) {
					this.workplace_field.set_value(this.workplace);
				} else {
					this.workplace = "";
					this.refresh();
				}
			},
		});
	}

	refresh() {
		frappe.call({
			method: FLASH_API + ".get_overview",
			args: { workplace: this.workplace || null },
			callback: (r) => {
				const data = r.message || {};
				this.current = data.open_attempt || null;
				this.render(data);
			},
		});
	}

	render(data) {
		this.$root.empty();
		if (this.current) {
			this.render_board(this.current);
		} else {
			this.render_start(data);
		}
		this.render_tables(data);
	}

	render_start(data) {
		const waiting = (data.waiting || []).reduce((n, r) => n + r.count, 0);
		const $box = $(`
			<div class="frappe-card" style="padding:20px;margin-bottom:15px;">
				<div class="text-muted" style="margin-bottom:10px;">
					${__("Boards waiting for flashing")}: <b>${waiting}</b>
				</div>
				<button class="btn btn-primary btn-lg btn-next" ${waiting ? "" : "disabled"}>
					<i class="fa fa-microchip"></i> ${__("Next board")}
				</button>
			</div>
		`).appendTo(this.$root);
		$box.find(".btn-next").on("click", () => this.next_board());
	}

	next_board() {
		frappe.call({
			method: FLASH_API + ".next_board",
			args: { workplace: this.workplace || null },
			freeze: true,
			callback: (r) => {
				this.current = r.message;
				this.refresh();
			},
		});
	}

	render_board(c) {
		const esc = frappe.utils.escape_html;
		const can_write = !!window.showDirectoryPicker;
		const can_serial = !!navigator.serial && c.verify_mode === "Console";
		const $box = $(`
			<div class="frappe-card" style="padding:20px;margin-bottom:15px;">
				<div class="text-muted">${esc(c.item_name || c.item_code)} · ${__("Job Card")} ${esc(c.job_card)}</div>
				<div style="font-size:32px;font-weight:600;letter-spacing:1px;margin:6px 0;">${esc(c.serial_no)}</div>
				<div style="margin-bottom:12px;">
					<i class="fa fa-file-code-o"></i> ${esc(c.firmware)} <b>${esc(c.version)}</b>
					<span class="text-muted" style="margin-left:8px;">SHA-256 ${esc((c.sha256 || "").slice(0, 12))}…</span>
				</div>
				<div class="flash-instructions" style="margin-bottom:15px;">${c.instructions || ""}</div>
				<div class="flash-actions" style="display:flex;gap:8px;flex-wrap:wrap;">
					${can_write ? `<button class="btn btn-primary btn-write"><i class="fa fa-usb"></i> ${__("Write to board")}</button>` : ""}
					<button class="btn btn-default btn-download"><i class="fa fa-download"></i> ${__("Download UF2")}</button>
					${can_serial ? `<button class="btn btn-default btn-verify"><i class="fa fa-plug"></i> ${__("Verify via console")}</button>` : ""}
					<button class="btn btn-success btn-confirm"><i class="fa fa-check"></i> ${__("Board shows this serial")}</button>
					<button class="btn btn-danger btn-fail"><i class="fa fa-times"></i> ${__("Failed")}</button>
					<button class="btn btn-default btn-release">${__("Put back")}</button>
				</div>
				<div class="flash-status text-muted" style="margin-top:12px;"></div>
			</div>
		`).appendTo(this.$root);

		this.$status = $box.find(".flash-status");
		$box.find(".btn-write").on("click", () => this.write_to_drive(c));
		$box.find(".btn-download").on("click", () => this.download(c));
		$box.find(".btn-verify").on("click", () => this.verify_console(c));
		$box.find(".btn-confirm").on("click", () => this.confirm(c, "Operator", null));
		$box.find(".btn-fail").on("click", () => this.fail(c));
		$box.find(".btn-release").on("click", () => this.release(c));
	}

	image_url(c) {
		return `/api/method/${FLASH_API}.get_image?attempt=${encodeURIComponent(c.attempt)}`;
	}

	set_status(text, color) {
		this.$status.css("color", color || "").text(text);
	}

	async fetch_image(c) {
		const response = await fetch(this.image_url(c), {
			credentials: "same-origin",
			headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
		});
		if (!response.ok) {
			throw new Error(__("Could not build the image ({0})", [response.status]));
		}
		return response.arrayBuffer();
	}

	download(c) {
		window.open(this.image_url(c));
		this.set_status(__("Copy the downloaded file to the RPI-RP2 drive"));
	}

	async write_to_drive(c) {
		let dir;
		try {
			dir = await window.showDirectoryPicker({ mode: "readwrite" });
		} catch (e) {
			return;
		}

		this.set_status(__("Building the image…"));
		try {
			const data = await this.fetch_image(c);
			const handle = await dir.getFileHandle(c.file_name, { create: true });
			const writable = await handle.createWritable();
			try {
				await writable.write(data);
				await writable.close();
			} catch (e) {
				// The board reboots as soon as the last block lands and takes the drive with it.
			}
			this.set_status(__("Written. Wait for the board to restart, then verify"), "var(--green-600)");
		} catch (e) {
			this.set_status(e.message || String(e), "var(--red-600)");
		}
	}

	async verify_console(c) {
		let port;
		try {
			port = await navigator.serial.requestPort({ filters: [{ usbVendorId: 0x2e8a }] });
			await port.open({ baudRate: c.verify_baud || 115200 });
		} catch (e) {
			this.set_status(__("Could not open the board's console"), "var(--red-600)");
			return;
		}

		this.set_status(__("Waiting for {0}…", [c.verify_pattern]));
		const decoder = new TextDecoderStream();
		const closed = port.readable.pipeTo(decoder.writable).catch(() => {});
		const reader = decoder.readable.getReader();
		const deadline = Date.now() + (c.verify_timeout || 20) * 1000;
		let buffer = "";
		let found = null;

		try {
			while (Date.now() < deadline && !found) {
				const timeout = new Promise((resolve) =>
					setTimeout(() => resolve({ timed_out: true }), Math.max(deadline - Date.now(), 0))
				);
				const chunk = await Promise.race([reader.read(), timeout]);
				if (chunk.timed_out || chunk.done) break;
				buffer += chunk.value;
				found = buffer.split(/\r?\n/).find((line) => line.includes(c.verify_pattern)) || null;
			}
		} finally {
			try {
				await reader.cancel();
				await closed;
				await port.close();
			} catch (e) {
				// the port is already gone
			}
		}

		if (!found) {
			this.set_status(
				__("The board did not report {0}. Reset it and try again, or confirm from the screen", [c.verify_pattern]),
				"var(--red-600)"
			);
			return;
		}
		this.confirm(c, "Console", found.trim());
	}

	confirm(c, verified_by, console_line) {
		frappe.call({
			method: FLASH_API + ".confirm",
			args: { attempt: c.attempt, verified_by, console_line },
			freeze: true,
			callback: () => {
				frappe.show_alert({
					message: __("{0} flashed. Stick the label {0}", [c.serial_no]),
					indicator: "green",
				});
				this.current = null;
				this.refresh();
			},
		});
	}

	fail(c) {
		frappe.prompt(
			{ fieldname: "reason", fieldtype: "Small Text", label: __("What went wrong"), reqd: 1 },
			(values) => {
				frappe.call({
					method: FLASH_API + ".fail",
					args: { attempt: c.attempt, reason: values.reason },
					callback: () => this.refresh(),
				});
			},
			__("Flashing failed"),
			__("Log it and put the board back")
		);
	}

	release(c) {
		frappe.call({
			method: FLASH_API + ".release",
			args: { attempt: c.attempt },
			callback: () => this.refresh(),
		});
	}

	render_tables(data) {
		const esc = frappe.utils.escape_html;
		const $waiting = $('<div style="margin-bottom:15px;"></div>').appendTo(this.$root);
		$('<h5></h5>').text(__("Waiting")).appendTo($waiting);
		new erpnext.DataTable({
			parent: $waiting,
			storage_key: "firmware-flashing-waiting",
			max_height: "240px",
			rows: data.waiting || [],
			columns: [
				{ key: "item_code", label: __("Item"), pin: true, html: (r) => esc(r.item_code) },
				{ key: "firmware", label: __("Firmware"), html: (r) => esc(r.firmware) },
				{ key: "version", label: __("Version"), html: (r) => esc(r.version || "—") },
				{ key: "count", label: __("Boards"), align: "right", value: (r) => flt(r.count), html: (r) => r.count },
			],
		});

		const $recent = $("<div></div>").appendTo(this.$root);
		$("<h5></h5>").text(__("Recent")).appendTo($recent);
		new erpnext.DataTable({
			parent: $recent,
			storage_key: "firmware-flashing-recent",
			max_height: "320px",
			rows: data.recent || [],
			columns: [
				{ key: "serial_no", label: __("Serial No"), pin: true, html: (r) => esc(r.serial_no) },
				{ key: "status", label: __("Status"), html: (r) => esc(__(r.status)) },
				{ key: "firmware_version", label: __("Version"), html: (r) => esc(r.firmware_version || "") },
				{ key: "verified_by", label: __("Verified By"), html: (r) => esc(r.verified_by ? __(r.verified_by) : "") },
				{ key: "owner", label: __("Operator"), html: (r) => erpnext.entity.user(r.owner, { size: 18 }) },
				{
					key: "finished_on",
					label: __("Finished"),
					html: (r) => (r.finished_on ? frappe.datetime.str_to_user(r.finished_on) : ""),
				},
			],
			on_row_click: (r) => frappe.set_route("Form", "Flash Attempt", r.name),
		});
	}
}
