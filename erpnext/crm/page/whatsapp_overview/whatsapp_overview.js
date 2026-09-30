frappe.pages["whatsapp-overview"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("WhatsApp Overview"),
		single_column: true,
	});
	wrapper.whatsapp_overview = new WhatsAppOverview(page);
};

frappe.pages["whatsapp-overview"].on_page_show = function (wrapper) {
	wrapper.whatsapp_overview?.start_timer();
};

frappe.pages["whatsapp-overview"].on_page_hide = function (wrapper) {
	wrapper.whatsapp_overview?.stop_timer();
};

const WAO_REFRESH_SECONDS = 60;
const WAO_TABS = [
	["summary", "fa fa-th-large", "Summary"],
	["numbers", "fa fa-phone", "Numbers"],
	["managers", "fa fa-users", "Managers"],
	["pending", "fa fa-hourglass-half", "Pending replies"],
	["settings", "fa fa-cog", "Settings"],
];
const WAO_PERIODS = [
	["today", "Today"],
	["7", "Last 7 days"],
	["30", "Last 30 days"],
	["90", "Last 90 days"],
];

// Working-hours duration: "45 min", "3 h 20 min", "2 d 1 h" (a day = 24 working hours).
function wao_duration(seconds) {
	if (seconds === null || seconds === undefined) return "—";
	const mins = Math.round(seconds / 60);
	if (mins < 1) return __("< 1 min");
	if (mins < 60) return __("{0} min", [mins]);
	const hours = Math.floor(mins / 60);
	if (hours < 24) return __("{0} h {1} min", [hours, mins % 60]);
	return __("{0} d {1} h", [Math.floor(hours / 24), hours % 24]);
}

class WhatsAppOverview {
	constructor(page) {
		this.page = page;
		this.data = null;
		this.tab = "summary";
		this.filter = "";
		this.period = "7";
		this.auto = true;
		this.make();
		this.refresh();
	}

