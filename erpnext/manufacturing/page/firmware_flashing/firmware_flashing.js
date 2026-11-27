const FLASH_API = "erpnext.manufacturing.flashing";

const BOOTSEL_FILTER = { vendorId: 0x2e8a, productId: 0x0003 };
const PICOBOOT_MAGIC = 0x431fd10b;
const PICOBOOT_SECTOR = 4096;

// Flattens a UF2 image into one buffer aligned to flash sectors (gaps stay 0xFF).
function uf2_to_flash(buffer) {
	if (buffer.byteLength % 512) {
		throw new Error(__("Not a UF2 file"));
	}
	const view = new DataView(buffer);
	const blocks = [];
	for (let off = 0; off < buffer.byteLength; off += 512) {
		if (
			view.getUint32(off, true) !== 0x0a324655 ||
			view.getUint32(off + 4, true) !== 0x9e5d5157 ||
			view.getUint32(off + 508, true) !== 0x0ab16f30
		) {
			throw new Error(__("Not a UF2 file"));
		}
		if (view.getUint32(off + 8, true) & 1) continue;
		const size = view.getUint32(off + 16, true);
		blocks.push({
			address: view.getUint32(off + 12, true),
			data: new Uint8Array(buffer, off + 32, size),
		});
	}
	if (!blocks.length) throw new Error(__("Not a UF2 file"));

	const low = Math.min(...blocks.map((b) => b.address));
	const high = Math.max(...blocks.map((b) => b.address + b.data.length));
	const start = Math.floor(low / PICOBOOT_SECTOR) * PICOBOOT_SECTOR;
	const end = Math.ceil(high / PICOBOOT_SECTOR) * PICOBOOT_SECTOR;
	const data = new Uint8Array(end - start).fill(0xff);
	blocks.forEach((b) => data.set(b.data, b.address - start));
	return { start, data };
}

const PICOBOOT_COMMANDS = {
	1: "EXCLUSIVE_ACCESS",
	2: "REBOOT",
	3: "FLASH_ERASE",
	4: "READ",
	5: "WRITE",
	6: "EXIT_XIP",
	7: "ENTER_CMD_XIP",
};

function describe_device(d) {
	return `${d.productName || "USB device"} ${d.vendorId.toString(16)}:${d.productId.toString(16)} serial ${
		d.serialNumber || "-"
	}`;
}

// PICOBOOT: the RP2040 boot ROM's USB interface, spoken straight over WebUSB.
class Picoboot {
	constructor(device, log) {
		this.device = device;
		this.token = 1;
		this.log = log || (() => {});
	}

	async open() {
		const device = this.device;
		this.log(`open ${describe_device(device)}`);
		await device.open();
		if (!device.configuration) {
			this.log("no configuration selected, selecting 1");
			await device.selectConfiguration(1);
		}
		for (const iface of device.configuration.interfaces) {
			this.log(
				`interface ${iface.interfaceNumber}: ` +
					iface.alternates
						.map(
							(a) =>
								`class 0x${a.interfaceClass.toString(16)} endpoints [` +
								a.endpoints
									.map((e) => `${e.direction}/${e.type}/${e.endpointNumber}`)
									.join(", ") +
								"]"
						)
						.join("; ")
			);
			const alt = iface.alternates.find((a) => a.interfaceClass === 0xff);
			if (!alt) continue;
			this.interface_number = iface.interfaceNumber;
			this.ep_out = alt.endpoints.find((e) => e.direction === "out" && e.type === "bulk");
			this.ep_in = alt.endpoints.find((e) => e.direction === "in" && e.type === "bulk");
		}
		if (this.interface_number === undefined || !this.ep_out || !this.ep_in) {
			throw new Error(__("The board has no PICOBOOT interface"));
		}
		this.log(
			`using interface ${this.interface_number}, out ep ${this.ep_out.endpointNumber}, in ep ${this.ep_in.endpointNumber}`
		);
		await device.claimInterface(this.interface_number);
		this.log("interface claimed, resetting PICOBOOT state (0x41)");
		await device.controlTransferOut({
			requestType: "vendor",
			recipient: "interface",
			request: 0x41,
			value: 0,
			index: this.interface_number,
		});
	}

