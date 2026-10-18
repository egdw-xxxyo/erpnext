frappe.pages["package-overview"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Package Overview"),
		single_column: true,
	});
	wrapper.package_overview = new PackageOverview(page);
};

frappe.pages["package-overview"].on_page_show = function (wrapper) {
	wrapper.package_overview?.start_timer();
};

frappe.pages["package-overview"].on_page_hide = function (wrapper) {
	wrapper.package_overview?.stop_timer();
};

const PKO_REFRESH_SECONDS = 60;
const PKO_PAGE_SIZE = 50;
const PKO_TABS = [
	["summary", "fa fa-th-large", "Summary"],
	["waiting", "fa fa-hourglass-half", "Waiting to ship"],
	["items", "fa fa-cubes", "By item"],
	["shipped", "fa fa-truck", "Shipped"],
	["drafts", "fa fa-pencil-square-o", "Drafts"],
	["other", "fa fa-random", "Unpacked and loose"],
];
const PKO_STATUSES = [
	["Draft", "red"],
	["Packed", "blue"],
	["Shipped", "green"],
	["Unpacked", "orange"],
	["Cancelled", "gray"],
];

class PackageOverview {
	constructor(page) {
		this.page = page;
		this.data = null;
		this.tab = "summary";
		this.state = {};
		this.page_no = {};
		this.auto = true;
		this.make();
		this.refresh();
	}

	make() {
		this.page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.page.add_inner_button(__("Auto-refresh"), () => this.toggle_auto());
		this.page.add_inner_button(__("Package"), () => frappe.set_route("List", "Package"));
		this.page.main.html(`
			<div class="package-overview">
				<div class="pko-tabs"></div>
				<div class="pko-meta text-muted"></div>
				<div class="pko-bar"></div>
				<div class="pko-body"></div>
			</div>
		`);
		this.$tabs = this.page.main.find(".pko-tabs");
		this.$meta = this.page.main.find(".pko-meta");
		this.$bar = this.page.main.find(".pko-bar");
		this.make_bar();
		this.$body = this.page.main.find(".pko-body");
		this.$tabs.on("click", ".pko-tab", (e) => {
			this.tab = $(e.currentTarget).data("tab");
			this.render();
		});
		this.$body.on("click", ".pko-page", (e) => {
			const $b = $(e.currentTarget);
			const key = $b.data("key");
			this.page_no[key] = Math.max(0, (this.page_no[key] || 0) + Number($b.data("dir")));
			this.render();
		});
		this.$body.on("click", ".pko-goto", (e) => {
			e.preventDefault();
			this.tab = $(e.currentTarget).data("tab");
			const item = $(e.currentTarget).data("item");
			if (item) {
				const f = this.f();
				if (!f.items.includes(String(item))) f.items = [...f.items, String(item)];
				this.reset_pages();
			}
			this.render();
		});
		this.$body.on("click", ".pko-toggle", (e) => {
			if ($(e.target).closest("a[href]").length) return;
			$(e.currentTarget).closest(".pko-card").toggleClass("pko-open");
		});
	}

	start_timer() {
		this.stop_timer();
		if (!this.auto) return;
		this.timer = setInterval(() => this.refresh(true), PKO_REFRESH_SECONDS * 1000);
	}

	stop_timer() {
		if (this.timer) clearInterval(this.timer);
		this.timer = null;
	}

	toggle_auto() {
		this.auto = !this.auto;
		this.auto ? this.start_timer() : this.stop_timer();
		frappe.show_alert({
			message: this.auto ? __("Auto-refresh on") : __("Auto-refresh off"),
			indicator: this.auto ? "green" : "gray",
		});
		this.render_meta();
	}

	refresh(silent) {
		if (this.loading) return;
		this.loading = true;
		frappe
			.call({
				method: "erpnext.stock.page.package_overview.package_overview.get_overview",
				freeze: !silent && !this.data,
			})
			.then((r) => {
				this.data = r.message;
				this.render();
			})
			.always(() => {
				this.loading = false;
			});
		if (!this.timer && this.auto) this.start_timer();
	}

