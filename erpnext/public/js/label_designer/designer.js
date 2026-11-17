frappe.provide("erpnext.label_designer");

const LD_PALETTE = [
	{ type: "text", icon: "fa fa-font", label: __("Text") },
	{ type: "field", icon: "fa fa-database", label: __("Field") },
	{ type: "input", icon: "fa fa-keyboard-o", label: __("Input") },
	{ type: "image", icon: "fa fa-picture-o", label: __("Image") },
	{ type: "barcode", icon: "fa fa-barcode", label: __("Barcode") },
	{ type: "qr", icon: "fa fa-qrcode", label: __("QR Code") },
	{ type: "table", icon: "fa fa-table", label: __("Table") },
	{ type: "repeat", icon: "fa fa-th-list", label: __("Repeat") },
	{ type: "line", icon: "fa fa-minus", label: __("Line") },
	{ type: "rect", icon: "fa fa-square-o", label: __("Box") },
];

const LD_DEFAULTS = {
	text: () => ({ w: 30, h: 6, text: __("Text"), style: { font_size_pt: 10 } }),
	field: () => ({ w: 30, h: 6, field: "name", style: { font_size_pt: 10 } }),
	input: () => ({ w: 30, h: 6, input: "", style: { font_size_pt: 10 } }),
	image: () => ({ w: 15, h: 15, file: "", fit: "contain" }),
	barcode: () => ({
		w: 40,
		h: 12,
		source: "field",
		field: "name",
		barcode_type: "code128",
		module_width: 0.2,
		show_text: 1,
		style: { font_size_pt: 7 },
	}),
	qr: () => ({ w: 15, h: 15, source: "field", field: "name", module_size: 4 }),
	repeat: () => ({
		w: 40,
		h: 30,
		list: "items",
		value: "serial_no",
		show: "barcode",
		show_text: 1,
		barcode_type: "code128",
		module_width: 0.3,
		module_size: 4,
		item_h: 9,
		columns: 1,
		gap_mm: 1,
		max_items: 0,
		style: { font_size_pt: 7 },
	}),
	table: () => ({
		w: 50,
		h: 12,
		cols: [20, 30],
		cell_padding_mm: 0.5,
		loop: "",
		rows: [
			{ h: 0, cells: [{ text: __("Name") }, { text: "{{ doc.name }}" }] },
			{ h: 0, cells: [{ text: "" }, { text: "" }] },
		],
		style: { font_size_pt: 8, border_mm: 0.3 },
	}),
	line: () => ({ w: 40, h: 0.4 }),
	rect: () => ({ w: 30, h: 15, fill: 0, radius_mm: 0, style: { border_mm: 0.3 } }),
};

const LD_FONTS = ["DejaVu Sans", "DejaVu Serif", "DejaVu Sans Mono"];
const LD_FONT_ALIASES = {
	Arial: "DejaVu Sans",
	"DejaVu Sans Condensed": "DejaVu Sans",
	Monospace: "DejaVu Sans Mono",
};
const LD_FONT_FILES = {
	"DejaVu Sans": ["DejaVuSans", "DejaVuSans-Bold"],
	"DejaVu Serif": ["DejaVuSerif", "DejaVuSerif-Bold"],
	"DejaVu Sans Mono": ["DejaVuSansMono", "DejaVuSansMono-Bold"],
};
const LD_DOTS_PER_MM = 300 / 25.4;
const ld_font_mm = (pt) => Math.max(1, Math.round(flt(pt || 10) * (300 / 72))) / LD_DOTS_PER_MM;
const ld_font = (name) => {
	name = LD_FONT_ALIASES[name] || name;
	return LD_FONT_FILES[name] ? name : "DejaVu Sans";
};
const LD_FORMATS = [
	["", __("As is")],
	["upper", __("Upper case")],
	["date", __("Date")],
	["datetime", __("Date and time")],
	["float:0", "0"],
	["float:1", "0.0"],
	["float:2", "0.00"],
	["float:3", "0.000"],
];
const LD_BARCODES = ["code128", "code39", "ean13", "ean8", "upca", "isbn13", "gs1_128"];

const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
const round2 = (n) => Math.round(n * 100) / 100;