	async close() {
		this.log("releasing interface");
		try {
			await this.device.releaseInterface(this.interface_number);
		} catch (e) {
			// the board already rebooted
		}
		try {
			await this.device.close();
		} catch (e) {
			// same
		}
	}

	async status_text() {
		try {
			const r = await this.device.controlTransferIn(
				{
					requestType: "vendor",
					recipient: "interface",
					request: 0x42,
					value: 0,
					index: this.interface_number,
				},
				16
			);
			return `status ${r.data.getUint32(4, true)}, command ${r.data.getUint8(8)}`;
		} catch (e) {
			return "";
		}
	}

	check(result, what) {
		if (result.status !== "ok") {
			this.log(`${what} failed: ${result.status}`, "error");
			throw new Error(`${what}: ${result.status}`);
		}
		return result;
	}

	async command(id, size, args, length, out_data) {
		const buffer = new ArrayBuffer(32);
		const view = new DataView(buffer);
		view.setUint32(0, PICOBOOT_MAGIC, true);
		view.setUint32(4, this.token++, true);
		view.setUint8(8, id);
		view.setUint8(9, size);
		view.setUint32(12, length || 0, true);
		(args || []).forEach((a, i) => view.setUint32(16 + i * 4, a, true));
		if (!length || this.log_all) {
			const name = PICOBOOT_COMMANDS[id] || id;
			this.log(
				`cmd ${name} args [${(args || []).map((a) => "0x" + a.toString(16)).join(", ")}] length ${
					length || 0
				}`
			);
		}

		try {
			this.check(await this.device.transferOut(this.ep_out.endpointNumber, buffer), "command");
			if (!length) {
				this.check(await this.device.transferIn(this.ep_in.endpointNumber, 1), "ack");
				return null;
			}
			if (out_data) {
				this.check(await this.device.transferOut(this.ep_out.endpointNumber, out_data), "write");
				this.check(await this.device.transferIn(this.ep_in.endpointNumber, 1), "ack");
				return null;
			}
			const result = this.check(
				await this.device.transferIn(this.ep_in.endpointNumber, length),
				"read"
			);
			this.check(await this.device.transferOut(this.ep_out.endpointNumber, new ArrayBuffer(0)), "ack");
			return new Uint8Array(result.data.buffer, result.data.byteOffset, result.data.byteLength);
		} catch (e) {
			throw new Error(`${e.message} (${await this.status_text()})`);
		}
	}

	async flash(image, progress) {
		const { start, data } = image;
		this.log(`image: 0x${start.toString(16)} + ${data.length} bytes`);
		await this.command(1, 1, [1]);
		await this.command(6, 0);
		this.log("erasing flash (can take a few seconds)");
		await this.command(3, 8, [start, data.length]);
		this.log("erase done");

		let written = 0;
		for (let off = 0; off < data.length; off += PICOBOOT_SECTOR) {
			const chunk = data.subarray(off, off + PICOBOOT_SECTOR);
			if (chunk.every((b) => b === 0xff)) continue;
			await this.command(5, 8, [start + off, chunk.length], chunk.length, chunk.slice());
			written++;
			if (written % 32 === 1)
				this.log(`written ${written} blocks, now at 0x${(start + off).toString(16)}`);
			progress("write", off / data.length);
		}
		this.log(`write done: ${written} non-empty blocks of ${data.length / PICOBOOT_SECTOR}`);

		await this.command(7, 0);
		this.log("reading flash back to verify");
		for (let off = 0; off < data.length; off += PICOBOOT_SECTOR) {
			const want = data.subarray(off, off + PICOBOOT_SECTOR);
			const got = await this.command(4, 8, [start + off, want.length], want.length);
			for (let i = 0; i < want.length; i++) {
				if (got[i] !== want[i]) {
					throw new Error(
						__("Verification failed at {0}", ["0x" + (start + off + i).toString(16)])
					);
				}
			}
			progress("verify", off / data.length);
		}
		this.log("verify OK: flash matches the image", "ok");
	}