	f(tab) {
		return (this.state[tab || this.tab] ||= { items: [], groups: [], from: "", to: "", q: "" });
	}

	reset_pages() {
		this.page_no = {};
	}

	make_bar() {
		const defs = [
			["items", "MultiSelectList", __("Item"), (txt) => this.item_options(txt)],
			["groups", "MultiSelectList", __("Item Category"), (txt) => this.group_options(txt)],
			["from", "Date", __("From date")],
			["to", "Date", __("To date")],
			["q", "Data", __("Package"), null, __("Package ID, serial no, order")],
		];
		this.fields = {};
		defs.forEach(([key, fieldtype, label, get_data, placeholder]) => {
			const $col = $(`<div class="pko-field" data-key="${key}"></div>`).appendTo(this.$bar);
			const df = {
				fieldname: key,
				fieldtype,
				label,
				placeholder: placeholder || label,
				change: () => this.on_field(key),
			};
			if (get_data) df.get_data = get_data;
			const control = frappe.ui.form.make_control({ df, parent: $col, render_input: true });
			control.refresh();
			this.fields[key] = control;
		});
		this.fields.q.$input.on(
			"input",
			frappe.utils.debounce(() => this.on_field("q"), 250)
		);
		$(`<a class="pko-clear">${__("Clear filters")}</a>`)
			.appendTo(this.$bar)
			.on("click", () => {
				this.state[this.tab] = null;
				this.reset_pages();
				this.render();
			});
	}

	on_field(key) {
		if (this.syncing) return;
		const f = this.f();
		let value = this.fields[key].get_value();
		if (key === "items" || key === "groups") value = [...new Set((value || []).map(String))];
		else value = (value || "").trim();
		if (JSON.stringify(f[key]) === JSON.stringify(value)) return;
		f[key] = value;
		this.reset_pages();
		this.render();
	}

	sync_bar() {
		const f = this.f();
		const show = this.tab !== "summary";
		this.$bar.toggle(show);
		if (!show) return;
		this.syncing = true;
		Object.keys(this.fields).forEach((key) => {
			const want = f[key];
			if (
				JSON.stringify(this.fields[key].get_value() || (Array.isArray(want) ? [] : "")) !==
				JSON.stringify(want)
			)
				this.fields[key].set_value(want);
		});
		this.syncing = false;
		const dated = this.tab !== "items";
		this.$bar.find('[data-key="from"], [data-key="to"]').toggle(dated);
	}

	// Codes of the items the current tab shows, ignoring its own item and category filter.
	tab_codes() {
		const d = this.data;
		const codes = new Set();
		if (this.tab === "waiting" || this.tab === "drafts")
			d[this.tab].forEach((b) => b.contents.forEach((c) => codes.add(c.item_code)));
		else if (this.tab === "items") d.items.forEach((i) => codes.add(i.item_code));
		else if (this.tab === "shipped")
			d.shipments.forEach((s) => Object.keys(s.items).forEach((c) => codes.add(c)));
		else if (this.tab === "other") d.loose_shipped.forEach((s) => codes.add(s.item_code));
		return codes;
	}

	item_options(txt) {
		const q = (txt || "").toLowerCase();
		const names = Object.fromEntries((this.data?.items || []).map((i) => [i.item_code, i.item_name]));
		return [...this.tab_codes()]
			.sort()
			.filter((c) => !q || `${c} ${names[c] || ""}`.toLowerCase().includes(q))
			.map((c) => ({ value: c, description: names[c] && names[c] !== c ? names[c] : "" }));
	}

	group_options(txt) {
		const q = (txt || "").toLowerCase();
		const counts = {};
		this.tab_codes().forEach((c) => {
			const g = (this.data.item_groups || {})[c];
			if (g) counts[g] = (counts[g] || 0) + 1;
		});
		return Object.keys(counts)
			.sort()
			.filter((g) => !q || g.toLowerCase().includes(q))
			.map((g) => ({ value: g, description: __("{0} items in group", [counts[g]]) }));
	}

	item_allowed(item_code) {
		const f = this.f();
		if (f.items.length && !f.items.includes(item_code)) return false;
		if (f.groups.length && !f.groups.includes((this.data.item_groups || {})[item_code])) return false;
		return true;
	}

