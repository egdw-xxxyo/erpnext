frappe.pages["scanner-overview"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Scanner Overview"),
		single_column: true,
	});
	wrapper.scanner_overview = new ScannerOverview(page);
};

frappe.pages["scanner-overview"].on_page_show = function (wrapper) {
	wrapper.scanner_overview?.start_timer();
};

frappe.pages["scanner-overview"].on_page_hide = function (wrapper) {
	wrapper.scanner_overview?.stop_timer();
};

const SO_REFRESH_SECONDS = 15;
const SO_TABS = [
	["summary", "fa fa-th-large", "Summary"],
	["scanners", "fa fa-barcode", "Scanners"],
	["workplaces", "fa fa-map-marker", "Workplaces"],
	["scripts", "fa fa-sitemap", "Scripts and Flows"],
	["printers", "fa fa-print", "Printers"],
	["commands", "fa fa-terminal", "Commands"],
];

class ScannerOverview {
	constructor(page) {
		this.page = page;
		this.data = null;
		this.tab = "summary";
		this.filter = "";
		this.auto = true;
		this.make();
		this.refresh();
	}

	make() {
		this.page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.page.add_inner_button(__("Auto-refresh"), () => this.toggle_auto());
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
			<div class="scanner-overview">
				<div class="so-tabs"></div>
				<div class="so-meta text-muted"></div>
				<div class="so-body"></div>
			</div>
		`);
		this.$tabs = this.page.main.find(".so-tabs");
		this.$meta = this.page.main.find(".so-meta");
		this.$body = this.page.main.find(".so-body");
		this.$tabs.on("click", ".so-tab", (e) => {
			this.tab = $(e.currentTarget).data("tab");
			this.render();
		});
		this.$body.on("click", ".so-goto", (e) => {
			e.preventDefault();
			this.tab = $(e.currentTarget).data("tab");
			this.render();
		});
		this.$body.on("click", ".so-check-printer", (e) =>
			this.check_printer($(e.currentTarget).data("printer"))
		);
		this.$body.on("click", ".so-toggle", (e) =>
			$(e.currentTarget).closest(".so-card").toggleClass("so-open")
		);
	}

	start_timer() {
		this.stop_timer();
		if (!this.auto) return;
		this.timer = setInterval(() => this.refresh(true), SO_REFRESH_SECONDS * 1000);
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
				method: "erpnext.devices.page.scanner_overview.scanner_overview.get_overview",
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

	check_printer(printer) {
		frappe.show_alert({ message: __("Checking printer {0}…", [printer]), indicator: "blue" });
		frappe
			.call({
				method: "erpnext.devices.doctype.label_printer.label_printer.check_connection",
				args: { printer_name: printer },
			})
			.then((r) => {
				const ok = r.message && r.message.connected;
				frappe.show_alert({
					message: ok
						? __("Printer {0} is reachable", [printer])
						: __("Printer {0} is not reachable: {1}", [
								printer,
								(r.message && r.message.status) || "",
						  ]),
					indicator: ok ? "green" : "red",
				});
				this.refresh(true);
			});
	}

	render() {
		if (!this.data) return;
		this.render_tabs();
		this.render_meta();
		this.render_tab();
	}

	render_tabs() {
		const d = this.data;
		const counts = {
			summary: d.issues.filter((i) => i.level === "error").length || "",
			scanners: d.scanners.length,
			workplaces: d.workplaces.length,
			scripts: d.scripts.filter((s) => !s.parent_script).length,
			printers: d.printers.length,
			commands: d.commands.length,
		};
		this.$tabs.html(
			SO_TABS.map(
				([key, icon, label]) => `
				<button class="btn btn-sm so-tab ${this.tab === key ? "btn-primary" : "btn-default"}" data-tab="${key}">
					<i class="${icon}"></i> ${__(label)}
					${counts[key] !== "" ? `<span class="so-count">${counts[key]}</span>` : ""}
				</button>`
			).join("")
		);
	}

	render_meta() {
		if (!this.data) return;
		this.$meta.html(
			`${__("Updated")}: ${frappe.datetime.str_to_user(this.data.generated_at)} · ${
				this.auto ? __("auto-refresh every {0} s", [SO_REFRESH_SECONDS]) : __("auto-refresh off")
			}`
		);
	}

	render_tab() {
		if (!this.data) return;
		const html = this[`render_${this.tab}`]();
		this.$body.html(html || `<div class="text-muted so-empty">${__("Nothing found")}</div>`);
	}

	match(...values) {
		if (!this.filter) return true;
		return values.some((v) => v && String(v).toLowerCase().includes(this.filter));
	}

	// ------------------------------------------------------------------ summary

	render_summary() {
		const d = this.data;
		const online = d.scanners.filter((s) => s.online).length;
		const busy = d.scanners.filter((s) => s.state).length;
		const printers_ok = d.printers.filter((p) => p.is_enabled && p.last_status === "Ready").length;
		const failed = d.printers.reduce((n, p) => n + (p.jobs_24h.Failed || 0), 0);
		const roots = d.scripts.filter((s) => !s.parent_script && s.is_active).length;
		const flows = d.scripts.filter((s) => s.parent_script && s.is_active).length;

		const tile = (tab, icon, value, label, sub) => `
			<a class="so-tile so-goto" data-tab="${tab}" href="#">
				<div class="so-tile-icon"><i class="${icon}"></i></div>
				<div class="so-tile-value">${value}</div>
				<div class="so-tile-label">${label}</div>
				<div class="so-tile-sub text-muted">${sub}</div>
			</a>`;

		const issues = d.issues.filter((i) => this.match(i.message, i.area, i.name));
		const level_icon = {
			error: "fa-times-circle",
			warning: "fa-exclamation-triangle",
			info: "fa-info-circle",
		};
		const level_label = { error: __("Error"), warning: __("Warning"), info: __("Info") };

		return `
			<div class="so-tiles">
				${tile(
					"scanners",
					"fa fa-barcode",
					`${online} / ${d.scanners.length}`,
					__("Scanners online"),
					__("{0} in a flow now", [busy])
				)}
				${tile(
					"workplaces",
					"fa fa-map-marker",
					d.workplaces.length,
					__("Workplaces"),
					__("{0} without own script", [d.workplaces.filter((w) => w.uses_default_script).length])
				)}
				${tile("scripts", "fa fa-sitemap", roots, __("Active scripts"), __("{0} flows", [flows]))}
				${tile(
					"printers",
					"fa fa-print",
					`${printers_ok} / ${d.printers.length}`,
					__("Printers ready"),
					__("{0} failed jobs in 24 h", [failed])
				)}
				${tile("commands", "fa fa-terminal", d.commands.length, __("Commands"), __("CMD-… barcodes"))}
			</div>
			<div class="so-flow">
				<span><i class="fa fa-barcode"></i> ${__("Scanner")}</span><i class="fa fa-long-arrow-right"></i>
				<span><i class="fa fa-map-marker"></i> ${__("Workplace")}</span><i class="fa fa-long-arrow-right"></i>
				<span><i class="fa fa-sitemap"></i> ${__("Script")} → ${__("Flow")} → ${__(
			"Flow state"
		)}</span><i class="fa fa-long-arrow-right"></i>
				<span><i class="fa fa-print"></i> ${__("Workplace printer")}</span>
			</div>
			<h5 class="so-h">${__("Setup checks")} <span class="text-muted">(${issues.length})</span></h5>
			${
				issues.length
					? `<div class="so-issues">${issues
							.map(
								(i) => `
						<div class="so-issue so-${i.level}">
							<i class="fa ${level_icon[i.level]}"></i>
							<span class="so-issue-level">${level_label[i.level]}</span>
							<span class="so-issue-area text-muted">${frappe.utils.escape_html(i.area)}</span>
							<span class="so-issue-msg">${frappe.utils.escape_html(i.message)}</span>
							${i.doctype ? `<span class="so-issue-link">${this.link(i.doctype, i.name, __("Go to"))}</span>` : ""}
						</div>`
							)
							.join("")}</div>`
					: `<div class="so-ok"><i class="fa fa-check-circle"></i> ${__("No problems found")}</div>`
			}
			${this.where_to_find()}
		`;
	}

	where_to_find() {
		const rows = [
			["Scanner", __("Scanners: device key, workplace, employee, scan log")],
			["Workplace", __("Workplaces: WP-… barcode, printers")],
			["Workplace Script", __("Scripts: states, flows, versions, workplaces")],
			["Device Script", __("Script libraries used as scripts.<name>")],
			["Scanner Command", __("Commands: CMD-… barcodes, print a sheet via Actions → Print Labels")],
			["Label Printer", __("Printers: IP, loaded labels, connection check")],
			["Print Job", __("Print jobs: status, log, label preview")],
			["Packing Template", __("Packing templates: PKG-… barcodes")],
			["Scanner Configuration", __("Display size, message format, timeouts")],
		];
		return `
			<h5 class="so-h">${__("Where to find")}</h5>
			<div class="so-where">
				${rows
					.map(
						([dt, text]) => `
					<div><a href="${this.list_url(dt)}">${__(dt)}</a>
					<span class="text-muted">— ${frappe.utils.escape_html(text)}</span></div>`
					)
					.join("")}
			</div>`;
	}

	// ------------------------------------------------------------------ scanners

	render_scanners() {
		const rows = this.data.scanners.filter((s) =>
			this.match(s.label, s.workplace, s.employee_name, s.script, s.subflow, s.state_label, s.state)
		);
		if (!rows.length) return "";
		return `
			<div class="so-table-wrap"><table class="table table-bordered so-table">
				<thead><tr>
					<th>${__("Scanner")}</th><th>${__("Status")}</th><th>${__("Workplace")}</th>
					<th>${__("Employee")}</th><th>${__("Current flow / state")}</th><th>${__("Last scan")}</th>
				</tr></thead>
				<tbody>${rows.map((s) => this.scanner_row(s)).join("")}</tbody>
			</table></div>`;
	}

	scanner_row(s) {
		let status;
		if (!s.is_active) status = this.pill(__("Disabled"), "gray");
		else if (s.online) status = this.pill(__("Active recently"), "green");
		else if (s.last_active_ago != null) status = this.pill(__("Idle"), "orange");
		else status = this.pill(__("Never used"), "gray");

		const seen =
			s.last_active_ago != null
				? `<div class="text-muted small">${this.ago(s.last_active_ago)}</div>`
				: "";

		let flow = `<span class="text-muted">${__("Waiting")}</span>`;
		if (s.state) {
			flow = `
				<div><b>${frappe.utils.escape_html(s.subflow || s.script || "")}</b></div>
				<div>${this.pill(s.state_label || s.state, "blue")}
				<span class="text-muted small">${this.ago(s.state_age)} / ${__("resets after {0}", [
				this.duration(s.state_timeout),
			])}</span></div>
				${
					s.context
						? `<div class="so-ctx">${Object.entries(s.context)
								.map(
									([k, v]) =>
										`<span><b>${frappe.utils.escape_html(
											k
										)}</b>: ${frappe.utils.escape_html(v)}</span>`
								)
								.join("")}</div>`
						: ""
				}`;
		} else if (s.state_expired) {
			flow = `<span class="text-muted">${__("State expired")}</span>`;
		}
		if (s.script && !s.state) {
			flow += `<div class="text-muted small">${__("Script")}: ${frappe.utils.escape_html(
				s.script
			)}</div>`;
		}

		let last = `<span class="text-muted">—</span>`;
		if (s.last_scan) {
			const l = s.last_scan;
			const msg = (l.error_message || l.result_message || "").split("\n").slice(1).join(" ");
			const failed = l.status === "Error" || /помилка|error/i.test(msg);
			last = `
				<div><code>${frappe.utils.escape_html(l.raw_data || "")}</code>
				<span class="text-muted small">${frappe.datetime.prettyDate(l.timestamp)}</span></div>
				<div class="small ${failed ? "text-danger" : "text-muted"}">${frappe.utils.escape_html(
				msg.slice(0, 140)
			)}</div>`;
		}

		return `
			<tr>
				<td>${this.link("Scanner", s.name, s.label)}<div class="text-muted small">${frappe.utils.escape_html(
			s.configuration || ""
		)}</div></td>
				<td>${status}${seen}</td>
				<td>${s.workplace ? this.link("Workplace", s.workplace) : `<span class="text-muted">—</span>`}</td>
				<td>${
					s.employee
						? this.link("Employee", s.employee, s.employee_name || s.employee)
						: `<span class="text-muted">—</span>`
				}</td>
				<td>${flow}</td>
				<td>${last}</td>
			</tr>`;
	}

	// ------------------------------------------------------------------ workplaces

	render_workplaces() {
		const d = this.data;
		const rows = d.workplaces.filter((w) =>
			this.match(w.name, w.barcode, w.script, ...w.printers.map((p) => p.label_printer), ...w.scanners)
		);
		if (!rows.length) return "";
		const printers = Object.fromEntries(d.printers.map((p) => [p.name, p]));
		return `
			<div class="so-table-wrap"><table class="table table-bordered so-table">
				<thead><tr>
					<th>${__("Workplace")}</th><th>${__("Barcode")}</th><th>${__("Script")}</th>
					<th>${__("Printers")}</th><th>${__("Scanners")}</th>
				</tr></thead>
				<tbody>${rows
					.map(
						(w) => `
					<tr class="${w.is_active ? "" : "so-muted"}">
						<td>${this.link("Workplace", w.name)}</td>
						<td><code>${frappe.utils.escape_html(w.barcode || "—")}</code></td>
						<td>${
							w.script
								? this.link("Workplace Script", w.script)
								: `<span class="text-muted">${__("Default")}: ${frappe.utils.escape_html(
										d.default_script || "—"
								  )}</span>`
						}</td>
						<td>${
							w.printers.length
								? w.printers
										.map((p) => {
											const pr = printers[p.label_printer] || {};
											return `<div>${this.printer_dot(pr)} ${this.link(
												"Label Printer",
												p.label_printer
											)}
												${p.purpose ? `<span class="text-muted small">(${frappe.utils.escape_html(p.purpose)})</span>` : ""}
												${p.is_default ? `<span class="text-muted small">${__("default")}</span>` : ""}
												<span class="text-muted small">${frappe.utils.escape_html(pr.ip_address || "")}</span></div>`;
										})
										.join("")
								: `<span class="text-muted">—</span>`
						}</td>
						<td>${w.scanners.map((s) => this.link("Scanner", s)).join(", ") || `<span class="text-muted">—</span>`}</td>
					</tr>`
					)
					.join("")}</tbody>
			</table></div>`;
	}

	// ------------------------------------------------------------------ scripts

	render_scripts() {
		const d = this.data;
		const by_name = Object.fromEntries(d.scripts.map((s) => [s.name, s]));
		const roots = d.scripts.filter((s) => !s.parent_script);
		const children = (name) => d.scripts.filter((s) => s.parent_script === name);
		const busy = {};
		d.scanners.forEach((s) => {
			if (!s.state) return;
			const key = s.subflow || s.script;
			(busy[key] = busy[key] || []).push(s.label);
		});

		const visible = roots.filter((r) =>
			this.match(
				r.name,
				...r.workplaces,
				...r.subflow_entries.map((e) => e.trigger_value),
				...children(r.name).map((c) => c.name)
			)
		);
		if (!visible.length) return "";

		const cards = visible
			.sort((a, b) => b.is_active - a.is_active || b.workplaces.length - a.workplaces.length)
			.map((r) => {
				const entries = r.subflow_entries;
				const linked = new Set(entries.map((e) => e.target_subflow));
				const orphans = children(r.name).filter((c) => !linked.has(c.name));
				const flow_rows = entries
					.map((e) =>
						this.flow_row(
							by_name[e.target_subflow],
							e.target_subflow,
							e.trigger_type === "Command"
								? `<code>${frappe.utils.escape_html(e.trigger_value)}</code>`
								: `${__("scan of")} <code>${frappe.utils.escape_html(
										e.trigger_value
								  )}</code>`,
							e.description,
							busy
						)
					)
					.concat(
						orphans.map((c) =>
							this.flow_row(
								c,
								c.name,
								`<span class="text-muted">${__("not linked")}</span>`,
								"",
								busy
							)
						)
					)
					.join("");

				return `
				<div class="so-card ${r.is_active ? "" : "so-muted"}">
					<div class="so-card-head so-toggle">
						<i class="fa fa-sitemap"></i>
						<b>${frappe.utils.escape_html(r.name)}</b>
						${r.is_active ? "" : this.pill(__("Inactive"), "gray")}
						${r.name === d.default_script ? this.pill(__("Default script"), "purple") : ""}
						${
							r.requires_printer
								? `<span class="text-muted small"><i class="fa fa-print"></i> ${__(
										"prints"
								  )}</span>`
								: ""
						}
						${busy[r.name] ? this.pill(__("In use: {0}", [busy[r.name].join(", ")]), "blue") : ""}
						<span class="so-card-right text-muted small">${frappe.utils.escape_html(r.default_version || "")}
							${this.link("Workplace Script", r.name, __("Go to"))}</span>
					</div>
					<div class="so-card-sub text-muted small">
						${__("Workplaces")}: ${
					r.workplaces.length
						? r.workplaces.map((w) => frappe.utils.escape_html(w)).join(", ")
						: "—"
				}
					</div>
					<div class="so-tree">
						<div class="so-node so-root-states">${__("Main flow")}: ${this.states(r)}</div>
						${flow_rows}
					</div>
					<div class="so-details">${this.script_details(r)}</div>
				</div>`;
			})
			.join("");

		return `<div class="text-muted small so-hint">${__(
			"Click a script to see its states and transitions."
		)}</div>${cards}`;
	}

	flow_row(flow, name, trigger, description, busy) {
		const inactive = flow && !flow.is_active;
		return `
			<div class="so-node ${!flow || inactive ? "so-muted" : ""}">
				<span class="so-trigger">${trigger}</span>
				<i class="fa fa-long-arrow-right text-muted"></i>
				${
					flow
						? this.link("Workplace Script", name)
						: `<span class="text-danger">${frappe.utils.escape_html(name)} (${__(
								"missing"
						  )})</span>`
				}
				${inactive ? this.pill(__("Inactive"), "gray") : ""}
				${busy[name] ? this.pill(__("In use: {0}", [busy[name].join(", ")]), "blue") : ""}
				${description ? `<span class="text-muted small">— ${frappe.utils.escape_html(description)}</span>` : ""}
				${flow ? `<div class="so-states">${this.states(flow)}</div>` : ""}
			</div>`;
	}

	states(script) {
		if (!script.states.length) return `<span class="text-muted small">${__("no states")}</span>`;
		return script.states
			.map((s) => {
				const cls = s.is_initial ? "so-state-initial" : s.is_final ? "so-state-final" : "";
				return `<span class="so-state ${cls}" title="${frappe.utils.escape_html(
					s.state
				)}">${frappe.utils.escape_html(s.label || s.state)}</span>`;
			})
			.join("");
	}

	script_details(script) {
		const transitions = script.transitions.length
			? script.transitions
					.map(
						(t) =>
							`<div><code>${frappe.utils.escape_html(
								t.from_state
							)}</code> — ${frappe.utils.escape_html(
								t.event
							)} → <code>${frappe.utils.escape_html(t.to_state)}</code></div>`
					)
					.join("")
			: `<span class="text-muted">—</span>`;
		const literals = script.barcode_literals.length
			? script.barcode_literals.map((b) => `<code>${frappe.utils.escape_html(b)}</code>`).join(" ")
			: `<span class="text-muted">—</span>`;
		return `
			<div class="so-detail-grid">
				<div><div class="so-label">${__("Transitions")}</div>${transitions}</div>
				<div><div class="so-label">${__("Barcodes used in the code")}</div>${literals}
					${
						script.requires_printer
							? `<div class="so-label">${__("Printer")}</div>${__(
									"Purpose"
							  )}: ${frappe.utils.escape_html(script.printer_purpose || __("default"))}
							${
								script.printer_label_template
									? `<br>${__("Label Template")}: ${frappe.utils.escape_html(
											script.printer_label_template
									  )}`
									: ""
							}`
							: ""
					}
				</div>
			</div>`;
	}

	// ------------------------------------------------------------------ printers

	render_printers() {
		const rows = this.data.printers.filter((p) =>
			this.match(p.name, p.ip_address, p.printer_model, p.loaded_label_size, ...p.workplaces)
		);
		if (!rows.length) return "";
		return `
			<div class="so-table-wrap"><table class="table table-bordered so-table">
				<thead><tr>
					<th>${__("Printer")}</th><th>${__("Status")}</th><th>${__("Address")}</th><th>${__("Loaded labels")}</th>
					<th>${__("Workplaces")}</th><th>${__("Print jobs in 24 h")}</th><th></th>
				</tr></thead>
				<tbody>${rows
					.map((p) => {
						const jobs = Object.entries(p.jobs_24h)
							.map(
								([st, n]) =>
									`<span class="so-job so-job-${st.toLowerCase()}">${__(st)}: ${n}</span>`
							)
							.join(" ");
						return `
					<tr class="${p.is_enabled ? "" : "so-muted"}">
						<td>${this.link("Label Printer", p.name)}<div class="text-muted small">${frappe.utils.escape_html(
							p.printer_model || ""
						)}</div></td>
						<td>${this.printer_dot(p)} ${p.is_enabled ? __(p.last_status || "Unknown") : __("Disabled")}${
							p.mock_printing ? ` ${this.pill(__("Mock printing"), "orange")}` : ""
						}
							${
								p.last_checked
									? `<div class="text-muted small">${frappe.datetime.prettyDate(
											p.last_checked
									  )}</div>`
									: ""
							}</td>
						<td><code>${frappe.utils.escape_html(p.ip_address || "")}${p.port ? ":" + p.port : ""}</code></td>
						<td>${frappe.utils.escape_html(p.loaded_label_size || "—")}${
							p.is_label_change_in_progress ? ` ${this.pill(__("Label change"), "orange")}` : ""
						}</td>
						<td>${
							p.workplaces.map((w) => this.link("Workplace", w)).join("<br>") ||
							`<span class="text-muted">—</span>`
						}</td>
						<td>${jobs || `<span class="text-muted">—</span>`}</td>
						<td><button class="btn btn-xs btn-default so-check-printer" data-printer="${frappe.utils.escape_html(
							p.name
						)}">
							<i class="fa fa-plug"></i> ${__("Check connection")}</button></td>
					</tr>`;
					})
					.join("")}</tbody>
			</table></div>`;
	}

	// ------------------------------------------------------------------ commands

	render_commands() {
		const rows = this.data.commands.filter((c) =>
			this.match(c.barcode_id, c.name, c.description, ...c.used_in.map((u) => u.script))
		);
		if (!rows.length) return "";
		const how = {
			subflow: __("opens flow"),
			code: __("handled in the script"),
			library: __("handled in the library"),
		};
		return `
			<div class="so-hint text-muted small">
				${__("Commands are separate barcodes. Print a sheet: open")}
				<a href="${this.list_url("Scanner Command")}">${__("Scanner Command")}</a>,
				${__("select commands, then Actions → Print Labels.")}
				${__("CMD-RESET works in every script.")}
			</div>
			<div class="so-table-wrap"><table class="table table-bordered so-table">
				<thead><tr><th>${__("Barcode")}</th><th>${__("Command")}</th><th>${__("Used by")}</th></tr></thead>
				<tbody>${rows
					.map(
						(c) => `
					<tr>
						<td><code>${frappe.utils.escape_html(c.barcode_id)}</code></td>
						<td>${this.link("Scanner Command", c.name)}
							${c.description ? `<div class="text-muted small">${frappe.utils.escape_html(c.description)}</div>` : ""}</td>
						<td>${
							c.used_in.length
								? c.used_in
										.map(
											(u) =>
												`<div>${frappe.utils.escape_html(
													u.script
												)} <span class="text-muted small">— ${how[u.how]}${
													u.target ? ` ${frappe.utils.escape_html(u.target)}` : ""
												}</span></div>`
										)
										.join("")
								: c.barcode_id === "CMD-RESET"
								? `<span class="text-muted">${__("Built in: resets any script")}</span>`
								: `<span class="text-muted">—</span>`
						}</td>
					</tr>`
					)
					.join("")}</tbody>
			</table></div>`;
	}

	// ------------------------------------------------------------------ helpers

	link(doctype, name, label) {
		if (!name) return "";
		return frappe.utils.get_form_link(doctype, name, true, frappe.utils.escape_html(label || name));
	}

	list_url(doctype) {
		return frappe.utils.get_form_link(doctype, "").replace(/\/$/, "");
	}

	pill(text, color) {
		return `<span class="indicator-pill ${color} so-pill">${frappe.utils.escape_html(text)}</span>`;
	}

	printer_dot(p) {
		let color = "gray";
		if (p.is_enabled && p.last_status === "Ready") color = "green";
		else if (p.is_enabled && ["Offline", "Connection Error"].includes(p.last_status)) color = "red";
		else if (p.is_enabled && p.last_status) color = "orange";
		return `<span class="so-dot so-dot-${color}"></span>`;
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