	async reboot() {
		try {
			await this.command(2, 12, [0, 0x20042000, 100]);
		} catch (e) {
			this.log(`reboot ack not received (expected, the board left the bus): ${e.message}`);
		}
	}
}

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
		this.flashing = false;
		this.usb_device = null;
		this.skip_device = null;
		this.auto = localStorage.getItem("firmware_flashing_auto") === "1";
		this.log_lines = [];
		this.setup_usb();

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

	log(message, level) {
		const stamp = new Date().toLocaleTimeString("en-GB", { hour12: false });
		const ms = String(new Date().getMilliseconds()).padStart(3, "0");
		this.log_lines.push({ text: `${stamp}.${ms}  ${message}`, level: level || "" });
		if (this.log_lines.length > 400) this.log_lines.shift();
		if (!this.$log) return;
		const el = this.$log[0];
		const stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 20;
		this.$log.append(this.log_line_html(this.log_lines[this.log_lines.length - 1]));
		while (this.$log.children().length > 400) this.$log.children().first().remove();
		if (stick) el.scrollTop = el.scrollHeight;
	}

	log_line_html(line) {
		const color =
			line.level === "error" ? "var(--red-600)" : line.level === "ok" ? "var(--green-600)" : "inherit";
		return $("<div></div>").css({ color, "white-space": "pre-wrap" }).text(line.text);
	}

	render_log() {
		const $card = $(`
			<div class="frappe-card" style="padding:12px 20px;margin-top:15px;">
				<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
					<b>${__("Live log")}</b>
					<span class="text-muted" style="font-size:12px;">${__("Not stored. Gone on reload")}</span>
					<button class="btn btn-default btn-xs btn-clear-log">${__("Clear")}</button>
				</div>
				<div class="flash-log" style="font-family:monospace;font-size:12px;max-height:260px;overflow:auto;"></div>
			</div>
		`).appendTo(this.$root);
		this.$log = $card.find(".flash-log");
		this.log_lines.forEach((l) => this.$log.append(this.log_line_html(l)));
		this.$log[0].scrollTop = this.$log[0].scrollHeight;
		$card.find(".btn-clear-log").on("click", () => {
			this.log_lines = [];
			this.$log.empty();
		});
	}

	setup_usb() {
		if (!navigator.usb) {
			this.log("WebUSB is not available in this browser (use Chrome or Edge over HTTPS)", "error");
			return;
		}
		this.log("WebUSB available");
		this.on_usb_connect = (e) => {
			this.log(`USB connect event: ${describe_device(e.device)}`);
			this.board_seen(e.device);
		};
		this.on_usb_disconnect = (e) => {
			this.log(`USB disconnect event: ${describe_device(e.device)}`);
			if (e.device === this.usb_device) this.usb_device = null;
			if (e.device === this.skip_device) this.skip_device = null;
			this.render_usb_bar();
		};
		navigator.usb.addEventListener("connect", this.on_usb_connect);
		navigator.usb.addEventListener("disconnect", this.on_usb_disconnect);
		navigator.usb.getDevices().then((devices) => {
			this.log(
				`already permitted devices: ${
					devices.length ? devices.map(describe_device).join("; ") : "none"
				}`
			);
			const board = devices.find((d) => this.is_bootsel(d));
			if (board) this.board_seen(board);
		});
	}

	alive() {
		if (this.$root.closest("body").length) return true;
		navigator.usb.removeEventListener("connect", this.on_usb_connect);
		navigator.usb.removeEventListener("disconnect", this.on_usb_disconnect);
		return false;
	}

	is_bootsel(device) {
		return device.vendorId === BOOTSEL_FILTER.vendorId && device.productId === BOOTSEL_FILTER.productId;
	}

	board_seen(device) {
		if (!this.alive()) return;
		if (!this.is_bootsel(device)) {
			this.log(`ignoring ${describe_device(device)}: not a BOOTSEL board (need 2e8a:0003)`);
			return;
		}
		this.log(`BOOTSEL board ready: ${describe_device(device)}`, "ok");
		this.usb_device = device;
		this.render_usb_bar();
		this.try_auto();
	}

	async connect_board() {
		try {
			this.log("opening the USB device picker");
			const device = await navigator.usb.requestDevice({ filters: [BOOTSEL_FILTER] });
			this.board_seen(device);
		} catch (e) {
			this.log(`device picker: ${e.message || e}`);
		}
	}

	render_usb_bar() {
		if (!navigator.usb) return;
		if (!this.$usb_bar) {
			this.$usb_bar = $('<div class="usb-bar" style="margin-bottom:15px;"></div>');
		}
		this.$usb_bar.prependTo(this.$root);
		const connected = !!this.usb_device;
		this.$usb_bar.html(`
			<div class="frappe-card" style="padding:12px 20px;display:flex;gap:16px;align-items:center;flex-wrap:wrap;">
				<span style="color:${connected ? "var(--green-600)" : "var(--text-muted)"};">
					<i class="fa fa-usb"></i>
					${connected ? __("Board in BOOTSEL mode connected") : __("Waiting for a board in BOOTSEL mode")}
				</span>
				<button class="btn btn-default btn-xs btn-connect">${__("Connect board")}</button>
				<label style="margin:0;display:flex;gap:6px;align-items:center;">
					<input type="checkbox" class="chk-auto" ${this.auto ? "checked" : ""}>
					${__("Flash automatically when a board is connected")}
				</label>
			</div>
		`);
		this.$usb_bar.find(".btn-connect").on("click", () => this.connect_board());
		this.$usb_bar.find(".chk-auto").on("change", (e) => {
			this.auto = e.target.checked;
			this.log(`auto flash ${this.auto ? "on" : "off"}`);
			localStorage.setItem("firmware_flashing_auto", this.auto ? "1" : "0");
			this.try_auto();
		});
	}

	async try_auto() {
		if (!this.auto || !this.usb_device || !this.alive()) return;
		const reason = this.flashing
			? "a flash is already running"
			: this.usb_device === this.skip_device
			? "this board was already handled, replug it to flash again"
			: !this.$root.is(":visible")
			? "page is not visible"
			: "";
		if (reason) {
			this.log(`auto flash skipped: ${reason}`);
			return;
		}
		const device = this.usb_device;
		this.flashing = true;
		this.log("auto flash started");
		try {
			let c = this.current;
			if (!c) {
				this.log("taking the next board from the queue");
				c = await frappe.xcall(FLASH_API + ".next_board", { workplace: this.workplace || null });
				this.current = c;
				await this.refresh();
			}
			await this.flash_usb(c, device);
		} catch (e) {
			this.skip_device = device;
			const message = (e && (e.message || e._server_messages)) || String(e);
			this.log(`auto flash failed: ${message}`, "error");
			if (this.$status) this.set_status(message, "var(--red-600)");
			else frappe.show_alert({ message: String(message), indicator: "red" });
		} finally {
			this.flashing = false;
		}
	}

	async flash_usb(c, device) {
		if (!this.$status) await this.refresh();
		this.skip_device = device;
		this.log(
			`flashing ${c.board_serial} (${c.serial_no}), ${c.firmware} ${c.version}, job card ${c.job_card}`
		);
		this.set_status(__("Building the image…"));
		const raw = await this.fetch_image(c);
		this.log(`image from server: ${raw.byteLength} bytes (${raw.byteLength / 512} UF2 blocks)`);
		const image = uf2_to_flash(raw);
		const board = new Picoboot(device, (m, l) => this.log(m, l));
		await board.open();
		try {
			await board.flash(image, (phase, done) => {
				const label = phase === "write" ? __("Writing") : __("Verifying");
				this.set_status(`${label} ${Math.round(done * 100)}%`);
			});
			this.set_status(__("Restarting the board…"));
			await board.reboot();
		} finally {
			await board.close();
		}
		this.log("confirming on the server, closing the Job Card");
		await this.confirm(c, "USB", null);
		this.log(`${c.board_serial} done`, "ok");
	}

	async flash_usb_manual(c) {
		if (this.flashing) return;
		let device = this.usb_device;
		if (!device) {
			try {
				device = await navigator.usb.requestDevice({ filters: [BOOTSEL_FILTER] });
			} catch (e) {
				return;
			}
			this.usb_device = device;
		}
		this.flashing = true;
		try {
			await this.flash_usb(c, device);
		} catch (e) {
			this.log(`flash failed: ${e.message || e}`, "error");
			this.set_status(e.message || String(e), "var(--red-600)");
		} finally {
			this.flashing = false;
		}
	}

	refresh() {
		return frappe.call({
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
		this.render_usb_bar();
		if (this.current) {
			this.render_board(this.current);
		} else {
			this.render_start(data);
		}
		this.render_tables(data);
		this.render_log();
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
		const can_usb = !!navigator.usb;
		const can_serial = !!navigator.serial && c.verify_mode === "Console";
		const $box = $(`
			<div class="frappe-card" style="padding:20px;margin-bottom:15px;">
				<div class="text-muted">${esc(c.item_name || c.item_code)} · ${__("Job Card")} ${esc(c.job_card)}</div>
				<div style="font-size:32px;font-weight:600;letter-spacing:1px;margin:6px 0;">${esc(c.board_serial)}</div>
				<div class="text-muted" style="margin-bottom:6px;">${__("Serial No")}: ${esc(c.serial_no)}</div>
				<div style="margin-bottom:12px;">
					<i class="fa fa-file-code-o"></i> ${esc(c.firmware)} <b>${esc(c.version)}</b>
					<span class="text-muted" style="margin-left:8px;">SHA-256 ${esc((c.sha256 || "").slice(0, 12))}…</span>
				</div>
				<div class="flash-instructions" style="margin-bottom:15px;">${c.instructions || ""}</div>
				<div class="flash-actions" style="display:flex;gap:8px;flex-wrap:wrap;">
					${
						can_usb
							? `<button class="btn btn-primary btn-usb"><i class="fa fa-usb"></i> ${__(
									"Flash over USB"
							  )}</button>`
							: ""
					}
					${
						can_write
							? `<button class="btn btn-default btn-write"><i class="fa fa-usb"></i> ${__(
									"Write to board"
							  )}</button>`
							: ""
					}
					<button class="btn btn-default btn-download"><i class="fa fa-download"></i> ${__("Download UF2")}</button>
					${
						can_serial
							? `<button class="btn btn-default btn-verify"><i class="fa fa-plug"></i> ${__(
									"Verify via console"
							  )}</button>`
							: ""
					}
					<button class="btn btn-success btn-confirm"><i class="fa fa-check"></i> ${__(
						"Board shows this serial"
					)}</button>
					<button class="btn btn-danger btn-fail"><i class="fa fa-times"></i> ${__("Failed")}</button>
					<button class="btn btn-default btn-release">${__("Put back")}</button>
				</div>
				<div class="flash-status text-muted" style="margin-top:12px;"></div>
			</div>
		`).appendTo(this.$root);

		this.$status = $box.find(".flash-status");
		$box.find(".btn-usb").on("click", () => this.flash_usb_manual(c));
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
				__("The board did not report {0}. Reset it and try again, or confirm from the screen", [
					c.verify_pattern,
				]),
				"var(--red-600)"
			);
			return;
		}
		this.confirm(c, "Console", found.trim());
	}

	confirm(c, verified_by, console_line) {
		return frappe.call({
			method: FLASH_API + ".confirm",
			args: { attempt: c.attempt, verified_by, console_line },
			freeze: !this.flashing,
			callback: () => {
				frappe.show_alert({
					message: __("{0} flashed. Stick the label {0}", [c.board_serial]),
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
		$("<h5></h5>").text(__("Waiting")).appendTo($waiting);
		new erpnext.DataTable({
			parent: $waiting,
			storage_key: "firmware-flashing-waiting",
			max_height: "240px",
			rows: data.waiting || [],
			columns: [
				{ key: "item_code", label: __("Item"), pin: true, html: (r) => esc(r.item_code) },
				{ key: "firmware", label: __("Firmware"), html: (r) => esc(r.firmware) },
				{ key: "version", label: __("Version"), html: (r) => esc(r.version || "—") },
				{
					key: "count",
					label: __("Boards"),
					align: "right",
					value: (r) => flt(r.count),
					html: (r) => r.count,
				},
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
				{
					key: "board_serial",
					label: __("Board Serial"),
					pin: true,
					html: (r) => esc(r.board_serial || ""),
				},
				{ key: "serial_no", label: __("Serial No"), html: (r) => esc(r.serial_no) },
				{ key: "status", label: __("Status"), html: (r) => esc(__(r.status)) },
				{ key: "firmware_version", label: __("Version"), html: (r) => esc(r.firmware_version || "") },
				{
					key: "verified_by",
					label: __("Verified By"),
					html: (r) => esc(r.verified_by ? __(r.verified_by) : ""),
				},
				{
					key: "owner",
					label: __("Operator"),
					html: (r) => erpnext.entity.user(r.owner, { size: 18 }),
				},
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