	date_allowed(date) {
		const f = this.f();
		if (!f.from && !f.to) return true;
		const day = String(date || "").slice(0, 10);
		if (!day) return false;
		return (!f.from || day >= f.from) && (!f.to || day <= f.to);
	}

	paginate(key, rows) {
		const pages = Math.max(1, Math.ceil(rows.length / PKO_PAGE_SIZE));
		const page = Math.min(this.page_no[key] || 0, pages - 1);
		this.page_no[key] = page;
		const from = page * PKO_PAGE_SIZE;
		const pager = `
			<div class="pko-pager">
				<span class="text-muted">${__("{0}–{1} of {2}", [
					rows.length ? from + 1 : 0,
					Math.min(rows.length, from + PKO_PAGE_SIZE),
					rows.length,
				])}</span>
				<button class="btn btn-xs btn-default pko-page" data-key="${key}" data-dir="-1" ${page ? "" : "disabled"}>
					<i class="fa fa-chevron-left"></i></button>
				<span>${page + 1} / ${pages}</span>
				<button class="btn btn-xs btn-default pko-page" data-key="${key}" data-dir="1" ${
			page < pages - 1 ? "" : "disabled"
		}>
					<i class="fa fa-chevron-right"></i></button>
			</div>`;
		return { rows: rows.slice(from, from + PKO_PAGE_SIZE), pager };
	}

	render() {
		if (!this.data) return;
		this.render_tabs();
		this.render_meta();
		this.sync_bar();
		const html = this[`render_${this.tab}`](this.data);
		this.$body.html(html || `<div class="text-muted pko-empty">${__("Nothing found")}</div>`);
	}

	render_tabs() {
		const d = this.data;
		const counts = {
			summary: d.issues.filter((i) => i.level === "error").length || "",
			waiting: d.waiting.length,
			items: d.items.length,
			shipped: d.shipments.length,
			drafts: d.drafts.length,
			other: d.unpacked.length + d.loose_shipped.length,
		};
		this.$tabs.html(
			PKO_TABS.map(
				([key, icon, label]) => `
				<button class="btn btn-sm pko-tab ${this.tab === key ? "btn-primary" : "btn-default"}" data-tab="${key}">
					<i class="${icon}"></i> ${__(label)}
					${counts[key] !== "" ? `<span class="pko-count">${counts[key]}</span>` : ""}
				</button>`
			).join("")
		);
	}

	render_meta() {
		if (!this.data) return;
		this.$meta.html(
			`${__("Updated")}: ${frappe.datetime.str_to_user(this.data.generated_at)} · ${
				this.auto ? __("auto-refresh every {0} s", [PKO_REFRESH_SECONDS]) : __("auto-refresh off")
			}`
		);
	}

	match(...values) {
		const q = this.f().q.toLowerCase();
		if (!q) return true;
		return values.flat().some((v) => v && String(v).toLowerCase().includes(q));
	}

	box_match(box) {
		return (
			box.contents.some((c) => this.item_allowed(c.item_code)) &&
			this.date_allowed(box.created) &&
			this.match(
				box.name,
				box.packing_template,
				box.sales_order,
				box.bpak,
				box.pallet,
				box.serials,
				box.contents.map((c) => [c.item_code, c.item_name]),
				Object.keys(box.warehouses)
			)
		);
	}

	// ------------------------------------------------------------------ summary

