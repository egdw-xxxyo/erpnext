frappe.pages["production-line-overview"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Production Line Overview"),
		single_column: true,
	});
	wrapper.production_line_overview = new ProductionLineOverview(page);
};

frappe.pages["production-line-overview"].on_page_show = function (wrapper) {
	const view = wrapper.production_line_overview;
	if (!view) return;
	const line = frappe.route_options && frappe.route_options.production_line;
	if (line) {
		frappe.route_options = null;
		view.set_line(line);
	}
	view.start_timer();
};

frappe.pages["production-line-overview"].on_page_hide = function (wrapper) {
	wrapper.production_line_overview?.stop_timer();
};

const PLO_REFRESH_SECONDS = 30;
const PLO_TABS = [
	["summary", "fa fa-th-large", "Summary"],
	["lines", "fa fa-industry", "Lines"],
	["today", "fa fa-calendar-check-o", "Today"],
	["units", "fa fa-cube", "Units in work"],
	["work_orders", "fa fa-cogs", "Work Orders"],
	["workplaces", "fa fa-map-marker", "Workplaces"],
];
const PLO_STATES = [
	["free", "Waiting"],
	["in_progress", "In progress"],
	["measured", "Measured, not finished"],
	["waiting_packing", "Waiting for packing"],
	["in_stock", "In stock"],
	["rejected", "Rejected"],
];

class ProductionLineOverview {
	constructor(page) {
		this.page = page;
		this.data = null;
		this.tab = "summary";
		this.filter = "";
		this.line = "";
		this.auto = true;
		this.make();
		this.refresh();
	}

	make() {
		this.page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.page.add_inner_button(__("Auto-refresh"), () => this.toggle_auto());
		this.line_field = this.page.add_field({
			fieldname: "production_line",
			fieldtype: "Link",
			options: "Production Line",
			label: __("Production Line"),
			change: () => {
				this.line = this.line_field.get_value() || "";
				this.render();
			},
		});
		this.search = this.page.add_field({
			fieldname: "search",
			fieldtype: "Data",
			label: __("Search"),
			placeholder: __("Search"),
			change: () => {
				this.filter = (this.search.get_value() || "").trim().toLowerCase();
				this.render_tab();
			},
		});
		this.search.$input.on(
			"input",
			frappe.utils.debounce(() => this.search.$input.trigger("change"), 250)
		);

		this.page.main.html(`
			<div class="production-line-overview">
				<div class="plo-tabs"></div>
				<div class="plo-meta text-muted"></div>
				<div class="plo-body"></div>
			</div>
		`);
		this.$tabs = this.page.main.find(".plo-tabs");
		this.$meta = this.page.main.find(".plo-meta");
		this.$body = this.page.main.find(".plo-body");
		this.$tabs.on("click", ".plo-tab", (e) => {
			this.tab = $(e.currentTarget).data("tab");
			this.render();
		});
		this.$body.on("click", ".plo-goto", (e) => {
			e.preventDefault();
			this.tab = $(e.currentTarget).data("tab");
			this.render();
		});
		this.$body.on("click", ".plo-toggle", (e) =>
			$(e.currentTarget).closest(".plo-card").toggleClass("plo-open")
		);
	}

	set_line(line) {
		this.line = line;
		this.line_field.set_value(line);
		this.tab = "today";
		this.render();
	}

