frappe.pages["sensitive-data-monitor"].on_page_load = (wrapper) => {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Sensitive Data Monitor"),
		single_column: true,
	});
	wrapper.monitor = new SensitiveDataMonitor(page);
};

frappe.pages["sensitive-data-monitor"].on_page_show = (wrapper) => wrapper.monitor?.load();

const MONITOR_METHOD = "erpnext.access_control.sensitive_monitor";
class SensitiveDataMonitor {
	constructor(page) {
		this.page = page;
		this.data = null;
		this.event = page.add_field({
			fieldtype: "Select",
			fieldname: "event",
			label: __("Event"),
			options: [
				{ value: "", label: __("All events") },
				...erpnext.sensitive_log.EVENTS.map((value) => ({ value, label: __(value) })),
			],
			change: () => this.render(),
		});
		this.user = page.add_field({
			fieldtype: "Link",
			fieldname: "user",
			options: "User",
			label: __("User"),
			change: () => this.render(),
		});
		page.set_primary_action(
			__("Settings"),
			() => frappe.set_route("Form", "Sensitive Data Settings"),
			"settings"
		);
		page.set_secondary_action(__("Refresh"), () => this.load(), "refresh");
		page.add_inner_button(__("Access Management"), () => frappe.set_route("access-console"));
		this.$body = $('<div class="sdm"></div>').appendTo(page.main);
		this.add_style();
		this.bind();
	}

	load() {
		return frappe.xcall(`${MONITOR_METHOD}.get_overview`).then((data) => {
			this.data = data;
			this.render();
		});
	}

	person(user, sub) {
		if (!user) return `<span class="text-muted">—</span>`;
		const info = this.data.people[user] || {};
		return erpnext.entity.user(
			{ user, full_name: info.full_name, user_image: info.user_image },
			{ size: 24, sub }
		);
	}

	when(value) {
		return value ? frappe.datetime.str_to_user(value) : "—";
	}

	clock(epoch) {
		return moment(epoch * 1000).format("DD.MM.YYYY HH:mm");
	}

	matches(row, fields) {
		const event = this.event.get_value();
		const user = this.user.get_value();
		return (!event || row.event === event) && (!user || fields.some((field) => row[field] === user));
	}

	table(title, icon, headers, rows, empty) {
		const esc = frappe.utils.escape_html;
		return `<div class="sdm-section">
			<div class="sdm-title"><i class="fa ${icon}"></i> ${esc(title)}
				<span class="text-muted">${rows.length}</span></div>
			${
				rows.length
					? `<div class="sdm-scroll"><table class="table table-sm sdm-table"><thead><tr>${headers
							.map((header) => `<th>${esc(header)}</th>`)
							.join("")}</tr></thead><tbody>${rows
							.map((cells) => `<tr>${cells.map((cell) => `<td>${cell}</td>`).join("")}</tr>`)
							.join("")}</tbody></table></div>`
					: `<div class="text-muted sdm-empty">${esc(empty)}</div>`
			}
		</div>`;
	}

	stat(label, value, color) {
		return `<div class="sdm-stat"><div class="sdm-stat-value ${color || ""}">${value}</div>
			<div class="sdm-stat-label">${frappe.utils.escape_html(label)}</div></div>`;
	}

	summary_html() {
		const data = this.data;
		const day_ago = frappe.datetime.add_days(frappe.datetime.now_datetime(), -1);
		const wrong = data.events.filter((row) => row.event === "Wrong PIN" && row.creation > day_ago).length;
		const blocked = data.pins.filter((row) => row.locked).length;
		const protected_count =
			data.protected.doctypes.length + data.protected.reports.length + data.protected.pages.length;
		const fields = Object.values(data.fields).reduce((total, list) => total + list.length, 0);
		return `<div class="sdm-stats">
			${this.stat(__("Protection"), data.enabled ? __("On") : __("Off"), data.enabled ? "green" : "red")}
			${this.stat(__("Protected objects"), protected_count)}
			${this.stat(__("Protected fields"), fields)}
			${this.stat(__("Open now"), data.active.length, data.active.length ? "orange" : "")}
			${this.stat(__("Wrong PINs in 24 h"), wrong, wrong ? "orange" : "")}
			${this.stat(__("Blocked PINs"), blocked, blocked ? "red" : "")}
		</div>
		${
			data.enabled
				? ""
				: `<div class="alert alert-warning">${__(
						"Protection is off: nothing asks for the PIN. Turn it on in the settings."
				  )}</div>`
		}
		<div class="text-muted small sdm-note">${__(
			"Unlock lasts {0} min, locks after {1} min without activity, {2} wrong attempts block the PIN.",
			[data.settings.unlock_minutes, data.settings.idle_minutes || "—", data.settings.max_attempts]
		)}</div>`;
	}

	active_html() {
		const rows = this.data.active
			.filter((row) => this.matches(row, ["user", "actor"]))
			.map((row) => [
				this.person(row.user),
				row.actor ? this.person(row.actor, __("viewing as the user")) : "—",
				this.clock(row.since),
				this.clock(row.until),
				`<button class="btn btn-xs btn-default sdm-lock" data-session="${row.id}">
					<i class="fa fa-lock"></i> ${__("Lock")}</button>`,
			]);
		return this.table(
			__("Open now"),
			"fa-unlock-alt",
			[__("User"), __("Acted By"), __("Since"), __("Until"), ""],
			rows,
			__("Nobody has protected data open")
		);
	}