	render_summary(d) {
		const c = this.data.counts;
		const waiting_qty = d.waiting.reduce((n, b) => n + b.serial_count, 0);
		const oldest = d.waiting[0];
		const week = d.history.slice(-7);
		const packed_week = week.reduce((n, r) => n + r.packed, 0);
		const shipped_week = week.reduce((n, r) => n + r.shipped, 0);

		const tile = (tab, icon, value, label, sub) => `
			<a class="pko-tile pko-goto" data-tab="${tab}" href="#">
				<div class="pko-tile-icon"><i class="${icon}"></i></div>
				<div class="pko-tile-value">${value}</div>
				<div class="pko-tile-label">${label}</div>
				<div class="pko-tile-sub text-muted">${sub}</div>
			</a>`;

		const issues = d.issues.filter((i) => this.match(i.message, i.area, i.name));
		const level_icon = {
			error: "fa-times-circle",
			warning: "fa-exclamation-triangle",
			info: "fa-info-circle",
		};
		const level_label = { error: __("Error"), warning: __("Warning"), info: __("Info") };
		const page = this.paginate("issues", issues);
		const shown = page.rows;

		return `
			<div class="pko-tiles">
				${tile(
					"waiting",
					"fa fa-hourglass-half",
					d.waiting.length,
					__("Boxes waiting to ship"),
					oldest
						? __("{0} pcs, oldest {1}", [waiting_qty, this.duration(oldest.age)])
						: __("{0} pcs", [waiting_qty])
				)}
				${tile(
					"items",
					"fa fa-cubes",
					d.items.filter((i) => i.Packed.boxes).length,
					__("Items in waiting boxes"),
					__("{0} items packed ever", [d.items.length])
				)}
				${tile(
					"shipped",
					"fa fa-truck",
					c.Shipped || 0,
					__("Boxes shipped"),
					__("{0} documents", [d.shipments.length])
				)}
				${tile(
					"summary",
					"fa fa-line-chart",
					`${packed_week} / ${shipped_week}`,
					__("Packed / shipped, 7 days"),
					__("boxes")
				)}
				${tile("drafts", "fa fa-pencil-square-o", d.drafts.length, __("Draft boxes"), __("not submitted yet"))}
				${tile(
					"other",
					"fa fa-random",
					d.loose_shipped.length,
					__("Shipped without a box"),
					__("serials, last {0} days", [this.data.history_days])
				)}
			</div>
			<div class="pko-statuses">
				${PKO_STATUSES.map(
					([status, color]) => `
					<a href="/desk/package?status=${encodeURIComponent(status)}">
						${this.pill(`${__(status)}: ${c[status] || 0}`, color)}</a>`
				).join("")}
			</div>
			<div class="pko-flow">
				<span><i class="fa fa-cube"></i> ${__("Unit in staging")}</span><i class="fa fa-long-arrow-right"></i>
				<span><i class="fa fa-pencil-square-o"></i> ${__("Draft")}</span><i class="fa fa-long-arrow-right"></i>
				<span><i class="fa fa-archive"></i> ${__("Packed")}</span><i class="fa fa-long-arrow-right"></i>
				<span><i class="fa fa-truck"></i> ${__("Delivery Note")} (${__(
			"whole box"
		)})</span><i class="fa fa-long-arrow-right"></i>
				<span><i class="fa fa-check"></i> ${__("Shipped")}</span>
			</div>
			<h5 class="pko-h">${__("Last {0} days", [this.data.history_days])}</h5>
			${this.history_chart(d.history)}
			<h5 class="pko-h">${__("Checks")} <span class="text-muted">(${issues.length})</span></h5>
			${
				issues.length
					? `<div class="pko-issues">${shown
							.map(
								(i) => `
						<div class="pko-issue pko-${i.level}">
							<i class="fa ${level_icon[i.level]}"></i>
							<span class="pko-issue-level">${level_label[i.level]}</span>
							<span class="pko-issue-area">${i.doctype ? this.link(i.doctype, i.name) : ""}</span>
							<span class="pko-issue-msg">${frappe.utils.escape_html(i.message)}</span>
						</div>`
							)
							.join("")}</div>${issues.length > PKO_PAGE_SIZE ? page.pager : ""}`
					: `<div class="pko-ok"><i class="fa fa-check-circle"></i> ${__(
							"No problems found"
					  )}</div>`
			}
			${this.where_to_find()}
		`;
	}