	start_timer() {
		this.stop_timer();
		if (!this.auto) return;
		this.timer = setInterval(() => this.refresh(true), PLO_REFRESH_SECONDS * 1000);
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
				method: "erpnext.manufacturing.page.production_line_overview.production_line_overview.get_overview",
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

	// The line picker narrows every tab; the data itself always covers all lines.
	view() {
		const d = this.data;
		if (!this.line) return d;
		const lines = d.lines.filter((l) => l.name === this.line);
		const benches = new Set(lines.flatMap((l) => l.workplaces.map((w) => w.workplace)));
		const names = new Set([
			...lines.map((l) => l.name),
			...benches,
			...lines.flatMap((l) => l.plan.map((p) => p.item_code)),
			...lines.flatMap((l) => l.plan.map((p) => (d.items[p.item_code] || {}).default_bom)),
		]);
		return {
			...d,
			lines,
			workplaces: d.workplaces.filter((w) => benches.has(w.name)),
			work_orders: d.work_orders.filter((wo) => wo.production_line === this.line),
			attention: d.attention.filter((u) => u.production_line === this.line),
			issues: d.issues.filter((i) => !i.name || names.has(i.name) || i.message.includes(this.line)),
		};
	}

	render() {
		if (!this.data) return;
		this.render_tabs();
		this.render_meta();
		this.render_tab();
	}

	render_tabs() {
		const d = this.view();
		const counts = {
			summary: d.issues.filter((i) => i.level === "error").length || "",
			lines: d.lines.length,
			today: d.lines.reduce((n, l) => n + l.plan.filter((p) => p.enabled).length, 0),
			units: d.attention.length,
			work_orders: d.work_orders.filter((wo) => wo.is_live).length,
			workplaces: d.workplaces.length,
		};
		this.$tabs.html(
			PLO_TABS.map(
				([key, icon, label]) => `
				<button class="btn btn-sm plo-tab ${this.tab === key ? "btn-primary" : "btn-default"}" data-tab="${key}">
					<i class="${icon}"></i> ${__(label)}
					${counts[key] !== "" ? `<span class="plo-count">${counts[key]}</span>` : ""}
				</button>`
			).join("")
		);
	}

	render_meta() {
		if (!this.data) return;
		this.$meta.html(
			`${__("Updated")}: ${frappe.datetime.str_to_user(this.data.generated_at)} · ${
				this.auto ? __("auto-refresh every {0} s", [PLO_REFRESH_SECONDS]) : __("auto-refresh off")
			}`
		);
	}

	render_tab() {
		if (!this.data) return;
		const html = this[`render_${this.tab}`](this.view());
		this.$body.html(html || `<div class="text-muted plo-empty">${__("Nothing found")}</div>`);
	}

	match(...values) {
		if (!this.filter) return true;
		return values.some((v) => v && String(v).toLowerCase().includes(this.filter));
	}

	// ------------------------------------------------------------------ summary

	render_summary(d) {
		const enabled = d.lines.filter((l) => l.enabled);
		const units = this.sum_units(enabled.map((l) => l.units));
		const planned = enabled.reduce(
			(n, l) => n + l.plan.filter((p) => p.enabled).reduce((m, p) => m + p.daily_qty, 0),
			0
		);
		const made = units.in_stock + units.waiting_packing + units.rejected;
		const not_planned = enabled.filter((l) => l.plan_due && !l.planned_today).length;
		const stale = d.work_orders.filter((wo) => wo.is_live && !wo.is_today).length;

		const tile = (tab, icon, value, label, sub) => `
			<a class="plo-tile plo-goto" data-tab="${tab}" href="#">
				<div class="plo-tile-icon"><i class="${icon}"></i></div>
				<div class="plo-tile-value">${value}</div>
				<div class="plo-tile-label">${label}</div>
				<div class="plo-tile-sub text-muted">${sub}</div>
			</a>`;

		const issues = d.issues.filter((i) => this.match(i.message, i.area, i.name));
		const level_icon = {
			error: "fa-times-circle",
			warning: "fa-exclamation-triangle",
			info: "fa-info-circle",
		};
		const level_label = { error: __("Error"), warning: __("Warning"), info: __("Info") };

		return `
			<div class="plo-tiles">
				${tile(
					"lines",
					"fa fa-industry",
					`${enabled.length} / ${d.lines.length}`,
					__("Lines enabled"),
					not_planned
						? __("{0} not planned today", [not_planned])
						: __("today's Work Orders opened")
				)}
				${tile(
					"today",
					"fa fa-calendar-check-o",
					`${made} / ${planned}`,
					__("Made today / daily plan"),
					__("{0} in stock, {1} rejected", [units.in_stock, units.rejected])
				)}
				${tile(
					"units",
					"fa fa-cube",
					units.in_progress + units.measured,
					__("Units in work"),
					__("{0} measured, not finished", [
						d.attention.filter((u) => u.state === "measured").length,
					])
				)}
				${tile(
					"work_orders",
					"fa fa-cogs",
					d.work_orders.filter((wo) => wo.is_live).length,
					__("Open Work Orders"),
					__("{0} from earlier days", [stale])
				)}
				${tile(
					"workplaces",
					"fa fa-map-marker",
					d.workplaces.length,
					__("Workplaces"),
					__("{0} with a unit in work", [
						d.workplaces.filter((w) => w.in_progress.length || w.measured.length).length,
					])
				)}
			</div>
			<div class="plo-flow">
				<span><i class="fa fa-calendar"></i> ${__("Plan")}</span><i class="fa fa-long-arrow-right"></i>
				<span><i class="fa fa-cogs"></i> ${__("Work Order")} (${__(
			"serials"
		)})</span><i class="fa fa-long-arrow-right"></i>
				<span><i class="fa fa-id-card-o"></i> ${__("Job Card")} ${__(
			"per unit"
		)}</span><i class="fa fa-long-arrow-right"></i>
				<span><i class="fa fa-map-marker"></i> ${__("Workplace")}</span><i class="fa fa-long-arrow-right"></i>
				<span><i class="fa fa-check-square-o"></i> ${__(
					"Quality Inspection"
				)}</span><i class="fa fa-long-arrow-right"></i>
				<span><i class="fa fa-archive"></i> ${__("Stock")}</span>
			</div>
			<h5 class="plo-h">${__("Setup checks")} <span class="text-muted">(${issues.length})</span></h5>
			${
				issues.length
					? `<div class="plo-issues">${issues
							.map(
								(i) => `
						<div class="plo-issue plo-${i.level}">
							<i class="fa ${level_icon[i.level]}"></i>
							<span class="plo-issue-level">${level_label[i.level]}</span>
							<span class="plo-issue-area text-muted">${frappe.utils.escape_html(i.area)}</span>
							<span class="plo-issue-msg">${frappe.utils.escape_html(i.message)}</span>
							${i.doctype ? `<span class="plo-issue-link">${this.link(i.doctype, i.name, __("Go to"))}</span>` : ""}
						</div>`
							)
							.join("")}</div>`
					: `<div class="plo-ok"><i class="fa fa-check-circle"></i> ${__(
							"No problems found"
					  )}</div>`
			}
			${this.where_to_find()}
		`;
	}

	where_to_find() {
		const rows = [
			["Production Line", __("Lines: plan, workplaces, warehouses, plan and close-of-day times")],
			["Work Order", __("Work Orders: one per item per day, plus overflow")],
			["Job Card", __("Job Cards: one per unit and operation, the unit's serial")],
			["Serial No", __("Serial numbers: where a unit is now")],
			["Quality Inspection", __("Quality inspections: measurement verdict per unit")],
			["OTDR Measurement", __("OTDR measurements: trace, verdict, label")],
			["Stock Entry", __("Stock entries: a finished unit's Manufacture entry")],
			["Workplace", __("Workplaces: operations, employees, printers")],
			["Error Log", __("Errors of the plan run and the close of day")],
		];
		return `
			<h5 class="plo-h">${__("Where to find")}</h5>
			<div class="plo-where">
				${rows
					.map(
						([dt, text]) => `
					<div><a href="${this.list_url(dt)}">${__(dt)}</a>
					<span class="text-muted">— ${frappe.utils.escape_html(text)}</span></div>`
					)
					.join("")}
				<div><a href="/desk/production-flow">${__("Production Flow")}</a>
				<span class="text-muted">— ${__("BOM operations of a line drawn as a diagram")}</span></div>
			</div>`;
	}

	// ------------------------------------------------------------------ lines

	render_lines(d) {
		const rows = d.lines.filter((l) =>
			this.match(
				l.name,
				l.line_type,
				...l.workplaces.map((w) => w.workplace),
				...l.plan.map((p) => p.item_code)
			)
		);
		if (!rows.length) return "";
		const dash = `<span class="text-muted">—</span>`;
		return `<div class="text-muted small plo-hint">${__(
			"Click a line to see its warehouses and the last plan and close-of-day runs."
		)}</div>${rows
			.map(
				(l) => `
			<div class="plo-card ${l.enabled ? "" : "plo-muted"}">
				<div class="plo-card-head plo-toggle">
					<i class="fa fa-industry"></i>
					<b>${frappe.utils.escape_html(l.line_name || l.name)}</b>
					${this.pill(__(l.line_type), "blue")}
					${l.enabled ? "" : this.pill(__("Disabled"), "gray")}
					${
						l.enabled && l.plan_due
							? l.planned_today
								? this.pill(__("Planned today"), "green")
								: this.pill(__("Not planned today"), "red")
							: ""
					}
					${l.manufacture_at_packing ? this.pill(__("Into stock at packing"), "purple") : ""}
					<span class="plo-card-right text-muted small">
						<a href="/desk/production-flow?production_line=${encodeURIComponent(l.name)}">${__("Production Flow")}</a> ·
						${this.link("Production Line", l.name, __("Go to"))}</span>
				</div>
				<div class="plo-card-sub text-muted small">
					${__("Plan at")} ${(l.plan_time || "—").slice(0, 5)} ·
					${
						l.cleanup_enabled
							? `${__("Close day at")} ${(l.cleanup_time || "—").slice(0, 5)}`
							: __("Day is not closed")
					} · ${__("Overflow")}: ${l.overflow_qty || 1}
				</div>
				<div class="plo-tree">
					<div class="plo-node"><b>${__("Workplaces")}</b>: ${
					l.workplaces
						.map(
							(w) =>
								`${this.link("Workplace", w.workplace)}${
									w.enabled ? "" : ` ${this.pill(__("off"), "gray")}`
								}`
						)
						.join(", ") || dash
				}</div>
					${
						l.plan.length
							? l.plan
									.map(
										(p) => `
					<div class="plo-node ${p.enabled ? "" : "plo-muted"}">
						<span class="plo-trigger">${p.daily_qty} ${__("per day")}</span>
						<i class="fa fa-long-arrow-right text-muted"></i>
						${this.item_link(p.item_code)}
						<span class="text-muted small">${__("at")}</span> ${p.workplace ? this.link("Workplace", p.workplace) : dash}
						${p.enabled ? "" : this.pill(__("off"), "gray")}
					</div>`
									)
									.join("")
							: `<div class="plo-node text-muted">${__("Nothing planned")}</div>`
					}
				</div>
				<div class="plo-details">
					<div class="plo-detail-grid">
						<div class="plo-kv">
							<span class="text-muted">${__("Company")}</span><span>${frappe.utils.escape_html(l.company || "—")}</span>
							<span class="text-muted">${__("Source Warehouse")}</span><span>${this.wh(l.source_warehouse)}</span>
							<span class="text-muted">${__("Work-in-progress warehouse")}</span><span>${this.wh(l.wip_warehouse)}</span>
							<span class="text-muted">${__("Finished goods warehouse")}</span><span>${this.wh(l.fg_warehouse)}</span>
							<span class="text-muted">${__("Reject warehouse")}</span><span>${this.wh(l.reject_warehouse)}</span>
						</div>
						<div>
							<div class="plo-label">${__("Last plan run")} ${
					l.last_run_on
						? `<span class="text-muted">${frappe.datetime.prettyDate(l.last_run_on)}</span>`
						: ""
				}</div>
							<div class="plo-pre">${frappe.utils.escape_html(l.last_result || "—")}</div>
							<div class="plo-label">${__("Last close of day")} ${
					l.last_cleanup_on
						? `<span class="text-muted">${frappe.datetime.prettyDate(l.last_cleanup_on)}</span>`
						: ""
				}</div>
							<div class="plo-pre">${frappe.utils.escape_html(l.last_cleanup_result || "—")}</div>
						</div>
					</div>
				</div>
			</div>`
			)
			.join("")}`;
	}

	// ------------------------------------------------------------------ today

	render_today(d) {
		const rows = [];
		d.lines
			.filter((l) => l.enabled)
			.forEach((l) =>
				l.plan
					.filter((p) => p.enabled)
					.forEach((p) => {
						const item = d.items[p.item_code] || {};
						if (this.match(l.name, p.item_code, item.item_name, p.workplace, ...p.work_orders))
							rows.push({ line: l, plan: p, item });
					})
			);
		if (!rows.length) return "";
		return `
			${this.legend()}
			<div class="plo-table-wrap"><table class="table table-bordered plo-table">
				<thead><tr>
					<th>${__("Item")}</th><th>${__("Line")} / ${__("Workplace")}</th><th>${__("Daily plan")}</th>
					<th>${__("Today's Work Orders")}</th><th>${__("Units today")}</th>
				</tr></thead>
				<tbody>${rows
					.map(({ line, plan, item }) => {
						const u = plan.units;
						const made = u.in_stock + u.waiting_packing + u.rejected;
						return `
					<tr>
						<td>${this.item_link(plan.item_code)}${
							item.default_bom
								? `<div class="text-muted small">${this.link("BOM", item.default_bom)}</div>`
								: ""
						}</td>
						<td>${this.link("Production Line", line.name)}<div>${
							plan.workplace ? this.link("Workplace", plan.workplace) : ""
						}</div></td>
						<td><b>${made}</b> / ${plan.daily_qty}
							<div class="text-muted small">${__("{0} left to hand out", [u.free])}</div></td>
						<td>${
							plan.work_orders.map((w) => this.link("Work Order", w)).join("<br>") ||
							`<span class="text-danger">${__("None yet")}</span>`
						}${
							plan.overflow_work_orders
								? `<div>${this.pill(
										__("{0} overflow", [plan.overflow_work_orders]),
										"orange"
								  )}</div>`
								: ""
						}</td>
						<td style="min-width: 220px">${this.bar(u)}${this.state_counts(u)}</td>
					</tr>`;
					})
					.join("")}</tbody>
			</table></div>`;
	}

	// ------------------------------------------------------------------ units

	render_units(d) {
		const rows = d.attention.filter((u) =>
			this.match(
				u.serial_no,
				u.item_code,
				u.work_order,
				u.workplace,
				u.workstation,
				u.by_name,
				u.job_card
			)
		);
		if (!rows.length) return "";
		const state_color = { in_progress: "blue", measured: "purple", rejected: "red" };
		return `
			<div class="plo-hint text-muted small">${__(
				"Units taken at a workplace and not finished yet, and units rejected today. A measured unit is handed back to the workplace before a new one."
			)}</div>
			<div class="plo-table-wrap"><table class="table table-bordered plo-table">
				<thead><tr>
					<th>${__("Serial No")}</th><th>${__("State")}</th><th>${__("Workplace")}</th>
					<th>${__("Job Card")}</th><th>${__("Quality Inspection")}</th><th>${__("Since")}</th>
				</tr></thead>
				<tbody>${rows
					.map(
						(u) => `
					<tr>
						<td>${this.link("Serial No", u.serial_no)}<div class="text-muted small">${frappe.utils.escape_html(
							u.item_code
						)}</div></td>
						<td>${this.pill(this.state_label(u.state), state_color[u.state])}
							${
								u.open_operations.length
									? `<div class="text-muted small">${__("Open")}: ${u.open_operations
											.map((o) => frappe.utils.escape_html(o))
											.join(", ")}</div>`
									: ""
							}</td>
						<td>${u.workplace ? this.link("Workplace", u.workplace) : ""}
							<div class="text-muted small">${frappe.utils.escape_html(u.workstation || "")}</div></td>
						<td>${this.link("Job Card", u.job_card)}<div class="text-muted small">${this.link(
							"Work Order",
							u.work_order
						)}</div></td>
						<td>${
							u.quality_inspection
								? `${this.link("Quality Inspection", u.quality_inspection)} ${
										u.qi_status
											? this.pill(
													__(u.qi_status),
													u.qi_status === "Accepted" ? "green" : "red"
											  )
											: ""
								  }`
								: `<span class="text-muted">—</span>`
						}</td>
						<td>${u.age != null ? this.ago(u.age) : "—"}
							<div class="text-muted small">${frappe.utils.escape_html(u.by_name || "")}</div></td>
					</tr>`
					)
					.join("")}</tbody>
			</table></div>`;
	}

	// ------------------------------------------------------------------ work orders

	render_work_orders(d) {
		const rows = d.work_orders.filter((wo) =>
			this.match(wo.name, wo.production_item, wo.production_line, wo.status)
		);
		if (!rows.length) return "";
		const status_color = {
			"Not Started": "orange",
			"In Process": "blue",
			Completed: "green",
			Stopped: "gray",
			Closed: "gray",
		};
		return `
			<div class="plo-hint text-muted small">${__(
				"Open Work Orders of the lines' items and those opened in the last {0} days.",
				[d.history_days]
			)}</div>
			${this.legend()}
			<div class="plo-table-wrap"><table class="table table-bordered plo-table">
				<thead><tr>
					<th>${__("Work Order")}</th><th>${__("Item")}</th><th>${__("Status")}</th>
					<th>${__("Qty")}</th><th>${__("Units")}</th>
				</tr></thead>
				<tbody>${rows
					.map(
						(wo) => `
					<tr class="${wo.is_live ? "" : "plo-muted"}">
						<td>${this.link("Work Order", wo.name)}
							<div class="text-muted small">${frappe.datetime.str_to_user(wo.creation).slice(0, 16)}
							${wo.reason === "overflow" ? this.pill(__("overflow"), "orange") : ""}</div></td>
						<td>${this.item_link(wo.production_item)}<div class="text-muted small">${frappe.utils.escape_html(
							wo.production_line || ""
						)}</div></td>
						<td>${this.pill(__(wo.status), status_color[wo.status] || "gray")}
							${wo.is_live && !wo.is_today ? `<div class="small text-danger">${__("from an earlier day")}</div>` : ""}</td>
						<td>${flt(wo.produced_qty)} / ${flt(wo.qty)}</td>
						<td style="min-width: 220px">${this.bar(wo.units)}${this.state_counts(wo.units)}</td>
					</tr>`
					)
					.join("")}</tbody>
			</table></div>`;
	}

	// ------------------------------------------------------------------ workplaces

	render_workplaces(d) {
		const line_of = {};
		d.lines.forEach((l) => l.workplaces.forEach((w) => (line_of[w.workplace] = l.name)));
		const rows = d.workplaces.filter((w) =>
			this.match(
				w.name,
				w.label,
				line_of[w.name],
				...w.operations.map((o) => o.operation),
				...w.printers.map((p) => p.label_printer),
				...w.in_progress,
				...w.measured
			)
		);
		if (!rows.length) return "";
		const dash = `<span class="text-muted">—</span>`;
		return `
			<div class="plo-table-wrap"><table class="table table-bordered plo-table">
				<thead><tr>
					<th>${__("Workplace")}</th><th>${__("Operations")}</th><th>${__("Employees")}</th>
					<th>${__("Printers")}</th><th>${__("Script")} / OTDR</th><th>${__("Units in work")}</th>
				</tr></thead>
				<tbody>${rows
					.sort((a, b) => a.name.localeCompare(b.name))
					.map(
						(w) => `
					<tr class="${w.is_active ? "" : "plo-muted"}">
						<td>${this.link("Workplace", w.name, w.label)}<div class="text-muted small">${frappe.utils.escape_html(
							line_of[w.name] || ""
						)}</div></td>
						<td>${
							w.operations
								.map(
									(o) =>
										`<div>${frappe.utils.escape_html(
											o.operation || ""
										)} <span class="text-muted small">${frappe.utils.escape_html(
											o.workstation || ""
										)}</span></div>`
								)
								.join("") || dash
						}</td>
						<td>${w.employees || dash}</td>
						<td>${
							w.printers
								.map(
									(p) =>
										`${this.link("Label Printer", p.label_printer)}${
											p.is_default
												? ` <span class="text-muted small">${__("default")}</span>`
												: ""
										}`
								)
								.join("<br>") || dash
						}</td>
						<td>${w.workplace_script ? this.link("Workplace Script", w.workplace_script) : dash}
							${w.otdr_configuration ? `<div>${this.link("OTDR Configuration", w.otdr_configuration)}</div>` : ""}</td>
						<td>${
							w.in_progress.length || w.measured.length
								? [
										...w.in_progress.map(
											(s) =>
												`${this.pill(__("In progress"), "blue")} ${this.link(
													"Serial No",
													s
												)}`
										),
										...w.measured.map(
											(s) =>
												`${this.pill(__("Measured"), "purple")} ${this.link(
													"Serial No",
													s
												)}`
										),
								  ].join("<br>")
								: dash
						}</td>
					</tr>`
					)
					.join("")}</tbody>
			</table></div>`;
	}

	// ------------------------------------------------------------------ helpers

	sum_units(list) {
		const out = Object.fromEntries(PLO_STATES.map(([k]) => [k, 0]));
		list.forEach((u) => PLO_STATES.forEach(([k]) => (out[k] += (u && u[k]) || 0)));
		return out;
	}

	state_label(state) {
		const row = PLO_STATES.find(([k]) => k === state);
		return row ? __(row[1]) : state;
	}

	bar(units) {
		const total = PLO_STATES.reduce((n, [k]) => n + (units[k] || 0), 0);
		if (!total) return `<span class="text-muted">—</span>`;
		return `<div class="plo-bar">${PLO_STATES.filter(([k]) => units[k])
			.map(
				([k]) =>
					`<span class="plo-st-${k}" style="width: ${
						(units[k] / total) * 100
					}%" title="${this.state_label(k)}: ${units[k]}"></span>`
			)
			.join("")}</div>`;
	}

	state_counts(units) {
		return `<div class="text-muted small">${PLO_STATES.filter(([k]) => units[k])
			.map(([k]) => `${this.state_label(k)}: ${units[k]}`)
			.join(" · ")}</div>`;
	}

	legend() {
		return `<div class="plo-legend plo-hint">${PLO_STATES.map(
			([k]) => `<span><i class="plo-st-${k}"></i>${this.state_label(k)}</span>`
		).join("")}</div>`;
	}

	item_link(item_code) {
		const item = (this.data.items || {})[item_code] || {};
		return `${this.link("Item", item_code)}${
			item.item_name && item.item_name !== item_code
				? `<div class="text-muted small">${frappe.utils.escape_html(item.item_name)}</div>`
				: ""
		}`;
	}

	wh(name) {
		return name ? this.link("Warehouse", name) : `<span class="text-muted">—</span>`;
	}

	link(doctype, name, label) {
		if (!name) return "";
		return frappe.utils.get_form_link(doctype, name, true, frappe.utils.escape_html(label || name));
	}

	list_url(doctype) {
		return frappe.utils.get_form_link(doctype, "").replace(/\/$/, "");
	}

	pill(text, color) {
		return `<span class="indicator-pill ${color} plo-pill">${frappe.utils.escape_html(text)}</span>`;
	}

	ago(seconds) {
		return __("{0} ago", [this.duration(seconds)]);
	}

	duration(seconds) {
		if (seconds == null) return "";
		if (seconds < 60) return __("{0} s", [seconds]);
		if (seconds < 3600) return __("{0} min", [Math.floor(seconds / 60)]);
		if (seconds < 86400) return __("{0} h", [Math.floor(seconds / 3600)]);
		return __("{0} d", [Math.floor(seconds / 86400)]);
	}
}