	pins_html() {
		const rows = this.data.pins
			.filter((row) => this.matches(row, ["user"]))
			.map((row) => [
				this.person(row.user),
				row.locked
					? `<span class="indicator-pill red">${__("Blocked")}</span>`
					: row.is_set
					? `<span class="indicator-pill green">${__("Active")}</span>`
					: `<span class="indicator-pill gray">${__("Not set")}</span>`,
				row.failed_attempts || 0,
				this.when(row.pin_set_on),
				this.when(row.last_unlock),
				row.is_set || row.locked
					? `<button class="btn btn-xs btn-default sdm-reset" data-user="${frappe.utils.escape_html(
							row.user
					  )}"><i class="fa fa-key"></i> ${__("Reset PIN")}</button>`
					: "",
			]);
		return this.table(
			__("PIN States"),
			"fa-key",
			[
				__("User"),
				__("Status"),
				__("Wrong Attempts In A Row"),
				__("PIN Set On"),
				__("Last Unlock"),
				"",
			],
			rows,
			__("Nobody has created a PIN yet")
		);
	}

	events_html() {
		const esc = frappe.utils.escape_html;
		const log = erpnext.sensitive_log;
		const rows = this.data.events
			.filter((row) => this.matches(row, ["user", "actor"]))
			.map((row) => {
				const text = log.describe(row);
				return [
					this.when(row.creation),
					`<span class="indicator-pill ${log.color(row.event)}">${esc(
						log.label(row.event)
					)}</span>`,
					`<span class="sdm-what" title="${esc(text.full)}">${esc(text.short)}</span>`,
					this.person(row.user),
					row.actor ? this.person(row.actor) : "—",
					row.ip_address
						? `<span title="${esc(log.client_text(row.user_agent))}">${esc(
								row.ip_address
						  )}</span>`
						: "—",
				];
			});
		return this.table(
			__("Sensitive Access Log"),
			"fa-history",
			[__("When"), __("Event"), __("What happened"), __("User"), __("Acted By"), __("IP Address")],
			rows,
			__("No events yet")
		);
	}

	views_html() {
		const esc = frappe.utils.escape_html;
		const rows = this.data.views
			.filter((row) => !this.user.get_value() || row.viewed_by === this.user.get_value())
			.map((row) => [
				this.when(row.creation),
				this.person(row.viewed_by),
				esc(__(row.reference_doctype)),
				`<a href="/desk/${frappe.router.slug(row.reference_doctype)}/${encodeURIComponent(
					row.reference_name
				)}">${esc(row.reference_name)}</a>`,
			]);
		return this.table(
			__("Opened protected documents"),
			"fa-eye",
			[__("When"), __("User"), __("Document Type"), __("Document")],
			rows,
			__("No protected document was opened yet")
		);
	}

	exports_html() {
		const esc = frappe.utils.escape_html;
		const rows = this.data.exports
			.filter((row) => !this.user.get_value() || row.user === this.user.get_value())
			.map((row) => [
				this.when(row.creation),
				this.person(row.user),
				esc(__(row.export_from || row.report_name || "")),
				esc(row.reference_document || ""),
				esc(row.file_type || row.method || ""),
			]);
		return this.table(
			__("Exports and prints"),
			"fa-download",
			[__("When"), __("User"), __("Source"), __("Document"), __("Format")],
			rows,
			__("Nothing protected was exported or printed")
		);
	}

	render() {
		if (!this.data) return;
		this.$body.html(
			this.summary_html() +
				this.active_html() +
				this.pins_html() +
				this.events_html() +
				this.views_html() +
				this.exports_html()
		);
	}

	bind() {
		this.$body.on("click", ".sdm-lock", (event) => {
			const session = $(event.currentTarget).data("session");
			frappe.confirm(__("Lock protected data for this user now?"), () =>
				frappe.xcall(`${MONITOR_METHOD}.force_lock`, { session }).then(() => this.load())
			);
		});
		this.$body.on("click", ".sdm-reset", (event) => {
			const user = $(event.currentTarget).data("user");
			frappe.confirm(
				__(
					"Reset the PIN of {0}? They will create a new one with their login password the next time they open protected data.",
					[frappe.utils.escape_html(frappe.user_info(user).fullname || user)]
				),
				() =>
					frappe.xcall(`${MONITOR_METHOD}.reset_pin`, { user }).then(() => {
						frappe.show_alert({ message: __("PIN reset"), indicator: "green" });
						this.load();
					})
			);
		});
	}

	add_style() {
		$("<style>")
			.text(
				`.sdm { padding: var(--padding-sm) var(--padding-md); }
				.sdm-stats { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 12px; }
				.sdm-stat { flex: 1 1 140px; padding: 12px; border: 1px solid var(--border-color);
					border-radius: var(--border-radius-md); background: var(--card-bg); }
				.sdm-stat-value { font-size: var(--text-2xl); font-weight: 600; }
				.sdm-stat-value.green { color: var(--green-600); }
				.sdm-stat-value.orange { color: var(--orange-600); }
				.sdm-stat-value.red { color: var(--red-600); }
				.sdm-stat-label { color: var(--text-muted); font-size: var(--text-sm); }
				.sdm-note { margin-bottom: var(--margin-md); }
				.sdm-section { margin-bottom: var(--margin-lg); padding: var(--padding-sm);
					border: 1px solid var(--border-color); border-radius: var(--border-radius-md);
					background: var(--card-bg); overflow-x: auto; }
				.sdm-section .sdm-table { margin-bottom: 0; }
				.sdm-scroll { max-height: 420px; overflow-y: auto; }
				.sdm-scroll thead th { position: sticky; top: 0; z-index: 1; background: var(--card-bg); }
				.sdm-table td, .sdm-table th { white-space: nowrap; }
				.sdm-table .sdm-what { display: inline-block; max-width: 420px; white-space: normal; }
				.sdm-title { font-weight: 600; margin-bottom: var(--margin-sm); }
				.sdm-table td { vertical-align: middle; }
				.sdm-empty { padding: 8px 0; }`
			)
			.appendTo("head");
	}
}