	history_chart(history) {
		const max = Math.max(1, ...history.map((r) => Math.max(r.packed, r.shipped)));
		return `
			<div class="pko-chart">
				${history
					.map(
						(r) => `
					<div class="pko-day" title="${frappe.datetime.str_to_user(r.date)}: ${__("packed")} ${r.packed}, ${__(
							"shipped"
						)} ${r.shipped}">
						<div class="pko-day-bars">
							<span class="pko-bar-packed" style="height: ${(r.packed / max) * 100}%"></span>
							<span class="pko-bar-shipped" style="height: ${(r.shipped / max) * 100}%"></span>
						</div>
						<div class="pko-day-label text-muted">${r.date.slice(8, 10)}.${r.date.slice(5, 7)}</div>
					</div>`
					)
					.join("")}
			</div>
			<div class="pko-legend">
				<span><i class="pko-bar-packed"></i>${__("Packed")}</span>
				<span><i class="pko-bar-shipped"></i>${__("Shipped")}</span>
			</div>`;
	}

	where_to_find() {
		const rows = [
			["Package", __("Boxes: contents, status, the document that shipped them")],
			["Pallet", __("Pallets: boxes put together for one shipment")],
			["Packing Template", __("Packing templates: box, units per box, required checks")],
			["Packing Job", __("Packing jobs: who packed which serials at which workplace")],
			["Delivery Note", __("Delivery notes: a packed box ships only whole")],
			["Serial No", __("Serial numbers: where a unit is now")],
		];
		return `
			<h5 class="pko-h">${__("Where to find")}</h5>
			<div class="pko-where">
				${rows
					.map(
						([dt, text]) => `
					<div><a href="${this.list_url(dt)}">${__(dt)}</a>
					<span class="text-muted">— ${frappe.utils.escape_html(text)}</span></div>`
					)
					.join("")}
			</div>`;
	}

	// ------------------------------------------------------------------ boxes

	render_waiting(d) {
		return this.box_table(d.waiting, __("Oldest first. Click a row to see its serial numbers."));
	}

	render_drafts(d) {
		return this.box_table(d.drafts, __("Draft boxes are not packed yet: their serials are free."));
	}

	box_table(boxes, hint) {
		const rows = boxes.filter((b) => this.box_match(b));
		if (!rows.length) return "";
		const page = this.paginate(this.tab, rows);
		const shown = page.rows;
		const dash = `<span class="text-muted">—</span>`;
		return `
			<div class="text-muted small pko-hint">${hint}</div>
			<div class="pko-table-wrap"><table class="table table-bordered pko-table">
				<thead><tr>
					<th>${__("Package")}</th><th>${__("Age")}</th><th>${__("Contents")}</th>
					<th>${__("Where the serials are")}</th><th>${__("Order")} / ${__("Pallet")}</th>
				</tr></thead>
				<tbody>${shown
					.map(
						(b) => `
					<tr class="pko-card pko-toggle">
						<td>${this.link("Package", b.name)}
							<div class="text-muted small">${frappe.utils.escape_html(b.packing_template || "")}</div></td>
						<td class="${b.age > 7 * 86400 ? "text-danger" : ""}">${this.duration(b.age)}
							<div class="text-muted small">${frappe.datetime.str_to_user(b.created)}</div></td>
						<td>${b.contents
							.map(
								(c) =>
									`<div><b>${c.qty}</b> × ${this.item_link(c.item_code, c.item_name)}</div>`
							)
							.join("")}
							<div class="pko-details pko-serials">${b.serials.map((s) => this.link("Serial No", s)).join(" ")}</div></td>
						<td>${this.places(b)}</td>
						<td>${
							[
								b.sales_order && this.link("Sales Order", b.sales_order),
								b.bpak && this.link("BpAK", b.bpak),
								b.pallet && this.link("Pallet", b.pallet),
							]
								.filter(Boolean)
								.join("<br>") || dash
						}</td>
					</tr>`
					)
					.join("")}</tbody>
			</table></div>${page.pager}`;
	}

	places(box) {
		const parts = Object.entries(box.warehouses).map(
			([wh, n]) => `<div>${this.link("Warehouse", wh)} <span class="text-muted">× ${n}</span></div>`
		);
		if (box.gone) parts.push(`<div>${this.pill(__("{0} left stock", [box.gone]), "red")}</div>`);
		if (box.in_staging)
			parts.push(`<div>${this.pill(__("{0} in staging", [box.in_staging]), "orange")}</div>`);
		return parts.join("") || `<span class="text-muted">—</span>`;
	}

	// ------------------------------------------------------------------ items

	render_items(d) {
		const all = d.items.filter(
			(i) =>
				this.item_allowed(i.item_code) &&
				this.match(i.item_code, i.item_name, Object.keys(i.templates))
		);
		if (!all.length) return "";
		const page = this.paginate("items", all);
		const rows = page.rows;
		const cell = (s) =>
			s.boxes
				? `<b>${s.qty}</b> <span class="text-muted small">${__("in {0} boxes", [s.boxes])}</span>`
				: "";
		return `
			<div class="text-muted small pko-hint">${__("Click a number to see those boxes.")}</div>
			<div class="pko-table-wrap"><table class="table table-bordered pko-table">
				<thead><tr>
					<th>${__("Item")}</th><th>${__("Waiting to ship")}</th><th>${__("Oldest waiting")}</th>
					<th>${__("Draft")}</th><th>${__("Shipped")}</th><th>${__("Packing Template")}</th>
				</tr></thead>
				<tbody>${rows
					.map(
						(i) => `
					<tr>
						<td>${this.item_link(i.item_code, i.item_name)}</td>
						<td>${
							i.Packed.boxes
								? `<a href="#" class="pko-goto" data-tab="waiting" data-item="${frappe.utils.escape_html(
										i.item_code
								  )}">${cell(i.Packed)}</a>`
								: ""
						}</td>
						<td>${i.oldest_packed ? frappe.datetime.prettyDate(i.oldest_packed) : ""}</td>
						<td>${
							i.Draft.boxes
								? `<a href="#" class="pko-goto" data-tab="drafts" data-item="${frappe.utils.escape_html(
										i.item_code
								  )}">${cell(i.Draft)}</a>`
								: ""
						}</td>
						<td>${
							i.Shipped.boxes
								? `<a href="#" class="pko-goto" data-tab="shipped" data-item="${frappe.utils.escape_html(
										i.item_code
								  )}">${cell(i.Shipped)}</a>`
								: ""
						}</td>
						<td class="small">${Object.entries(i.templates)
							.map(
								([t, n]) =>
									`${this.link(
										"Packing Template",
										t
									)} <span class="text-muted">× ${n}</span>`
							)
							.join("<br>")}</td>
					</tr>`
					)
					.join("")}</tbody>
			</table></div>${page.pager}`;
	}

	// ------------------------------------------------------------------ shipped

	render_shipped(d) {
		const rows = d.shipments.filter(
			(s) =>
				Object.keys(s.items).some((c) => this.item_allowed(c)) &&
				this.date_allowed(s.date) &&
				this.match(s.name, s.party, Object.keys(s.items))
		);
		if (!rows.length) return "";
		const page = this.paginate("shipped", rows);
		const shown = page.rows;
		return `
			<div class="pko-table-wrap"><table class="table table-bordered pko-table">
				<thead><tr>
					<th>${__("Document")}</th><th>${__("Date")}</th><th>${__("Customer")}</th>
					<th>${__("Boxes")}</th><th>${__("Items")}</th>
				</tr></thead>
				<tbody>${shown
					.map(
						(s) => `
					<tr>
						<td>${this.link(s.doctype, s.name)}${s.docstatus === 1 ? "" : ` ${this.pill(__("Not submitted"), "red")}`}
							<div class="text-muted small">${__(s.doctype || "")}</div></td>
						<td>${s.date ? frappe.datetime.str_to_user(s.date) : ""}</td>
						<td>${frappe.utils.escape_html(s.party || "")}</td>
						<td><a href="/desk/package?status=Shipped&${this.link_field(s.doctype)}=${encodeURIComponent(s.name)}">${
							s.boxes
						}</a></td>
						<td>${Object.entries(s.items)
							.map(([code, qty]) => `<div><b>${qty}</b> × ${this.item_link(code)}</div>`)
							.join("")}</td>
					</tr>`
					)
					.join("")}</tbody>
			</table></div>${page.pager}`;
	}

	link_field(doctype) {
		return {
			"Delivery Note": "delivery_note",
			"Sales Invoice": "sales_invoice",
			"Stock Entry": "stock_entry",
		}[doctype];
	}

	// ------------------------------------------------------------------ other

	render_other(d) {
		const unpacked = d.unpacked.filter(
			(u) => this.date_allowed(u.modified) && this.match(u.name, u.packing_template)
		);
		const loose = d.loose_shipped.filter(
			(s) =>
				this.item_allowed(s.item_code) &&
				this.date_allowed(s.posting_datetime) &&
				this.match(s.voucher_no, s.serial_no, s.item_code)
		);
		const by_dn = {};
		loose.forEach((s) => (by_dn[s.voucher_no] = by_dn[s.voucher_no] || []).push(s));
		const up = this.paginate("other_unpacked", unpacked);
		const lp = this.paginate("other_loose", Object.entries(by_dn));
		return `
			<h5 class="pko-h">${__("Unpacked in the last 30 days")} <span class="text-muted">(${
			unpacked.length
		})</span></h5>
			${
				unpacked.length
					? `<div class="pko-table-wrap"><table class="table table-bordered pko-table">
				<thead><tr><th>${__("Package")}</th><th>${__("Packing Template")}</th><th>${__("Unpacked")}</th><th>${__(
							"By"
					  )}</th></tr></thead>
				<tbody>${up.rows
					.map(
						(u) => `<tr>
						<td>${this.link("Package", u.name)}</td>
						<td>${frappe.utils.escape_html(u.packing_template || "")}</td>
						<td>${frappe.datetime.prettyDate(u.modified)}</td>
						<td>${erpnext.entity ? erpnext.entity.user(u.modified_by, { size: 18 }) : u.modified_by}</td>
					</tr>`
					)
					.join("")}</tbody></table></div>${up.pager}`
					: `<div class="text-muted">${__("Nothing found")}</div>`
			}
			<h5 class="pko-h">${__("Shipped without a box, last {0} days", [this.data.history_days])}
				<span class="text-muted">(${loose.length})</span></h5>
			<div class="text-muted small pko-hint">${__(
				"Serial numbers delivered that were never in a submitted package."
			)}</div>
			${
				loose.length
					? `<div class="pko-table-wrap"><table class="table table-bordered pko-table">
				<thead><tr><th>${__("Delivery Note")}</th><th>${__("Item")}</th><th>${__("Serial No")}</th></tr></thead>
				<tbody>${lp.rows
					.map(
						([dn, list]) => `<tr>
						<td>${this.link("Delivery Note", dn)}
							<div class="text-muted small">${frappe.datetime.str_to_user(list[0].posting_datetime)}</div></td>
						<td>${[...new Set(list.map((s) => s.item_code))].map((c) => this.item_link(c)).join("")}</td>
						<td class="small">${list.length} · ${list.map((s) => this.link("Serial No", s.serial_no)).join(" ")}</td>
					</tr>`
					)
					.join("")}</tbody></table></div>${lp.pager}`
					: `<div class="text-muted">${__("Nothing found")}</div>`
			}`;
	}

	// ------------------------------------------------------------------ helpers

	item_link(item_code, item_name) {
		return `${this.link("Item", item_code)}${
			item_name && item_name !== item_code
				? ` <span class="text-muted small">${frappe.utils.escape_html(item_name)}</span>`
				: ""
		}`;
	}

	link(doctype, name, label) {
		if (!name) return "";
		return frappe.utils.get_form_link(doctype, name, true, frappe.utils.escape_html(label || name));
	}

	list_url(doctype) {
		return frappe.utils.get_form_link(doctype, "").replace(/\/$/, "");
	}

	pill(text, color) {
		return `<span class="indicator-pill ${color} pko-pill">${frappe.utils.escape_html(text)}</span>`;
	}

	duration(seconds) {
		if (seconds == null) return "";
		if (seconds < 3600) return __("{0} min", [Math.floor(seconds / 60)]);
		if (seconds < 86400) return __("{0} h", [Math.floor(seconds / 3600)]);
		return __("{0} d", [Math.floor(seconds / 86400)]);
	}
}
