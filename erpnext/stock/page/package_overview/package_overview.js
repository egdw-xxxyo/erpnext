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
const PKO_ROW_LIMIT = 300;
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
		this.filter = "";
		this.items = [];
		this.groups = [];
		this.auto = true;
		this.make();
		this.refresh();
	}

	make() {
		this.page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.page.add_inner_button(__("Auto-refresh"), () => this.toggle_auto());
		this.page.add_inner_button(__("Package"), () => frappe.set_route("List", "Package"));
		this.items_field = this.page.add_field({
			fieldname: "items",
			fieldtype: "MultiSelectList",
			label: __("Filter items"),
			placeholder: __("Filter items"),
			get_data: (txt) => this.item_options(txt),
			change: () => this.set_filter("items", this.items_field.get_value()),
		});
		this.groups_field = this.page.add_field({
			fieldname: "item_groups",
			fieldtype: "MultiSelectList",
			label: __("Filter categories"),
			placeholder: __("Filter categories"),
			get_data: (txt) => this.group_options(txt),
			change: () => this.set_filter("groups", this.groups_field.get_value()),
		});
		this.search = this.page.add_field({
			fieldname: "search",
			fieldtype: "Data",
			label: __("Search"),
			placeholder: __("Package, serial no, item, order"),
			change: () => {
				this.filter = (this.search.get_value() || "").trim().toLowerCase();
				this.render();
			},
		});
		this.search.$input.on(
			"input",
			frappe.utils.debounce(() => this.search.$input.trigger("change"), 250)
		);

		this.page.main.html(`
			<div class="package-overview">
				<div class="pko-tabs"></div>
				<div class="pko-meta text-muted"></div>
				<div class="pko-filters"></div>
				<div class="pko-body"></div>
			</div>
		`);
		this.$tabs = this.page.main.find(".pko-tabs");
		this.$meta = this.page.main.find(".pko-meta");
		this.$filters = this.page.main.find(".pko-filters");
		this.$filters.on("click", ".pko-chip-x", (e) => {
			const $chip = $(e.currentTarget).closest(".pko-chip");
			const kind = $chip.data("kind");
			this.set_filter(
				kind,
				this[kind].filter((v) => v !== String($chip.data("value"))),
				true
			);
		});
		this.$filters.on("click", ".pko-clear", () => {
			this.set_filter("items", [], true);
			this.set_filter("groups", [], true);
		});
		this.$body = this.page.main.find(".pko-body");
		this.$tabs.on("click", ".pko-tab", (e) => {
			this.tab = $(e.currentTarget).data("tab");
			this.render();
		});
		this.$body.on("click", ".pko-goto", (e) => {
			e.preventDefault();
			this.tab = $(e.currentTarget).data("tab");
			const item = $(e.currentTarget).data("item");
			if (item && !this.items.includes(String(item))) {
				this.set_filter("items", [...this.items, String(item)], true);
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

	// Item and category filters narrow every tab; the data itself always covers all boxes.
	set_filter(kind, values, sync_field) {
		this[kind] = [...new Set((values || []).filter(Boolean).map(String))];
		if (sync_field) {
			const field = kind === "items" ? this.items_field : this.groups_field;
			this.syncing = true;
			field.set_value(this[kind]);
			this.syncing = false;
		}
		if (!this.syncing) this.render();
	}

	item_options(txt) {
		const q = (txt || "").toLowerCase();
		return (this.data?.items || [])
			.filter((i) => !q || `${i.item_code} ${i.item_name || ""}`.toLowerCase().includes(q))
			.map((i) => ({
				value: i.item_code,
				description: i.item_name !== i.item_code ? i.item_name : "",
			}));
	}

	group_options(txt) {
		const q = (txt || "").toLowerCase();
		const counts = {};
		Object.values(this.data?.item_groups || {}).forEach((g) => (counts[g] = (counts[g] || 0) + 1));
		return Object.keys(counts)
			.sort()
			.filter((g) => !q || g.toLowerCase().includes(q))
			.map((g) => ({ value: g, description: __("{0} items in group", [counts[g]]) }));
	}

	item_allowed(item_code) {
		if (this.items.length && !this.items.includes(item_code)) return false;
		if (this.groups.length && !this.groups.includes((this.data.item_groups || {})[item_code]))
			return false;
		return true;
	}

	view() {
		const d = this.data;
		if (!this.items.length && !this.groups.length) return d;
		const ok = (code) => this.item_allowed(code);
		const has = (box) => box.contents.some((c) => ok(c.item_code));
		return {
			...d,
			waiting: d.waiting.filter(has),
			drafts: d.drafts.filter(has),
			items: d.items.filter((i) => ok(i.item_code)),
			shipments: d.shipments.filter((s) => Object.keys(s.items).some(ok)),
			loose_shipped: d.loose_shipped.filter((s) => ok(s.item_code)),
		};
	}

	render_filters() {
		const names = Object.fromEntries((this.data.items || []).map((i) => [i.item_code, i.item_name]));
		const chip = (kind, value, label) => `
			<span class="pko-chip" data-kind="${kind}" data-value="${frappe.utils.escape_html(value)}">
				${frappe.utils.escape_html(label)}
				<a class="pko-chip-x" title="${__("Remove")}"><i class="fa fa-times"></i></a>
			</span>`;
		const chips = [
			...this.groups.map((g) => chip("groups", g, `${__("Category")}: ${g}`)),
			...this.items.map((i) => chip("items", i, names[i] || i)),
		];
		this.$filters.html(
			chips.length
				? `<span class="text-muted">${__("Filters")}:</span> ${chips.join("")}
				   <a class="pko-clear">${__("Clear filters")}</a>`
				: ""
		);
	}

	render() {
		if (!this.data) return;
		this.render_tabs();
		this.render_meta();
		this.render_filters();
		const html = this[`render_${this.tab}`](this.view());
		this.$body.html(html || `<div class="text-muted pko-empty">${__("Nothing found")}</div>`);
	}

	render_tabs() {
		const d = this.view();
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
		if (!this.filter) return true;
		return values.flat().some((v) => v && String(v).toLowerCase().includes(this.filter));
	}

	box_match(box) {
		return this.match(
			box.name,
			box.packing_template,
			box.sales_order,
			box.bpak,
			box.pallet,
			box.serials,
			box.contents.map((c) => [c.item_code, c.item_name]),
			Object.keys(box.warehouses)
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
		const shown = issues.slice(0, PKO_ROW_LIMIT);

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
							.join("")}</div>${this.more(issues.length)}`
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
		const shown = rows.slice(0, PKO_ROW_LIMIT);
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
			</table></div>${this.more(rows.length)}`;
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
		const rows = d.items.filter((i) => this.match(i.item_code, i.item_name, Object.keys(i.templates)));
		if (!rows.length) return "";
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
			</table></div>`;
	}

	// ------------------------------------------------------------------ shipped

	render_shipped(d) {
		const rows = d.shipments.filter((s) => this.match(s.name, s.party, Object.keys(s.items)));
		if (!rows.length) return "";
		const shown = rows.slice(0, PKO_ROW_LIMIT);
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
			</table></div>${this.more(rows.length)}`;
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
		const unpacked = d.unpacked.filter((u) => this.match(u.name, u.packing_template));
		const loose = d.loose_shipped.filter((s) => this.match(s.voucher_no, s.serial_no, s.item_code));
		const by_dn = {};
		loose.forEach((s) => (by_dn[s.voucher_no] = by_dn[s.voucher_no] || []).push(s));
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
				<tbody>${unpacked
					.map(
						(u) => `<tr>
						<td>${this.link("Package", u.name)}</td>
						<td>${frappe.utils.escape_html(u.packing_template || "")}</td>
						<td>${frappe.datetime.prettyDate(u.modified)}</td>
						<td>${erpnext.entity ? erpnext.entity.user(u.modified_by, { size: 18 }) : u.modified_by}</td>
					</tr>`
					)
					.join("")}</tbody></table></div>`
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
				<tbody>${Object.entries(by_dn)
					.map(
						([dn, list]) => `<tr>
						<td>${this.link("Delivery Note", dn)}
							<div class="text-muted small">${frappe.datetime.str_to_user(list[0].posting_datetime)}</div></td>
						<td>${[...new Set(list.map((s) => s.item_code))].map((c) => this.item_link(c)).join("")}</td>
						<td class="small">${list.length} · ${list.map((s) => this.link("Serial No", s.serial_no)).join(" ")}</td>
					</tr>`
					)
					.join("")}</tbody></table></div>`
					: `<div class="text-muted">${__("Nothing found")}</div>`
			}`;
	}

	// ------------------------------------------------------------------ helpers

	more(total) {
		return total > PKO_ROW_LIMIT
			? `<div class="text-muted small">${__("Showing {0} of {1}. Narrow with the search or the item.", [
					PKO_ROW_LIMIT,
					total,
			  ])}</div>`
			: "";
	}

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