function ld_get(obj, path) {
	return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

function ld_set(obj, path, value) {
	const keys = path.split(".");
	let o = obj;
	keys.slice(0, -1).forEach((k) => {
		if (o[k] == null || typeof o[k] !== "object") o[k] = {};
		o = o[k];
	});
	o[keys[keys.length - 1]] = value;
}

erpnext.label_designer.Designer = class LabelDesigner {
	constructor({ wrapper, frm }) {
		this.$wrapper = $(wrapper);
		this.frm = frm;
		this.zoom = 6;
		this.snap = true;
		this.selected = [];
		this.size = { w: 60, h: 40 };
		this.history = [];
		this.history_index = -1;
		this.keys = [];
		this.load_layout();
		this.make();
		this.refresh_size();
		this.refresh_keys();
		this.push_history();
	}

	load_layout() {
		let layout = null;
		try {
			layout = JSON.parse(this.frm.doc.layout_json || "null");
		} catch (e) {
			layout = null;
		}
		this.layout =
			layout && Array.isArray(layout.elements) ? layout : { v: 1, grid_mm: 0.5, elements: [] };
		this.layout.grid_mm = this.layout.grid_mm || 0.5;
	}

	reload_from_doc() {
		const current = JSON.stringify(this.layout);
		if ((this.frm.doc.layout_json || "") === current) return;
		this.load_layout();
		this.selected = [];
		this.history = [];
		this.history_index = -1;
		this.push_history();
		this.render();
	}

	get padding() {
		const d = this.frm.doc;
		return {
			t: flt(d.padding_top_mm),
			r: flt(d.padding_right_mm),
			b: flt(d.padding_bottom_mm),
			l: flt(d.padding_left_mm),
		};
	}

	get content_size() {
		const p = this.padding;
		return { w: this.size.w - p.l - p.r, h: this.size.h - p.t - p.b };
	}

	async refresh_size() {
		const name = this.frm.doc.label_size;
		if (name) {
			const r = await frappe.db.get_value("Label Size", name, ["width_mm", "height_mm"]);
			const v = (r && r.message) || {};
			if (v.width_mm && v.height_mm) this.size = { w: flt(v.width_mm), h: flt(v.height_mm) };
		}
		this.fit_zoom();
		this.render();
	}

	async refresh_keys() {
		const keys = new Map();
		const add = (key, label) => {
			if (key && !keys.has(key)) keys.set(key, label || "");
		};
		add("name", __("Name"));
		const dt = this.frm.doc.reference_doctype;
		this.child_tables = [];
		if (dt) {
			await new Promise((res) => frappe.model.with_doctype(dt, res));
			(frappe.get_meta(dt).fields || []).forEach((f) => {
				if (frappe.model.no_value_type.includes(f.fieldtype)) return;
				if (f.fieldtype === "Table") {
					this.child_tables.push({ fieldname: f.fieldname, label: f.label, options: f.options });
					return;
				}
				add(f.fieldname, __(f.label));
			});
		}
		Object.keys(this.sample_data(true)).forEach((k) => add(k, ""));
		this.setup_keys().forEach((k) => add(k, __("Data setup")));
		this.keys = [...keys.entries()].map(([key, label]) => ({ key, label }));
		this.render_inspector();
	}

	sample_data(only_preview) {
		let data = {};
		try {
			data = JSON.parse(this.frm.doc.preview_data || "{}") || {};
		} catch (e) {
			data = {};
		}
		if (only_preview) return data;
		(this.frm.doc.inputs || []).forEach((row) => {
			if (row.default_value) data[row.fieldname] = row.default_value;
		});
		return data;
	}

	make() {
		this.$wrapper.html(`
			<div class="ld-root" tabindex="0">
				<div class="ld-toolbar">
					<button class="btn btn-xs btn-default" data-action="undo" title="${__(
						"Undo"
					)} (Ctrl+Z)"><i class="fa fa-undo"></i></button>
					<button class="btn btn-xs btn-default" data-action="redo" title="${__(
						"Redo"
					)} (Ctrl+Y)"><i class="fa fa-repeat"></i></button>
					<span class="ld-sep"></span>
					<button class="btn btn-xs btn-default" data-action="zoom_out" title="${__(
						"Zoom out"
					)}"><i class="fa fa-search-minus"></i></button>
					<span class="ld-zoom"></span>
					<button class="btn btn-xs btn-default" data-action="zoom_in" title="${__(
						"Zoom in"
					)}"><i class="fa fa-search-plus"></i></button>
					<button class="btn btn-xs btn-default" data-action="fit" title="${__(
						"Fit"
					)}"><i class="fa fa-arrows-alt"></i></button>
					<span class="ld-sep"></span>
					<label class="ld-snap"><input type="checkbox" data-action="snap" checked> ${__("Snap to grid")}</label>
					<span class="ld-sep"></span>
					<button class="btn btn-xs btn-default" data-action="duplicate" title="${__(
						"Duplicate"
					)} (Ctrl+D)"><i class="fa fa-clone"></i></button>
					<button class="btn btn-xs btn-default" data-action="front" title="${__(
						"Bring to front"
					)}"><i class="fa fa-level-up"></i></button>
					<button class="btn btn-xs btn-default" data-action="back" title="${__(
						"Send to back"
					)}"><i class="fa fa-level-down"></i></button>
					<button class="btn btn-xs btn-default" data-action="delete" title="${__(
						"Delete"
					)} (Del)"><i class="fa fa-trash"></i></button>
					<span class="ld-flex"></span>
					<button class="btn btn-xs btn-default ld-compare-btn" data-action="compare" title="${__(
						"Overlay the printed result (red) on the canvas"
					)}"><i class="fa fa-adjust"></i> ${__("Compare with print")}</button>
					<button class="btn btn-xs btn-default ld-setup-btn" data-action="setup" title="${__(
						"Compute values with Jinja before the elements are drawn"
					)}"><i class="fa fa-cogs"></i> ${__("Data setup")}</button>
					<button class="btn btn-xs btn-default" data-action="html" title="${__(
						"Generated HTML"
					)}"><i class="fa fa-code"></i></button>
					<button class="btn btn-xs btn-primary" data-action="preview"><i class="fa fa-eye"></i> ${__(
						"Exact preview"
					)}</button>
				</div>
				<div class="ld-body">
					<div class="ld-palette">
						<div class="ld-panel-title">${__("Components")}</div>
						${LD_PALETTE.map(
							(p) => `<div class="ld-palette-item" draggable="true" data-type="${p.type}">
								<i class="${p.icon}"></i><span>${p.label}</span></div>`
						).join("")}
						<div class="ld-hint">${__("Drag onto the label or click to add")}</div>
					</div>
					<div class="ld-stage-wrap"><div class="ld-stage"></div></div>
					<div class="ld-inspector"></div>
				</div>
			</div>`);
		this.$root = this.$wrapper.find(".ld-root");
		this.$stage = this.$wrapper.find(".ld-stage");
		this.$stage_wrap = this.$wrapper.find(".ld-stage-wrap");
		this.$inspector = this.$wrapper.find(".ld-inspector");
		this.bind();
	}

	bind() {
		this.$root.on("click", "[data-action]", (e) => {
			const action = $(e.currentTarget).attr("data-action");
			if (action === "snap") {
				this.snap = $(e.currentTarget).is(":checked");
				return;
			}
			this.action(action);
		});

		this.$root.on("click", ".ld-palette-item", (e) => {
			const c = this.content_size;
			const type = $(e.currentTarget).attr("data-type");
			const d = LD_DEFAULTS[type]();
			this.add_element(type, Math.max(0, (c.w - d.w) / 2), Math.max(0, (c.h - d.h) / 2));
		});
		this.$root.on("dragstart", ".ld-palette-item", (e) => {
			e.originalEvent.dataTransfer.setData("text/ld-type", $(e.currentTarget).attr("data-type"));
			e.originalEvent.dataTransfer.effectAllowed = "copy";
		});
		this.$stage.on("dragover", (e) => {
			if ([...e.originalEvent.dataTransfer.types].includes("text/ld-type")) e.preventDefault();
		});
		this.$stage.on("drop", (e) => {
			const type = e.originalEvent.dataTransfer.getData("text/ld-type");
			if (!type || !LD_DEFAULTS[type]) return;
			e.preventDefault();
			const pt = this.point_mm(e.originalEvent);
			this.add_element(type, pt.x, pt.y);
		});

		this.$stage.on("pointerdown", (e) => this.on_pointer_down(e));
		this.$root.on("keydown", (e) => this.on_key(e));

		this.$inspector.on("input change", "[data-path]", (e) => this.on_prop_change(e));
		this.$inspector.on("click", "[data-cmd]", (e) => this.on_inspector_cmd(e));
	}

	point_mm(ev) {
		const rect = this.$stage.find(".ld-content")[0].getBoundingClientRect();
		return {
			x: this.snap_mm((ev.clientX - rect.left) / this.zoom),
			y: this.snap_mm((ev.clientY - rect.top) / this.zoom),
		};
	}

	snap_mm(v) {
		if (!this.snap) return round2(v);
		const g = this.layout.grid_mm || 0.5;
		return round2(Math.round(v / g) * g);
	}

	fit_zoom() {
		const avail = Math.max(240, (this.$stage_wrap.width() || 600) - 40);
		this.zoom = Math.max(2, Math.min(20, Math.floor((avail / this.size.w) * 2) / 2));
	}

	action(action) {
		const sel = this.selected_elements();
		if (action === "undo") return this.undo();
		if (action === "redo") return this.redo();
		if (action === "zoom_in") this.zoom = Math.min(30, this.zoom + 1);
		if (action === "zoom_out") this.zoom = Math.max(1, this.zoom - 1);
		if (action === "fit") this.fit_zoom();
		if (["zoom_in", "zoom_out", "fit"].includes(action)) return this.render();
		if (action === "preview") return this.exact_preview();
		if (action === "compare") return this.toggle_compare();
		if (action === "html") return this.show_html();
		if (action === "setup") return this.edit_setup();
		if (!sel.length) return;
		const els = this.layout.elements;
		if (action === "delete") {
			this.layout.elements = els.filter((el) => !this.selected.includes(el.id));
			this.selected = [];
		}
		if (action === "duplicate") {
			const copies = sel.map((el) => ({
				...JSON.parse(JSON.stringify(el)),
				id: frappe.utils.get_random(8),
				x: round2(el.x + 2),
				y: round2(el.y + 2),
			}));
			els.push(...copies);
			this.selected = copies.map((c) => c.id);
		}
		if (action === "front") {
			this.layout.elements = [...els.filter((el) => !sel.includes(el)), ...sel];
		}
		if (action === "back") {
			this.layout.elements = [...sel, ...els.filter((el) => !sel.includes(el))];
		}
		this.commit();
	}

	add_element(type, x, y) {
		const el = { id: frappe.utils.get_random(8), type, x: 0, y: 0, rotate: 0, ...LD_DEFAULTS[type]() };
		if (type === "input") {
			const first = (this.frm.doc.inputs || [])[0];
			el.input = first ? first.fieldname : "";
		}
		el.x = this.snap_mm(x);
		el.y = this.snap_mm(y);
		this.layout.elements.push(el);
		this.selected = [el.id];
		this.commit();
		this.$root.trigger("focus");
		if (type === "image") this.choose_image(el);
	}

	selected_elements() {
		return this.layout.elements.filter((el) => this.selected.includes(el.id));
	}

	commit() {
		this.push_history();
		this.save();
		this.render();
		this.schedule_compare();
	}

	save() {
		const value = JSON.stringify(this.layout);
		if (this.frm.doc.layout_json !== value) {
			this._own_change = true;
			this.frm.set_value("layout_json", value).then(() => {
				this._own_change = false;
			});
		}
	}

	push_history() {
		const snap = JSON.stringify(this.layout);
		if (this.history[this.history_index] === snap) return;
		this.history = this.history.slice(0, this.history_index + 1);
		this.history.push(snap);
		if (this.history.length > 100) this.history.shift();
		this.history_index = this.history.length - 1;
	}

	undo() {
		if (this.history_index <= 0) return;
		this.history_index--;
		this.restore();
	}

	redo() {
		if (this.history_index >= this.history.length - 1) return;
		this.history_index++;
		this.restore();
	}

	restore() {
		this.layout = JSON.parse(this.history[this.history_index]);
		const ids = this.layout.elements.map((el) => el.id);
		this.selected = this.selected.filter((id) => ids.includes(id));
		this.save();
		this.render();
	}

	on_key(e) {
		if ($(e.target).is("input, textarea, select")) return;
		const ctrl = e.ctrlKey || e.metaKey;
		if (ctrl && e.key.toLowerCase() === "z") {
			e.preventDefault();
			return e.shiftKey ? this.redo() : this.undo();
		}
		if (ctrl && e.key.toLowerCase() === "y") {
			e.preventDefault();
			return this.redo();
		}
		if (ctrl && e.key.toLowerCase() === "d") {
			e.preventDefault();
			return this.action("duplicate");
		}
		if (!this.selected.length) return;
		if (e.key === "Delete" || e.key === "Backspace") {
			e.preventDefault();
			return this.action("delete");
		}
		const step = e.shiftKey ? 5 : this.layout.grid_mm || 0.5;
		const delta = {
			ArrowLeft: [-step, 0],
			ArrowRight: [step, 0],
			ArrowUp: [0, -step],
			ArrowDown: [0, step],
		}[e.key];
		if (!delta) return;
		e.preventDefault();
		this.selected_elements().forEach((el) => {
			el.x = round2(el.x + delta[0]);
			el.y = round2(el.y + delta[1]);
		});
		this.commit();
	}

	on_pointer_down(e) {
		if (e.button !== 0) return;
		const $handle = $(e.target).closest(".ld-handle");
		const $el = $(e.target).closest(".ld-el");
		this.$root.trigger("focus");

		if (!$el.length) {
			if (this.selected.length) {
				this.selected = [];
				this.render();
			}
			return;
		}
		const id = $el.attr("data-id");
		if (e.shiftKey) {
			this.selected = this.selected.includes(id)
				? this.selected.filter((s) => s !== id)
				: [...this.selected, id];
			this.render();
			return;
		}
		if (!this.selected.includes(id)) {
			this.selected = [id];
			this.render();
		}
		e.preventDefault();

		const start = { x: e.clientX, y: e.clientY };
		const handle = $handle.length ? $handle.attr("data-handle") : null;
		const originals = this.selected_elements().map((el) => ({ el, x: el.x, y: el.y, w: el.w, h: el.h }));
		let moved = false;

		const on_move = (ev) => {
			const dx = (ev.clientX - start.x) / this.zoom;
			const dy = (ev.clientY - start.y) / this.zoom;
			if (!moved && Math.abs(dx) + Math.abs(dy) < 0.2) return;
			moved = true;
			originals.forEach((o) => {
				if (!handle) {
					o.el.x = this.snap_mm(o.x + dx);
					o.el.y = this.snap_mm(o.y + dy);
				} else {
					this.apply_resize(o, handle, dx, dy);
				}
				this.position_dom(o.el);
			});
			this.update_geometry_inputs();
		};
		const on_up = () => {
			document.removeEventListener("pointermove", on_move);
			document.removeEventListener("pointerup", on_up);
			if (moved) this.commit();
		};
		document.addEventListener("pointermove", on_move);
		document.addEventListener("pointerup", on_up);
	}

	apply_resize(o, handle, dx, dy) {
		const min = 0.2;
		let { x, y, w, h } = o;
		if (handle.includes("e")) w = Math.max(min, this.snap_mm(o.x + o.w + dx) - o.x);
		if (handle.includes("s")) h = Math.max(min, this.snap_mm(o.y + o.h + dy) - o.y);
		if (handle.includes("w")) {
			x = Math.min(this.snap_mm(o.x + dx), o.x + o.w - min);
			w = o.x + o.w - x;
		}
		if (handle.includes("n")) {
			y = Math.min(this.snap_mm(o.y + dy), o.y + o.h - min);
			h = o.y + o.h - y;
		}
		Object.assign(o.el, { x: round2(x), y: round2(y), w: round2(w), h: round2(h) });
	}

	position_dom(el) {
		const $el = this.$stage.find(`.ld-el[data-id="${el.id}"]`);
		$el.css(this.box_css(el));
		if (["qr", "table", "repeat"].includes(el.type)) $el.find(".ld-el-inner").html(this.inner_html(el));
	}

	box_css(el) {
		const z = this.zoom;
		return {
			left: el.x * z + "px",
			top: el.y * z + "px",
			width: Math.max(1, el.w * z) + "px",
			height: Math.max(1, el.h * z) + "px",
			transform: el.rotate ? `rotate(${el.rotate}deg)` : "",
		};
	}

	render() {
		const z = this.zoom;
		const p = this.padding;
		const grid = (this.layout.grid_mm || 0.5) * z;
		const big = grid * (z >= 6 ? 10 : 20);
		this.$root.find(".ld-zoom").text(`${Math.round((z / 3.78) * 100)}%`);
		const els = this.layout.elements
			.map((el) => {
				const sel = this.selected.includes(el.id);
				const handles =
					sel && this.selected.length === 1
						? ["nw", "n", "ne", "e", "se", "s", "sw", "w"]
								.map((h) => `<div class="ld-handle ld-h-${h}" data-handle="${h}"></div>`)
								.join("")
						: "";
				const css = this.box_css(el);
				const style = Object.entries(css)
					.map(([k, v]) => `${k}:${v}`)
					.join(";");
				return `<div class="ld-el ld-type-${el.type} ${sel ? "ld-selected" : ""}" data-id="${
					el.id
				}" style="${style}"><div class="ld-el-inner">${this.inner_html(el)}</div>${handles}</div>`;
			})
			.join("");
		this.$stage.html(`
			<div class="ld-label" style="width:${this.size.w * z}px;height:${this.size.h * z}px;">
				<div class="ld-content" style="left:${p.l * z}px;top:${p.t * z}px;right:${p.r * z}px;bottom:${
			p.b * z
		}px;background-size:${big}px ${big}px, ${big}px ${big}px, ${grid}px ${grid}px, ${grid}px ${grid}px;">
					${els}
				</div>
				${this.compare && this.compare_url ? `<img class="ld-compare" src="${this.compare_url}">` : ""}
			</div>
			<div class="ld-size-note">${this.size.w} × ${this.size.h} ${__("mm")}${
			this.compare ? ` · <span class="ld-compare-note">${__("Red = printed result")}</span>` : ""
		}</div>`);
		this.render_inspector();
		this.check_overflow();
	}

	check_overflow() {
		const run = () => {
			this.overflowing = new Set();
			this.$stage.find(".ld-el").each((_i, node) => {
				const el = this.layout.elements.find((e) => e.id === node.dataset.id);
				if (!el || !["text", "field", "input", "table", "barcode", "repeat"].includes(el.type))
					return;
				const inner = node.querySelector(".ld-el-inner");
				const content = inner.firstElementChild;
				if (!content) return;
				if (el.type === "repeat") {
					const n = this.repeat_sample(el).length;
					const rows = Math.ceil(n / Math.max(1, cint(el.columns) || 1));
					const over_r =
						rows * (flt(el.item_h) + flt(el.gap_mm)) - flt(el.gap_mm) > flt(el.h) + 0.01;
					node.classList.toggle("ld-overflow", over_r);
					if (over_r) this.overflowing.add(el.id);
					return;
				}
				const over =
					content.scrollWidth > inner.clientWidth + 1 ||
					content.scrollHeight > inner.clientHeight + 1 ||
					[...content.querySelectorAll("td")].some(
						(td) => td.scrollWidth > td.clientWidth + 1 || td.scrollHeight > td.clientHeight + 1
					);
				node.classList.toggle("ld-overflow", over);
				if (over) this.overflowing.add(el.id);
			});
			const sel = this.selected_elements();
			this.$inspector
				.find(".ld-overflow-warn")
				.toggle(sel.length === 1 && this.overflowing.has(sel[0].id));
		};
		if (document.fonts && document.fonts.ready) document.fonts.ready.then(run);
		else run();
	}

	toggle_compare() {
		this.compare = !this.compare;
		this.$root.find(".ld-compare-btn").toggleClass("btn-primary", this.compare);
		if (this.compare) this.refresh_compare();
		else this.render();
	}

	schedule_compare() {
		if (!this.compare) return;
		clearTimeout(this._compare_timer);
		this._compare_timer = setTimeout(() => this.refresh_compare(), 700);
	}

	refresh_compare() {
		const seq = (this._compare_seq = (this._compare_seq || 0) + 1);
		frappe
			.call({
				method: "erpnext.devices.doctype.label_template.label_template.render_template_preview",
				args: { doc: erpnext.label_designer.form_payload(this.frm), sample: 1 },
			})
			.then((r) => {
				if (seq !== this._compare_seq || !this.compare || !r.message) return;
				return erpnext.label_designer.tint_ink(r.message.image_base64);
			})
			.then((url) => {
				if (!url || seq !== this._compare_seq) return;
				this.compare_url = url;
				this.render();
			});
	}

	sample_text(text, scope_row) {
		const data = this.sample_data();
		return esc(
			String(text || "")
				.replace(/\*\*([\s\S]+?)\*\*/g, "\u0001$1\u0002")
				.replace(/\^\^([\s\S]+?)\^\^/g, "\u0003$1\u0004")
		)
			.replace(/\{\{(.*?)\}\}/g, (m, expr) => {
				const match =
					expr.trim().match(/^(doc|row)\.([^\s|()]+)/) || expr.trim().match(/^([^\s|()]+)$/);
				const scope = match && match.length === 3 ? match[1] : "doc";
				const key = match ? match[match.length - 1] : expr.trim();
				if (scope === "doc" && data[key] != null && data[key] !== "") return esc(data[key]);
				return `<span class="ld-ph">${esc(scope_row && scope === "row" ? "↻ " + key : key)}</span>`;
			})
			.replace(/\n/g, "<br>")
			.replace(/\u0001/g, "<b>")
			.replace(/\u0002/g, "</b>")
			.replace(/\u0003/g, '<sup style="font-size:50%;vertical-align:super;line-height:0">')
			.replace(/\u0004/g, "</sup>");
	}

	text_css(style) {
		style = style || {};
		const fs = ld_font_mm(style.font_size_pt) * this.zoom;
		return [
			`font-family:'LD ${ld_font(style.font_family)}'`,
			`font-size:${fs}px`,
			`line-height:${style.line_height || 1.15}`,
			`text-align:${style.align || "left"}`,
			`vertical-align:${style.valign || "top"}`,
			`font-weight:${style.bold ? "bold" : "normal"}`,
			`font-style:${style.italic ? "italic" : "normal"}`,
			style.underline ? "text-decoration:underline" : "",
			style.invert ? "color:#fff;background:#000" : "color:#000",
			style.nowrap ? "white-space:nowrap" : "overflow-wrap:break-word",
		]
			.filter(Boolean)
			.join(";");
	}

	cell(inner, style) {
		const b = flt((style || {}).border_mm) * this.zoom;
		const border = b ? `border:${Math.max(1, b)}px solid #000;` : "";
		return `<table class="ld-cell" style="${border}"><tr><td style="${this.text_css(
			style
		)}">${inner}</td></tr></table>`;
	}

	value_html(el, key) {
		const data = this.sample_data();
		const val = data[key];
		const shown =
			val != null && val !== ""
				? esc(el.format === "upper" ? String(val).toUpperCase() : val)
				: `<span class="ld-ph">${esc(key || __("not set"))}</span>`;
		return this.sample_text(el.prefix || "") + shown + this.sample_text(el.suffix || "");
	}

	inner_html(el) {
		const style = el.style || {};
		const z = this.zoom;
		if (el.type === "text") return this.cell(this.sample_text(el.text), style);
		if (el.type === "field") return this.cell(this.value_html(el, el.field), style);
		if (el.type === "input") {
			const row = (this.frm.doc.inputs || []).find((r) => r.fieldname === el.input);
			const inner = row
				? row.default_value
					? esc(row.default_value)
					: `<span class="ld-ph ld-ph-input">${esc(row.label || row.fieldname)}</span>`
				: `<span class="ld-ph ld-ph-input">${__("Choose input")}</span>`;
			return this.cell(
				this.sample_text(el.prefix || "") + inner + this.sample_text(el.suffix || ""),
				style
			);
		}
		if (el.type === "image") {
			const url = el.file_url || (el.file ? `/files/${encodeURIComponent(el.file)}` : "");
			if (!url) return `<div class="ld-empty"><i class="fa fa-picture-o"></i></div>`;
			const fit = el.fit === "stretch" ? "fill" : "contain";
			return `<img src="${esc(url)}" style="width:100%;height:100%;object-fit:${fit};">`;
		}
		if (el.type === "barcode") {
			const data = el.source === "text" ? this.sample_text(el.data) : this.value_html({}, el.field);
			const text = el.show_text
				? `<div style="${this.text_css({ ...style, align: "center", nowrap: 1 })}">${data}</div>`
				: "";
			return `<div class="ld-barcode-wrap"><div class="ld-barcode"></div>${text}</div>`;
		}
		if (el.type === "qr") {
			const side = Math.min(el.w, el.h) * z;
			return `<div class="ld-qr" style="width:${side}px;height:${side}px;"></div>`;
		}
		if (el.type === "table") return this.table_html(el);
		if (el.type === "repeat") return this.repeat_html(el);
		if (el.type === "line") return `<div style="width:100%;height:100%;background:#000;"></div>`;
		if (el.type === "rect") {
			const b = Math.max(1, flt(style.border_mm) * z);
			return `<div style="width:100%;height:100%;box-sizing:border-box;border:${
				flt(style.border_mm) ? b : 0
			}px solid #000;border-radius:${flt(el.radius_mm) * z}px;${
				el.fill ? "background:#000;" : ""
			}"></div>`;
		}
		return "";
	}

	repeat_sample(el) {
		const list = this.sample_data()[el.list];
		const items = Array.isArray(list) && list.length ? list : [null, null, null];
		return cint(el.max_items) ? items.slice(0, cint(el.max_items)) : items;
	}

	repeat_html(el) {
		const z = this.zoom;
		const cols = Math.max(1, cint(el.columns) || 1);
		const gap = flt(el.gap_mm);
		const item_h = Math.max(0.5, flt(el.item_h) || 10);
		const item_w = Math.max(0.5, (flt(el.w) - gap * (cols - 1)) / cols);
		const style = el.style || {};
		const key = el.value || ".";
		return this.repeat_sample(el)
			.map((item, i) => {
				let val = item == null ? null : key === "." ? item : item[key];
				const shown =
					val != null && val !== "" && typeof val !== "object"
						? esc(val)
						: `<span class="ld-ph">↻ ${esc(key === "." ? el.list : key)}</span>`;
				let inner;
				if (el.show === "text") {
					inner = this.cell(
						this.sample_text(el.prefix || "") + shown + this.sample_text(el.suffix || ""),
						style
					);
				} else if (el.show === "qr") {
					const side = Math.min(item_w, item_h) * z;
					inner = `<div class="ld-qr" style="width:${side}px;height:${side}px;"></div>`;
				} else {
					const text = el.show_text
						? `<div style="${this.text_css({
								...style,
								align: "center",
								nowrap: 1,
						  })}">${shown}</div>`
						: "";
					inner = `<div class="ld-barcode-wrap"><div class="ld-barcode"></div>${text}</div>`;
				}
				const left = (i % cols) * (item_w + gap) * z;
				const top = Math.floor(i / cols) * (item_h + gap) * z;
				return `<div class="ld-repeat-item" style="left:${left}px;top:${top}px;width:${
					item_w * z
				}px;height:${item_h * z}px;">${inner}</div>`;
			})
			.join("");
	}

	table_html(el) {
		const style = el.style || {};
		const cols = (el.cols || []).map(flt);
		const total = cols.reduce((a, b) => a + b, 0) || 1;
		const b = flt(style.border_mm) ? Math.max(1, flt(style.border_mm) * this.zoom) : 0;
		const pad = flt(el.cell_padding_mm ?? 0.5) * this.zoom;
		const rows = (el.rows || [])
			.map((row, ri) => {
				const is_loop = el.loop && ri === el.rows.length - 1;
				let ci = 0;
				const cells = (row.cells || [])
					.slice(0, cols.length)
					.map((c) => {
						c = c || {};
						const col = (el.col_styles || [])[ci] || {};
						ci += cint(c.colspan) || 1;
						const own = Object.fromEntries(
							Object.entries({ ...col, ...c }).filter(
								([k, v]) =>
									["bold", "align", "italic", "font_size_pt", "valign", "nowrap"].includes(
										k
									) &&
									v !== "" &&
									v != null
							)
						);
						const cs = { ...style, ...own };
						return `<td colspan="${
							c.colspan || 1
						}" style="border:${b}px solid #000;padding:${pad}px;${this.text_css(
							cs
						)}">${this.sample_text(c.text, true)}</td>`;
					})
					.join("");
				const h = flt(row.h) ? `height:${flt(row.h) * this.zoom}px;` : "";
				return `<tr class="${is_loop ? "ld-loop-row" : ""}" style="${h}">${cells}</tr>`;
			})
			.join("");
		const colgroup = cols.map((c) => `<col style="width:${(c / total) * 100}%">`).join("");
		return `<table class="ld-table"><colgroup>${colgroup}</colgroup>${rows}</table>`;
	}

	update_geometry_inputs() {
		const sel = this.selected_elements();
		if (sel.length !== 1) return;
		["x", "y", "w", "h"].forEach((k) => {
			this.$inspector.find(`[data-path="${k}"]`).val(sel[0][k]);
		});
	}

	render_inspector() {
		if (!this.$inspector) return;
		const sel = this.selected_elements();
		if (!sel.length) {
			this.$inspector.html(this.inspector_empty());
			return;
		}
		if (sel.length > 1) {
			const btn = (cmd, icon, title, disabled) =>
				`<button class="btn btn-xs btn-default" data-cmd="${cmd}" title="${title}" ${
					disabled ? "disabled" : ""
				}>${icon}</button>`;
			const few = sel.length < 3;
			this.$inspector.html(`<div class="ld-panel-title">${__("{0} elements selected", [
				sel.length,
			])}</div>
				<div class="ld-group-title">${__("Align")}</div>
				<div class="ld-btns ld-align">
					${btn("align_left", '<i class="fa fa-align-left"></i>', __("Align left edges"))}
					${btn("align_center", '<i class="fa fa-align-center"></i>', __("Align horizontal centres"))}
					${btn("align_right", '<i class="fa fa-align-right"></i>', __("Align right edges"))}
				</div>
				<div class="ld-btns ld-align">
					${btn("align_top", '<i class="fa fa-long-arrow-up"></i>', __("Align top edges"))}
					${btn("align_middle", '<i class="fa fa-arrows-v"></i>', __("Align vertical centres"))}
					${btn("align_bottom", '<i class="fa fa-long-arrow-down"></i>', __("Align bottom edges"))}
				</div>
				<div class="ld-group-title">${__("Distribute")}</div>
				<div class="ld-btns ld-align">
					${btn("distribute_h", '<i class="fa fa-arrows-h"></i>', __("Equal horizontal gaps (3 or more)"), few)}
					${btn("distribute_v", '<i class="fa fa-arrows-v"></i>', __("Equal vertical gaps (3 or more)"), few)}
				</div>
				<div class="ld-group-title">${__("Size")}</div>
				<div class="ld-btns ld-align">
					${btn("same_width", __("Same width"), __("Width of the first selected element"))}
					${btn("same_height", __("Same height"), __("Height of the first selected element"))}
				</div>
				<div class="ld-hint">${__(
					"Edges align to the outer edge of the selection; sizes copy the first selected element."
				)}</div>
				<div class="ld-hint">${__("Drag to move together, arrows to nudge, Del to remove.")}</div>`);
			return;
		}
		const el = sel[0];
		const meta = LD_PALETTE.find((p) => p.type === el.type);
		this.$inspector.html(`
			<div class="ld-panel-title"><i class="${meta.icon}"></i> ${meta.label}</div>
			<div class="ld-overflow-warn alert alert-warning small" style="display:none;">
				<i class="fa fa-exclamation-triangle"></i> ${__(
					"The content does not fit the box and will be cut on the label. Enlarge the box or reduce the font."
				)}
			</div>
			${this.type_props(el)}
			<div class="ld-group-title">${__("Position and size")} (${__("mm")})</div>
			<div class="ld-grid4">
				${this.num("x", "X", el.x)}${this.num("y", "Y", el.y)}
				${this.num("w", __("Width"), el.w)}${this.num("h", __("Height"), el.h)}
			</div>
			${this.select("rotate", __("Rotation"), el.rotate || 0, [
				[0, "0°"],
				[90, "90°"],
				[180, "180°"],
				[270, "270°"],
			])}
			${this.style_props(el)}
			<div class="ld-group-title">${__("Visibility")}</div>
			${this.text("show_if", __("Show only if (Jinja condition)"), el.show_if)}
			<div class="ld-hint">${__("E.g. doc.items or doc.qty > 0. Empty = always shown.")}</div>
		`);
	}

	inspector_empty() {
		const c = this.content_size;
		return `<div class="ld-panel-title">${__("Label")}</div>
			<div class="ld-hint">${__("Printable area")}: ${round2(c.w)} × ${round2(c.h)} ${__("mm")}</div>
			<div class="ld-hint">${__("Select an element to edit it. Shift+click selects several.")}</div>
			<div class="ld-group-title">${__("Grid")} (${__("mm")})</div>
			${this.select("@grid_mm", __("Grid step"), this.layout.grid_mm, [
				[0.25, "0.25"],
				[0.5, "0.5"],
				[1, "1"],
				[2, "2"],
			])}
			<div class="ld-hint">${__("Size and padding are set in the fields above the designer.")}</div>`;
	}

	keys_datalist(id) {
		return `<datalist id="${id}">${this.keys
			.map((k) => `<option value="${esc(k.key)}">${esc(k.label)}</option>`)
			.join("")}</datalist>`;
	}

	type_props(el) {
		const list_id = "ld-keys-" + el.id;
		if (el.type === "text") {
			return `${this.textarea("text", __("Text"), el.text)}
				<div class="ld-hint">${__("Insert values with {{ doc.fieldname }}")}</div>`;
		}
		if (el.type === "field") {
			return `${this.text("field", __("Field"), el.field, list_id)}${this.keys_datalist(list_id)}
				${this.select("format", __("Format"), el.format || "", LD_FORMATS)}
				<div class="ld-grid2">${this.text("prefix", __("Prefix"), el.prefix)}${this.text(
				"suffix",
				__("Suffix"),
				el.suffix
			)}</div>`;
		}
		if (el.type === "input") {
			const opts = (this.frm.doc.inputs || []).map((r) => [
				r.fieldname,
				`${r.label || ""} (${r.fieldname})`,
			]);
			opts.unshift(["", ""]);
			return `${this.select("input", __("Input"), el.input, opts)}
				<button class="btn btn-xs btn-default" data-cmd="new_input"><i class="fa fa-plus"></i> ${__(
					"New input"
				)}</button>
				<div class="ld-hint">${__("The value is asked in the Print dialog.")}</div>
				${this.select("format", __("Format"), el.format || "", LD_FORMATS)}
				<div class="ld-grid2">${this.text("prefix", __("Prefix"), el.prefix)}${this.text(
				"suffix",
				__("Suffix"),
				el.suffix
			)}</div>`;
		}
		if (el.type === "image") {
			return `<div class="ld-field"><label>${__("File")}</label>
					<div class="ld-file">${esc(el.file || __("No file"))}</div>
					<button class="btn btn-xs btn-default" data-cmd="gallery"><i class="fa fa-picture-o"></i> ${__(
						"Choose image"
					)}</button></div>
				${this.select("fit", __("Fit"), el.fit || "contain", [
					["contain", __("Keep proportions")],
					["stretch", __("Stretch")],
				])}
				<div class="ld-hint">${__("Printed in black and white.")}</div>`;
		}
		if (el.type === "barcode" || el.type === "qr") {
			const source = this.select("source", __("Data"), el.source || "field", [
				["field", __("Field")],
				["text", __("Text")],
			]);
			const data =
				el.source === "text"
					? this.text("data", __("Text"), el.data)
					: `${this.text("field", __("Field"), el.field, list_id)}${this.keys_datalist(list_id)}`;
			if (el.type === "qr") {
				return source + data + this.num("module_size", __("Module size"), el.module_size || 4);
			}
			return `${source}${data}
				${this.select(
					"barcode_type",
					__("Barcode type"),
					el.barcode_type || "code128",
					LD_BARCODES.map((b) => [b, b.toUpperCase()])
				)}
				${this.num("module_width", __("Bar width (mm)"), el.module_width || 0.2)}
				${this.check("show_text", __("Show text under barcode"), el.show_text)}`;
		}
		if (el.type === "table") return this.table_props(el);
		if (el.type === "repeat") return this.repeat_props(el, list_id);
		if (el.type === "rect") {
			return `${this.check("fill", __("Filled"), el.fill)}${this.num(
				"radius_mm",
				__("Corner radius (mm)"),
				el.radius_mm || 0
			)}`;
		}
		return "";
	}

	repeat_props(el, list_id) {
		const lists = [
			...new Set([...(this.child_tables || []).map((t) => t.fieldname), ...this.setup_keys()]),
		];
		const lists_id = list_id + "-lists";
		const show = el.show || "barcode";
		let kind = "";
		if (show === "barcode") {
			kind = `${this.select(
				"barcode_type",
				__("Barcode type"),
				el.barcode_type || "code128",
				LD_BARCODES.map((b) => [b, b.toUpperCase()])
			)}
				${this.num("module_width", __("Bar width (mm)"), el.module_width || 0.2)}
				${this.check("show_text", __("Show text under barcode"), el.show_text)}`;
		} else if (show === "qr") {
			kind = this.num("module_size", __("Module size"), el.module_size || 4);
		} else {
			kind = `${this.select("format", __("Format"), el.format || "", LD_FORMATS)}
				<div class="ld-grid2">${this.text("prefix", __("Prefix"), el.prefix)}${this.text(
				"suffix",
				__("Suffix"),
				el.suffix
			)}</div>`;
		}
		return `${this.text("list", __("List"), el.list, lists_id)}
			<datalist id="${lists_id}">${lists.map((l) => `<option value="${esc(l)}">`).join("")}</datalist>
			<div class="ld-hint">${__(
				"A child table of the document or a list put on doc in Data setup. One block is drawn per item."
			)}</div>
			${this.text("value", __("Value of each item"), el.value, list_id)}${this.keys_datalist(list_id)}
			<div class="ld-hint">${__("Field of the row, or . for the item itself (a list of strings).")}</div>
			${this.select("show", __("Show as"), show, [
				["barcode", __("Barcode")],
				["qr", __("QR Code")],
				["text", __("Text")],
			])}
			${kind}
			<div class="ld-grid2">
				${this.num("item_h", __("Block height (mm)"), el.item_h || 10)}
				${this.num("columns", __("Columns"), el.columns || 1)}
			</div>
			<div class="ld-grid2">
				${this.num("gap_mm", __("Gap (mm)"), el.gap_mm || 0)}
				${this.num("max_items", __("Max items (0 = all)"), el.max_items || 0)}
			</div>`;
	}

	table_props(el) {
		const loop_opts = [["", __("No (static rows)")]].concat(
			(this.child_tables || []).map((t) => [t.fieldname, `${__(t.label)} (${t.fieldname})`])
		);
		if (el.loop && !loop_opts.find((o) => o[0] === el.loop)) loop_opts.push([el.loop, el.loop]);
		const rows = (el.rows || [])
			.map(
				(row, ri) => `<div class="ld-trow">
					<input class="form-control input-xs ld-rowh" type="number" step="0.5" min="0" title="${__(
						"Row height (mm), 0 = auto"
					)}" data-path="rows.${ri}.h" value="${esc(row.h || 0)}">
					${(row.cells || [])
						.map(
							(c, ci) =>
								`<input class="form-control input-xs" data-path="rows.${ri}.cells.${ci}.text" value="${esc(
									(c && c.text) || ""
								)}">`
						)
						.join("")}
					<button class="btn btn-xs btn-default" data-cmd="row_bold" data-row="${ri}" title="${__(
					"Bold row"
				)}"><b>B</b></button>
					<button class="btn btn-xs btn-default" data-cmd="del_row" data-row="${ri}" title="${__(
					"Remove row"
				)}"><i class="fa fa-times"></i></button>
				</div>`
			)
			.join("");
		const col_fonts = (el.cols || []).map((_c, i) => ((el.col_styles || [])[i] || {}).font_size_pt || "");
		return `${this.text("@cols", __("Column widths (mm)"), (el.cols || []).join(", "))}
			${this.text("@col_fonts", __("Column font sizes (pt)"), col_fonts.join(", "))}
			<div class="ld-hint">${__(
				"Comma-separated, empty = text style size. Use **text** for bold inside a cell."
			)}</div>
			<div class="ld-hint">${__(
				"Row height (mm) first, then cell texts. {{ doc.x }} and {{ row.x }} allowed."
			)}</div>
			<div class="ld-table-edit">${rows}</div>
			<div class="ld-btns">
				<button class="btn btn-xs btn-default" data-cmd="add_row"><i class="fa fa-plus"></i> ${__("Row")}</button>
				<button class="btn btn-xs btn-default" data-cmd="add_col"><i class="fa fa-plus"></i> ${__("Column")}</button>
				<button class="btn btn-xs btn-default" data-cmd="del_col"><i class="fa fa-minus"></i> ${__("Column")}</button>
			</div>
			${this.select("loop", __("Repeat last row for"), el.loop || "", loop_opts)}
			<div class="ld-hint">${__(
				"Repeats the last row for every row of the child table; use {{ row.fieldname }}."
			)}</div>
			${this.num("cell_padding_mm", __("Cell padding (mm)"), el.cell_padding_mm ?? 0.5)}`;
	}

	style_props(el) {
		if (["line", "image", "qr"].includes(el.type)) return "";
		const s = el.style || {};
		const border = this.num("style.border_mm", __("Border (mm)"), s.border_mm || 0);
		if (el.type === "rect") return `<div class="ld-group-title">${__("Style")}</div>${border}`;
		return `<div class="ld-group-title">${__("Text style")}</div>
			<div class="ld-grid2">
				${this.num("style.font_size_pt", __("Font size (pt)"), s.font_size_pt || 10)}
				${this.select(
					"style.font_family",
					__("Font"),
					ld_font(s.font_family),
					LD_FONTS.map((f) => [f, f])
				)}
			</div>
			<div class="ld-grid2">
				${this.select("style.align", __("Horizontal"), s.align || "left", [
					["left", __("Left")],
					["center", __("Center")],
					["right", __("Right")],
				])}
				${this.select("style.valign", __("Vertical"), s.valign || "top", [
					["top", __("Top")],
					["middle", __("Middle")],
					["bottom", __("Bottom")],
				])}
			</div>
			<div class="ld-checks">
				${this.check("style.bold", __("Bold"), s.bold)}
				${this.check("style.italic", __("Italic"), s.italic)}
				${this.check("style.underline", __("Underline"), s.underline)}
				${this.check("style.nowrap", __("No wrap"), s.nowrap)}
				${this.check("style.invert", __("White on black"), s.invert)}
			</div>
			<div class="ld-grid2">${border}${this.num(
			"style.line_height",
			__("Line height"),
			s.line_height || 1.15
		)}</div>`;
	}

	num(path, label, value) {
		return `<div class="ld-field"><label>${label}</label><input type="number" step="any" class="form-control input-xs" data-path="${path}" data-kind="num" value="${esc(
			value
		)}"></div>`;
	}

	text(path, label, value, list) {
		return `<div class="ld-field"><label>${label}</label><input type="text" class="form-control input-xs" data-path="${path}" ${
			list ? `list="${list}"` : ""
		} value="${esc(value || "")}"></div>`;
	}

	textarea(path, label, value) {
		return `<div class="ld-field"><label>${label}</label><textarea rows="3" class="form-control input-xs" data-path="${path}">${esc(
			value || ""
		)}</textarea></div>`;
	}

	select(path, label, value, options) {
		return `<div class="ld-field"><label>${label}</label><select class="form-control input-xs" data-path="${path}" data-kind="${
			typeof (options[0] || [])[0] === "number" ? "num" : "str"
		}">${options
			.map(
				([v, l]) =>
					`<option value="${esc(v)}" ${String(v) === String(value) ? "selected" : ""}>${esc(
						l
					)}</option>`
			)
			.join("")}</select></div>`;
	}

	check(path, label, value) {
		return `<label class="ld-check"><input type="checkbox" data-path="${path}" data-kind="check" ${
			value ? "checked" : ""
		}> ${label}</label>`;
	}

	on_prop_change(e) {
		const $input = $(e.currentTarget);
		const path = $input.attr("data-path");
		const kind = $input.attr("data-kind");
		const is_text = $input.is("input[type=text], textarea");
		if (e.type === "change" && is_text) return this.commit_props();
		if (e.type === "input" && !is_text && kind !== "num") return;

		let value = kind === "check" ? ($input.is(":checked") ? 1 : 0) : $input.val();
		if (kind === "num") value = value === "" ? 0 : flt(value);

		if (path === "@grid_mm") {
			this.layout.grid_mm = value;
			return this.commit();
		}
		const el = this.selected_elements()[0];
		if (!el) return;
		if (path === "@col_fonts") {
			const sizes = String(value).split(",");
			el.col_styles = (el.cols || []).map((_c, i) => {
				const cs = { ...((el.col_styles || [])[i] || {}) };
				const n = flt((sizes[i] || "").trim());
				if (n > 0) cs.font_size_pt = n;
				else delete cs.font_size_pt;
				return cs;
			});
		} else if (path === "@cols") {
			const cols = String(value)
				.split(/[,;\s]+/)
				.map(flt)
				.filter((n) => n > 0);
			if (!cols.length) return;
			el.cols = cols;
			(el.rows || []).forEach((row) => {
				row.cells = cols.map((_c, i) => (row.cells || [])[i] || { text: "" });
			});
		} else {
			ld_set(el, path, value);
		}

		this.position_dom(el);
		this.$stage.find(`.ld-el[data-id="${el.id}"] .ld-el-inner`).html(this.inner_html(el));
		this.save();
		this._props_dirty = true;
		if (e.type === "change" || kind === "check" || $input.is("select"))
			this.commit_props(path === "@cols" || $input.is("select"));
	}

	commit_props(rerender) {
		this.push_history();
		this.save();
		if (rerender) this.render();
	}

	arrange(cmd) {
		const sel = this.selected.map((id) => this.layout.elements.find((e) => e.id === id)).filter(Boolean);
		if (sel.length < 2) return;
		const left = Math.min(...sel.map((e) => e.x));
		const top = Math.min(...sel.map((e) => e.y));
		const right = Math.max(...sel.map((e) => e.x + e.w));
		const bottom = Math.max(...sel.map((e) => e.y + e.h));
		const set = {
			align_left: (e) => (e.x = left),
			align_right: (e) => (e.x = right - e.w),
			align_center: (e) => (e.x = (left + right) / 2 - e.w / 2),
			align_top: (e) => (e.y = top),
			align_bottom: (e) => (e.y = bottom - e.h),
			align_middle: (e) => (e.y = (top + bottom) / 2 - e.h / 2),
			same_width: (e) => (e.w = sel[0].w),
			same_height: (e) => (e.h = sel[0].h),
		}[cmd];
		if (set) sel.forEach(set);
		const distribute = (pos, size, start, end) => {
			if (sel.length < 3) return;
			const ordered = [...sel].sort((a, b) => a[pos] - b[pos]);
			const gap = (end - start - ordered.reduce((s, e) => s + e[size], 0)) / (ordered.length - 1);
			let at = start;
			ordered.forEach((e) => {
				e[pos] = at;
				at += e[size] + gap;
			});
		};
		if (cmd === "distribute_h") distribute("x", "w", left, right);
		if (cmd === "distribute_v") distribute("y", "h", top, bottom);
		sel.forEach((e) => ["x", "y", "w", "h"].forEach((k) => (e[k] = round2(e[k]))));
		this.commit();
	}

	on_inspector_cmd(e) {
		const cmd = $(e.currentTarget).attr("data-cmd");
		if (/^(align_|distribute_|same_)/.test(cmd)) return this.arrange(cmd);
		const el = this.selected_elements()[0];
		if (!el) return;
		const ri = cint($(e.currentTarget).attr("data-row"));
		if (cmd === "new_input") return this.new_input(el);
		if (cmd === "gallery") return this.choose_image(el);
		if (cmd === "add_row") el.rows.push({ h: 0, cells: el.cols.map(() => ({ text: "" })) });
		if (cmd === "del_row" && el.rows.length > 1) el.rows.splice(ri, 1);
		if (cmd === "row_bold") {
			const bold = !(el.rows[ri].cells || []).every((c) => c && c.bold);
			el.rows[ri].cells.forEach((c) => (c.bold = bold ? 1 : 0));
		}
		if (cmd === "add_col") {
			el.cols.push(10);
			el.rows.forEach((r) => r.cells.push({ text: "" }));
		}
		if (cmd === "del_col" && el.cols.length > 1) {
			el.cols.pop();
			el.rows.forEach((r) => r.cells.pop());
		}
		this.commit();
	}

	new_input(el) {
		const d = new frappe.ui.Dialog({
			title: __("New input"),
			fields: [
				{ fieldname: "label", fieldtype: "Data", label: __("Label"), reqd: 1 },
				{
					fieldname: "fieldname",
					fieldtype: "Data",
					label: __("Fieldname"),
					reqd: 1,
					description: __("Latin letters, digits and _"),
				},
				{
					fieldname: "fieldtype",
					fieldtype: "Select",
					label: __("Type"),
					options: "Data\nSmall Text\nInt\nFloat\nDate\nSelect\nCheck",
					default: "Data",
				},
				{ fieldname: "default_value", fieldtype: "Data", label: __("Default") },
				{ fieldname: "reqd", fieldtype: "Check", label: __("Mandatory") },
			],
			primary_action_label: __("Add"),
			primary_action: (v) => {
				const fieldname = v.fieldname.trim();
				if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(fieldname)) {
					frappe.msgprint(__("Invalid fieldname"));
					return;
				}
				if ((this.frm.doc.inputs || []).some((r) => r.fieldname === fieldname)) {
					frappe.msgprint(__("An input with this fieldname already exists"));
					return;
				}
				const row = this.frm.add_child("inputs", { ...v, fieldname });
				this.frm.refresh_field("inputs");
				el.input = row.fieldname;
				d.hide();
				this.commit();
			},
		});
		d.fields_dict.label.$input.on("input", () => {
			const label = d.get_value("label") || "";
			if (d._fieldname_touched) return;
			const slug = frappe.scrub(label).replace(/[^a-z0-9_]/g, "");
			d.set_value("fieldname", /^[a-z_]/.test(slug) ? slug : slug ? "f_" + slug : "");
		});
		d.fields_dict.fieldname.$input.on("input", () => (d._fieldname_touched = true));
		d.show();
	}

	choose_image(el) {
		erpnext.label_designer.image_gallery({
			selected: el.file,
			on_select: (file) => {
				const target = this.layout.elements.find((e) => e.id === el.id);
				if (!target) return;
				target.file = file.file_name;
				target.file_url = file.file_url;
				this.commit();
			},
		});
	}

	exact_preview() {
		if (this.compare) this.refresh_compare();
		erpnext.label_designer.preview_form(this.frm).then((data) => {
			if (data) erpnext.label_designer.show_big_preview(data, this.frm.doc.template_name);
		});
	}

	setup_keys() {
		const src = this.layout.setup || "";
		const keys = new Set();
		for (const m of src.matchAll(/doc\.update\(\s*\{([^}]*)\}/g)) {
			for (const k of m[1].matchAll(/["']([A-Za-z_][\w]*)["']\s*:/g)) keys.add(k[1]);
		}
		return [...keys];
	}

	edit_setup() {
		const d = new frappe.ui.Dialog({
			title: __("Data setup"),
			size: "large",
			fields: [
				{
					fieldname: "setup",
					fieldtype: "Code",
					options: "Jinja",
					label: __("Jinja run before the elements"),
					default: this.layout.setup || "",
					description: __(
						'Store computed values on doc, e.g. {% set _ = doc.update({"tu": ...}) %}; then show them with a Field element (doc.tu). Lookups run when the label is rendered; the canvas shows the key name.'
					),
				},
			],
			primary_action_label: __("Apply"),
			primary_action: (v) => {
				this.layout.setup = (v.setup || "").trim();
				d.hide();
				this.commit();
				this.refresh_keys();
			},
		});
		d.show();
	}

	show_html() {
		frappe.call({
			method: "erpnext.devices.label_layout.compile_layout_api",
			args: { layout: JSON.stringify(this.layout) },
			callback: (r) => {
				const d = new frappe.ui.Dialog({ title: __("Generated HTML"), size: "large" });
				d.$body.html(
					`<pre style="font-size:11px;max-height:60vh;overflow:auto;white-space:pre-wrap;">${esc(
						r.message || ""
					)}</pre><div class="text-muted small">${__(
						"Read only. Switch the editor to HTML to edit it by hand (the visual layout is then no longer used)."
					)}</div>`
				);
				d.show();
			},
		});
	}
};

erpnext.label_designer.image_gallery = function ({ selected, on_select }) {
	const method = "erpnext.devices.label_images";
	const d = new frappe.ui.Dialog({ title: __("Label images"), size: "large" });
	d.$body.html(`
		<div class="ld-gallery-bar">
			<input type="text" class="form-control input-sm ld-gallery-search" placeholder="${__("Search images...")}">
			<button class="btn btn-sm btn-primary ld-gallery-upload"><i class="fa fa-upload"></i> ${__(
				"Upload new"
			)}</button>
		</div>
		<div class="ld-gallery"><div class="text-muted small">${__("Loading...")}</div></div>
		<div class="ld-hint">${__(
			"Shared by every label template. Uploaded images are added here for everyone; labels print them in black and white."
		)}</div>`);
	let files = [];
	const draw = () => {
		const q = (d.$body.find(".ld-gallery-search").val() || "").toLowerCase().trim();
		const shown = files.filter((f) => !q || f.file_name.toLowerCase().includes(q));
		d.$body.find(".ld-gallery").html(
			shown.length
				? shown
						.map(
							(f) => `<div class="ld-gallery-item ${
								f.file_name === selected ? "ld-gallery-selected" : ""
							}" data-name="${esc(f.name)}" title="${esc(f.file_name)}">
								<div class="ld-gallery-thumb"><img src="${esc(f.file_url)}" loading="lazy"></div>
								<div class="ld-gallery-name">${esc(f.file_name)}</div>
							</div>`
						)
						.join("")
				: `<div class="text-muted small">${__("No images yet. Upload the first one.")}</div>`
		);
	};
	const load = () =>
		frappe.call({ method: `${method}.get_label_images` }).then((r) => {
			files = r.message || [];
			draw();
		});
	const pick = (file) => {
		d.hide();
		on_select(file);
	};
	d.$body.on("input", ".ld-gallery-search", draw);
	d.$body.on("click", ".ld-gallery-item", (e) => {
		const file = files.find((f) => f.name === $(e.currentTarget).attr("data-name"));
		if (file) pick(file);
	});
	d.$body.on("click", ".ld-gallery-upload", () => {
		new frappe.ui.FileUploader({
			method: `${method}.upload_label_image`,
			restrictions: { allowed_file_types: ["image/*"] },
			disable_file_browser: true,
			allow_web_link: false,
			allow_take_photo: false,
			allow_google_drive: false,
			on_success: (_file_doc, r) => {
				const file = r && r.message;
				if (file && file.file_url) {
					files.push(file);
					pick(file);
				} else {
					load();
				}
			},
		});
	});
	d.show();
	load();
	return d;
};

erpnext.label_designer.form_payload = function (frm) {
	const d = frm.doc;
	return JSON.stringify({
		editor_mode: d.editor_mode,
		html_template: d.html_template,
		layout_json: d.layout_json,
		label_size: d.label_size,
		field_mapping: d.field_mapping,
		preview_data: d.preview_data,
		reference_doctype: d.reference_doctype,
		padding_top_mm: d.padding_top_mm,
		padding_right_mm: d.padding_right_mm,
		padding_bottom_mm: d.padding_bottom_mm,
		padding_left_mm: d.padding_left_mm,
		inputs: (d.inputs || []).map((r) => ({
			fieldname: r.fieldname,
			label: r.label,
			default_value: r.default_value,
			reqd: r.reqd,
		})),
	});
};

erpnext.label_designer.preview_form = function (frm) {
	return frappe
		.call({
			method: "erpnext.devices.doctype.label_template.label_template.render_template_preview",
			args: { doc: erpnext.label_designer.form_payload(frm), sample: 1 },
			freeze: true,
			freeze_message: __("Rendering..."),
		})
		.then((r) => r.message);
};

erpnext.label_designer.show_big_preview = function (data, title) {
	const d = new frappe.ui.Dialog({ title: title || __("Preview"), size: "extra-large" });
	const PX_PER_MM = 3.78;
	const avail = Math.min(window.innerWidth * 0.85, 1100);
	const w = Math.min(avail, data.width_mm * PX_PER_MM * 4);
	d.$body.html(`
		<div style="text-align:center;padding:10px;">
			<div class="text-muted small" style="margin-bottom:8px;">
				${data.width_mm} × ${data.height_mm} ${__("mm")} · ${data.width_dots} × ${data.height_dots} @ ${data.dpi} DPI
			</div>
			<img src="data:image/png;base64,${data.image_base64}"
				style="width:${w}px;max-width:100%;border:1px solid var(--border-color);background:#fff;image-rendering:pixelated;">
			<details style="margin-top:10px;text-align:left;">
				<summary style="cursor:pointer;font-size:11px;color:var(--text-muted);">${__("Show HTML source")}</summary>
				<pre style="font-size:10px;max-height:240px;overflow:auto;margin-top:4px;background:var(--bg-color);padding:8px;border-radius:4px;">${esc(
					data.html || ""
				)}</pre>
			</details>
		</div>`);
	d.show();
};

erpnext.label_designer.tint_ink = function (b64) {
	return new Promise((resolve) => {
		const img = new Image();
		img.onload = () => {
			const c = document.createElement("canvas");
			c.width = img.width;
			c.height = img.height;
			const ctx = c.getContext("2d");
			ctx.drawImage(img, 0, 0);
			const data = ctx.getImageData(0, 0, c.width, c.height);
			const px = data.data;
			for (let i = 0; i < px.length; i += 4) {
				const ink = px[i] < 128;
				px[i] = 230;
				px[i + 1] = 20;
				px[i + 2] = 20;
				px[i + 3] = ink ? 150 : 0;
			}
			ctx.putImageData(data, 0, 0);
			resolve(c.toDataURL("image/png"));
		};
		img.onerror = () => resolve(null);
		img.src = `data:image/png;base64,${b64}`;
	});
};

erpnext.label_designer.font_faces = function () {
	return Object.entries(LD_FONT_FILES)
		.map(([family, [regular, bold]]) =>
			[
				[regular, "normal"],
				[bold, "bold"],
			]
				.map(
					([file, weight]) =>
						`@font-face{font-family:'LD ${family}';src:url('/assets/erpnext/fonts/label/${file}.ttf') format('truetype');font-weight:${weight};font-style:normal;font-display:block}`
				)
				.join("\n")
		)
		.join("\n");
};

erpnext.label_designer.inject_style = function () {
	if (document.getElementById("ld-style")) return;
	const css =
		erpnext.label_designer.font_faces() +
		`
.ld-root{border:1px solid var(--border-color);border-radius:var(--border-radius-md);background:var(--card-bg);outline:none}
.ld-toolbar{display:flex;align-items:center;gap:4px;padding:6px 8px;border-bottom:1px solid var(--border-color);flex-wrap:wrap}
.ld-sep{width:1px;height:18px;background:var(--border-color);margin:0 4px}
.ld-flex{flex:1}
.ld-zoom{font-size:11px;min-width:40px;text-align:center;color:var(--text-muted)}
.ld-snap{font-size:12px;margin:0;display:flex;gap:4px;align-items:center;font-weight:normal}
.ld-body{display:flex;min-height:420px}
.ld-palette{width:130px;border-right:1px solid var(--border-color);padding:8px;flex-shrink:0}
.ld-palette-item{display:flex;align-items:center;gap:8px;padding:6px 8px;margin-bottom:4px;border:1px solid var(--border-color);border-radius:6px;cursor:grab;font-size:12px;background:var(--fg-color);user-select:none}
.ld-palette-item:hover{border-color:var(--primary);color:var(--primary)}
.ld-palette-item i{width:14px;text-align:center}
.ld-panel-title{font-weight:600;font-size:12px;margin-bottom:8px;display:flex;gap:6px;align-items:center}
.ld-group-title{font-weight:600;font-size:11px;color:var(--text-muted);margin:12px 0 4px;text-transform:uppercase}
.ld-hint{font-size:11px;color:var(--text-muted);margin:4px 0}
.ld-stage-wrap{flex:1;overflow:auto;background:var(--subtle-fg);padding:20px;min-width:0}
.ld-stage{display:inline-block;min-width:100%}
.ld-label{position:relative;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.25);margin:0 auto}
.ld-content{position:absolute;outline:1px dashed rgba(0,120,255,.35);
	background-image:linear-gradient(rgba(0,0,0,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(0,0,0,.08) 1px,transparent 1px),linear-gradient(rgba(0,0,0,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(0,0,0,.03) 1px,transparent 1px)}
.ld-size-note{text-align:center;font-size:11px;color:var(--text-muted);margin-top:6px}
.ld-el{position:absolute;cursor:move;box-sizing:border-box;touch-action:none}
.ld-el:hover{outline:1px dashed rgba(0,120,255,.6)}
.ld-el.ld-selected{outline:1px solid #2490ef;z-index:2}
.ld-el-inner{width:100%;height:100%;overflow:hidden;pointer-events:none;color:#000;font-kerning:none;font-variant-ligatures:none;font-feature-settings:"kern" 0,"liga" 0;letter-spacing:0.006em;word-spacing:0;text-rendering:optimizeSpeed;-webkit-font-smoothing:antialiased}
.ld-el.ld-overflow{outline:1px dashed #e24c4c}
.ld-el.ld-overflow::after{content:"\\f071";font-family:FontAwesome;position:absolute;right:-14px;top:-14px;color:#e24c4c;font-size:12px}
.ld-compare{position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;image-rendering:pixelated;z-index:5}
.ld-compare-note{color:#e61414}
.ld-cell{width:100%;height:100%;border-collapse:collapse;table-layout:fixed;box-sizing:border-box}
.ld-cell td{padding:0}
.ld-table{width:100%;border-collapse:collapse;table-layout:fixed}
.ld-loop-row td{background:rgba(36,144,239,.08)}
.ld-gallery-bar{display:flex;gap:8px;margin-bottom:10px}
.ld-gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px;max-height:60vh;overflow:auto;padding:2px}
.ld-gallery-item{border:1px solid var(--border-color);border-radius:6px;padding:6px;cursor:pointer;background:var(--fg-color)}
.ld-gallery-item:hover,.ld-gallery-selected{border-color:var(--primary);box-shadow:0 0 0 1px var(--primary)}
.ld-gallery-thumb{height:90px;display:flex;align-items:center;justify-content:center;background:#fff;border-radius:4px}
.ld-gallery-thumb img{max-width:100%;max-height:90px;object-fit:contain}
.ld-gallery-name{font-size:11px;margin-top:4px;word-break:break-all;text-align:center}
.ld-repeat-item{position:absolute;overflow:hidden;outline:1px dotted rgba(36,144,239,.5)}
.ld-ph{background:rgba(36,144,239,.15);color:#1366b8;border-radius:3px;padding:0 2px;font-family:monospace;font-size:.85em}
.ld-ph-input{background:rgba(255,160,0,.2);color:#a05a00}
.ld-empty{width:100%;height:100%;display:flex;align-items:center;justify-content:center;background:#eee;color:#999}
.ld-barcode-wrap{width:100%;height:100%;display:flex;flex-direction:column}
.ld-barcode{flex:1;background:repeating-linear-gradient(90deg,#000 0 2px,#fff 2px 3px,#000 3px 4px,#fff 4px 7px,#000 7px 10px,#fff 10px 11px)}
.ld-qr{margin:auto;background:conic-gradient(#000 25%,#fff 0 50%,#000 0 75%,#fff 0) 0 0/20% 20%;outline:2px solid #000}
.ld-handle{position:absolute;width:8px;height:8px;background:#fff;border:1px solid #2490ef;border-radius:2px;z-index:3}
.ld-h-nw{left:-5px;top:-5px;cursor:nwse-resize}.ld-h-n{left:calc(50% - 4px);top:-5px;cursor:ns-resize}
.ld-h-ne{right:-5px;top:-5px;cursor:nesw-resize}.ld-h-e{right:-5px;top:calc(50% - 4px);cursor:ew-resize}
.ld-h-se{right:-5px;bottom:-5px;cursor:nwse-resize}.ld-h-s{left:calc(50% - 4px);bottom:-5px;cursor:ns-resize}
.ld-h-sw{left:-5px;bottom:-5px;cursor:nesw-resize}.ld-h-w{left:-5px;top:calc(50% - 4px);cursor:ew-resize}
.ld-inspector{width:260px;border-left:1px solid var(--border-color);padding:8px 10px;flex-shrink:0;overflow:auto;max-height:640px}
.ld-field{margin-bottom:6px}.ld-field label{font-size:11px;color:var(--text-muted);margin-bottom:2px;display:block}
.ld-grid2{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.ld-grid4{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:4px}
.ld-checks{display:flex;flex-wrap:wrap;gap:2px 10px;margin:4px 0 6px}
.ld-check{font-size:12px;font-weight:normal;display:flex;gap:4px;align-items:center;margin:0}
.ld-file{font-size:11px;word-break:break-all;margin-bottom:4px}
.ld-table-edit{display:flex;flex-direction:column;gap:3px;margin:4px 0}
.ld-trow{display:flex;gap:2px}.ld-trow input{min-width:0;flex:1;padding:2px 4px}.ld-trow .ld-rowh{flex:0 0 42px}
.ld-btns{display:flex;gap:4px;margin-bottom:6px}
.ld-align .btn{flex:1}
.lt-thumb{display:inline-block;cursor:zoom-in;border:1px solid var(--border-color);border-radius:4px;background:#fff;padding:4px;max-width:100%}
.lt-thumb img{display:block;max-height:150px;max-width:100%;width:auto;height:auto}
@media (max-width:900px){.ld-body{flex-direction:column}.ld-palette,.ld-inspector{width:auto;border:0;max-height:none}.ld-palette{display:flex;flex-wrap:wrap;gap:4px}}
`;
	const style = document.createElement("style");
	style.id = "ld-style";
	style.textContent = css;
	document.head.appendChild(style);
};