	make() {
		this.page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.page.add_inner_button(__("Auto-refresh"), () => this.toggle_auto());
		this.page.add_inner_button(__("Chats"), () => frappe.set_route("whatsapp-chat-center"));
		this.page.add_inner_button(__("Number Access"), () => frappe.set_route("whatsapp-access"));
		this.period_field = this.page.add_field({
			fieldname: "period",
			fieldtype: "Select",
			label: __("Period"),
			options: WAO_PERIODS.map(([value, label]) => ({ value, label: __(label) })),
			default: this.period,
			change: () => {
				this.period = this.period_field.get_value() || "7";
				this.refresh();
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
			<div class="whatsapp-overview">
				<div class="wao-tabs"></div>
				<div class="wao-meta text-muted"></div>
				<div class="wao-body"></div>
			</div>
		`);
		this.$tabs = this.page.main.find(".wao-tabs");
		this.$meta = this.page.main.find(".wao-meta");
		this.$body = this.page.main.find(".wao-body");
		this.$tabs.on("click", ".wao-tab", (e) => {
			this.tab = $(e.currentTarget).data("tab");
			this.render();
		});
		this.$body.on("click", ".wao-goto", (e) => {
			e.preventDefault();
			this.tab = $(e.currentTarget).data("tab");
			this.render();
		});
		this.$body.on("click", ".wao-open-chat", (e) => {
			e.preventDefault();
			const chat = $(e.currentTarget).data("chat");
			if (chat) frappe.set_route("whatsapp-chat-center", { chat });
		});
	}

	start_timer() {
		this.stop_timer();
		if (!this.auto) return;
		this.timer = setInterval(() => this.refresh(true), WAO_REFRESH_SECONDS * 1000);
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
				method: "erpnext.crm.page.whatsapp_overview.whatsapp_overview.get_overview",
				args: { period: this.period },
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

	render() {
		if (!this.data) return;
		if (!this.data.installed) {
			this.$body.html(
				`<div class="text-muted wao-empty">${__(
					"The WhatsApp app is not installed on this site."
				)}</div>`
			);
			return;
		}
		this.render_tabs();
		this.render_meta();
		this.render_tab();
	}

	render_tabs() {
		const d = this.data;
		const counts = {
			summary: "",
			numbers: d.accounts.length,
			managers: d.managers.length,
			pending: d.pending.length,
			settings: "",
		};
		this.$tabs.html(
			WAO_TABS.map(
				([key, icon, label]) => `
				<button class="btn btn-sm wao-tab ${this.tab === key ? "btn-primary" : "btn-default"}" data-tab="${key}">
					<i class="${icon}"></i> ${__(label)}
					${counts[key] !== "" ? `<span class="wao-count">${counts[key]}</span>` : ""}
				</button>`
			).join("")
		);
	}

	render_meta() {
		if (!this.data || !this.data.generated_at) return;
		this.$meta.html(
			`${__("Updated")}: ${frappe.datetime.str_to_user(this.data.generated_at)} · ${__(
				"times are counted in working hours"
			)} · ${
				this.auto ? __("auto-refresh every {0} s", [WAO_REFRESH_SECONDS]) : __("auto-refresh off")
			}`
		);
	}

	render_tab() {
		if (!this.data || !this.data.installed) return;
		const html = this[`render_${this.tab}`](this.data);
		this.$body.html(html || `<div class="text-muted wao-empty">${__("Nothing found")}</div>`);
	}

	match(...values) {
		if (!this.filter) return true;
		return values.some((v) => v && String(v).toLowerCase().includes(this.filter));
	}

	esc(v) {
		return frappe.utils.escape_html(v === null || v === undefined ? "" : String(v));
	}

	people(list) {
		return (
			(list || []).map((p) => this.esc(p.full_name || p.user)).join(", ") ||
			`<span class="text-muted">—</span>`
		);
	}

	status_pill(acc) {
		const active = acc.status === "Active";
		return `<span class="indicator-pill ${active ? "green" : "gray"} wao-pill">${this.esc(
			__(acc.status || "Inactive")
		)}</span>`;
	}

	// ------------------------------------------------------------------ summary

	render_summary(d) {
		const replies = d.accounts.reduce((n, a) => n + a.replies, 0);
		const all_times = d.managers.filter((m) => m.avg_reply !== null);
		const avg =
			replies > 0
				? Math.round(d.accounts.reduce((n, a) => n + (a.avg_reply || 0) * a.replies, 0) / replies)
				: null;
		const oldest = d.pending.length ? d.pending[0].waiting : null;

		const tile = (tab, icon, value, label, sub) => `
			<a class="wao-tile wao-goto" data-tab="${tab}" href="#">
				<div class="wao-tile-icon"><i class="${icon}"></i></div>
				<div class="wao-tile-value">${value}</div>
				<div class="wao-tile-label">${label}</div>
				<div class="wao-tile-sub text-muted">${sub}</div>
			</a>`;

		const cards = d.accounts
			.filter((a) => this.match(a.label, a.account_name, a.verified_name))
			.map((a) => this.number_card(a))
			.join("");

		return `
			<div class="wao-tiles">
				${tile(
					"numbers",
					"fa fa-phone",
					d.accounts.filter((a) => a.status === "Active").length + " / " + d.accounts.length,
					__("Active numbers"),
					__("{0} chats in total", [d.accounts.reduce((n, a) => n + a.chats_total, 0)])
				)}
				${tile(
					"pending",
					"fa fa-hourglass-half",
					d.pending.length,
					__("Waiting for a reply"),
					oldest !== null ? __("oldest waits {0}", [wao_duration(oldest)]) : __("nobody is waiting")
				)}
				${tile(
					"managers",
					"fa fa-clock-o",
					wao_duration(avg),
					__("Average reply time"),
					__("{0} replies, {1} managers answered", [replies, all_times.length])
				)}
				${tile(
					"numbers",
					"fa fa-exchange",
					d.accounts.reduce((n, a) => n + a.messages_in, 0) +
						" / " +
						d.accounts.reduce((n, a) => n + a.messages_out, 0),
					__("Messages in / out"),
					__("{0} new chats", [d.accounts.reduce((n, a) => n + a.chats_new, 0)])
				)}
			</div>
			<h5 class="wao-h">${__("Business numbers")}</h5>
			<div class="wao-cards">${cards || `<div class="text-muted">${__("No WhatsApp numbers yet")}</div>`}</div>
		`;
	}

	number_card(a) {
		return `
			<div class="wao-card">
				<div class="wao-card-head">
					<i class="fa fa-whatsapp wao-wa"></i>
					<div class="wao-card-title">
						<div class="wao-number">${this.esc(a.label)}</div>
						<div class="text-muted wao-card-sub">${this.esc(a.verified_name || a.account_name)}</div>
					</div>
					${this.status_pill(a)}
				</div>
				<div class="wao-kpis">
					<div><span class="wao-kpi">${a.pending}</span><span class="text-muted">${__("waiting")}</span></div>
					<div><span class="wao-kpi">${wao_duration(a.avg_reply)}</span><span class="text-muted">${__(
			"avg reply"
		)}</span></div>
					<div><span class="wao-kpi">${
						a.reply_rate === null ? "—" : a.reply_rate + "%"
					}</span><span class="text-muted">${__("answered")}</span></div>
					<div><span class="wao-kpi">${a.chats_active}</span><span class="text-muted">${__("active chats")}</span></div>
				</div>
				<div class="wao-card-people">
					<div><span class="wao-label">${__("Responsible")}</span> ${this.people(a.responsible)}</div>
					<div><span class="wao-label">${__("Spectators")}</span> ${this.people(a.spectators)}</div>
				</div>
				${
					a.oldest_pending !== null
						? `<div class="wao-warn"><i class="fa fa-hourglass-half"></i> ${__(
								"Oldest unanswered chat waits {0}",
								[wao_duration(a.oldest_pending)]
						  )}</div>`
						: ""
				}
			</div>`;
	}

	// ------------------------------------------------------------------ numbers

	render_numbers(d) {
		const rows = d.accounts
			.filter((a) => this.match(a.label, a.account_name, a.verified_name, a.phone_id))
			.map(
				(a) => `
				<tr>
					<td>
						<div class="wao-number">${this.esc(a.label)}</div>
						<div class="text-muted wao-small">${frappe.utils.get_form_link(
							"WhatsApp Account",
							a.name,
							true,
							this.esc(a.account_name || a.name)
						)}${a.verified_name ? " · " + this.esc(a.verified_name) : ""}</div>
						<div class="text-muted wao-small">${__("Phone ID")}: ${this.esc(a.phone_id)}</div>
					</td>
					<td>${this.status_pill(a)}${
					a.is_default_outgoing
						? `<div class="text-muted wao-small">${__("Default outgoing")}</div>`
						: ""
				}${
					a.is_default_incoming
						? `<div class="text-muted wao-small">${__("Default incoming")}</div>`
						: ""
				}</td>
					<td>${this.people(a.responsible)}</td>
					<td>${this.people(a.spectators)}</td>
					<td class="wao-num">${a.chats_total}<div class="text-muted wao-small">${__("{0} active, {1} new", [
					a.chats_active,
					a.chats_new,
				])}</div></td>
					<td class="wao-num">${a.messages_in} / ${a.messages_out}</td>
					<td class="wao-num">${a.pending}<div class="text-muted wao-small">${wao_duration(a.oldest_pending)}</div></td>
					<td class="wao-num">${wao_duration(a.avg_reply)}<div class="text-muted wao-small">${__("median {0}", [
					wao_duration(a.median_reply),
				])}</div></td>
					<td class="wao-num">${a.reply_rate === null ? "—" : a.reply_rate + "%"}<div class="text-muted wao-small">${__(
					"{0} replies",
					[a.replies]
				)}</div></td>
				</tr>`
			)
			.join("");
		if (!rows) return "";
		return `
			<div class="wao-table-wrap"><table class="table table-bordered wao-table">
				<thead><tr>
					<th>${__("Number")}</th>
					<th>${__("Status")}</th>
					<th>${__("Responsible")}</th>
					<th>${__("Spectators")}</th>
					<th>${__("Chats")}</th>
					<th>${__("Messages in / out")}</th>
					<th>${__("Waiting")}</th>
					<th>${__("Average reply")}</th>
					<th>${__("Answered")}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table></div>`;
	}

	// ------------------------------------------------------------------ managers

	render_managers(d) {
		const rows = d.managers
			.filter((m) => this.match(m.full_name, m.user, ...m.numbers.map((n) => n.label)))
			.map((m) => {
				const numbers =
					m.numbers
						.map(
							(n) =>
								`<div>${this.esc(n.label)} <span class="indicator-pill ${
									n.access === "Responsible" ? "blue" : "gray"
								} wao-pill">${this.esc(__(n.access))}</span></div>`
						)
						.join("") || `<span class="text-muted">${__("No number assigned")}</span>`;
				return `
				<tr>
					<td><div class="wao-number">${this.esc(m.full_name)}</div><div class="text-muted wao-small">${this.esc(
					m.user
				)}</div></td>
					<td>${numbers}</td>
					<td class="wao-num">${m.replies}</td>
					<td class="wao-num">${wao_duration(m.avg_reply)}<div class="text-muted wao-small">${__("median {0}", [
					wao_duration(m.median_reply),
				])}</div></td>
					<td class="wao-num">${m.messages_sent}</td>
					<td class="wao-num">${m.pending}</td>
					<td>${m.last_activity ? frappe.datetime.comment_when(m.last_activity) : "—"}</td>
				</tr>`;
			})
			.join("");
		if (!rows) return "";
		return `
			<div class="wao-table-wrap"><table class="table table-bordered wao-table">
				<thead><tr>
					<th>${__("Manager")}</th>
					<th>${__("Numbers")}</th>
					<th>${__("Replies")}</th>
					<th>${__("Average reply")}</th>
					<th>${__("Messages sent")}</th>
					<th>${__("Waiting on their numbers")}</th>
					<th>${__("Last reply")}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table></div>
			<div class="text-muted wao-small">${__(
				"A reply is the first message sent after the customer wrote; it is credited to whoever sent it."
			)}</div>`;
	}

	// ------------------------------------------------------------------ pending

	render_pending(d) {
		const rows = d.pending
			.filter((p) => this.match(p.title, p.phone, p.number_label, p.preview))
			.map(
				(p) => `
				<tr>
					<td>${
						p.chat
							? `<a href="#" class="wao-open-chat" data-chat="${this.esc(p.chat)}">${this.esc(
									p.title
							  )}</a>`
							: this.esc(p.title)
					}<div class="text-muted wao-small">+${this.esc(p.phone)}</div></td>
					<td>${this.esc(p.number_label)}</td>
					<td class="wao-preview">${this.esc(p.preview)}</td>
					<td class="wao-num">${p.count}</td>
					<td>${frappe.datetime.str_to_user(p.since)}</td>
					<td class="wao-num wao-wait">${wao_duration(p.waiting)}<div class="text-muted wao-small">${__(
					"{0} in total",
					[wao_duration(p.waiting_total)]
				)}</div></td>
				</tr>`
			)
			.join("");
		if (!rows) {
			return `<div class="wao-ok"><i class="fa fa-check-circle"></i> ${__(
				"Every customer got a reply"
			)}</div>`;
		}
		return `
			<div class="wao-table-wrap"><table class="table table-bordered wao-table">
				<thead><tr>
					<th>${__("Chat")}</th>
					<th>${__("Number")}</th>
					<th>${__("Last message")}</th>
					<th>${__("Unanswered")}</th>
					<th>${__("Waiting since")}</th>
					<th>${__("Waiting (working hours)")}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table></div>`;
	}

	// ------------------------------------------------------------------ settings

	render_settings(d) {
		const hours =
			(d.schedule.hours || [])
				.map((h) => `<div>${this.esc(__(h.weekday))}: ${this.esc(h.start)}–${this.esc(h.end)}</div>`)
				.join("") || `<div class="text-muted">—</div>`;
		const link = (route, icon, title, sub) => `
			<a class="wao-tile" href="/app/${route}">
				<div class="wao-tile-icon"><i class="${icon}"></i></div>
				<div class="wao-tile-label">${title}</div>
				<div class="wao-tile-sub text-muted">${sub}</div>
			</a>`;
		return `
			<div class="wao-tiles">
				${link(
					"whatsapp-access",
					"fa fa-user-plus",
					__("Number Access"),
					__("Who answers and who watches each number")
				)}
				${link(
					"whatsapp-chat-settings",
					"fa fa-clock-o",
					__("Working Hours"),
					__("Hours and holidays counted in reply times")
				)}
				${link("whatsapp-account", "fa fa-phone", __("WhatsApp Accounts"), __("Business numbers and API keys"))}
			</div>
			<h5 class="wao-h">${__("Working hours")}</h5>
			<div class="wao-hours">${hours}</div>
			<div class="text-muted wao-small">${__("Holiday list")}: ${this.esc(d.schedule.holiday_list || "—")}</div>
		`;
	}
}
