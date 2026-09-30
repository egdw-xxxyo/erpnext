// Огляд WhatsApp: business numbers, the people who work with them and how fast customers
// get answers. Managers also configure WhatsApp here: a number opens its card
// (/app/whatsapp-overview/number/<account>) with the Meta profile, notes and who answers
// or watches it; the Employees tab decides who works with WhatsApp at all.

frappe.pages["whatsapp-overview"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("WhatsApp Overview"),
		single_column: true,
	});
	wrapper.whatsapp_overview = new WhatsAppOverview(page);
};

frappe.pages["whatsapp-overview"].on_page_show = function (wrapper) {
	const view = wrapper.whatsapp_overview;
	if (!view) return;
	view.follow_route();
	view.start_timer();
};

frappe.pages["whatsapp-overview"].on_page_hide = function (wrapper) {
	wrapper.whatsapp_overview?.stop_timer();
};

const WAO_API = "erpnext.crm.page.whatsapp_overview.whatsapp_overview";
const WAO_REFRESH_SECONDS = 60;
const WAO_TABS = [
	["summary", "fa fa-th-large", "Summary"],
	["numbers", "fa fa-phone", "Numbers"],
	["employees", "fa fa-users", "Employees"],
	["pending", "fa fa-hourglass-half", "Pending replies"],
	["settings", "fa fa-cog", "Settings"],
];
const WAO_PERIODS = [
	["today", "Today"],
	["7", "Last 7 days"],
	["30", "Last 30 days"],
	["90", "Last 90 days"],
];
const WAO_LEVELS = {
	Admin: ["purple", "System Manager"],
	Manager: ["blue", "Manager"],
	Employee: ["green", "Employee"],
	"": ["gray", "No access"],
};
const WAO_QUALITY = { GREEN: ["green", "High"], YELLOW: ["orange", "Medium"], RED: ["red", "Low"] };

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
		this.card = null;
		this.number = null;
		this.tab = "summary";
		this.filter = "";
		this.period = "7";
		this.auto = true;
		erpnext.chat_render.inject_styles();
		this.make();
		this.follow_route();
		// Moving between the list and a number card stays on this page, so no page show.
		frappe.router.on("change", () => {
			if (frappe.get_route()[0] === "whatsapp-overview") this.follow_route();
		});
	}

	make() {
		this.page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.page.add_inner_button(__("Auto-refresh"), () => this.toggle_auto());
		this.page.add_inner_button(__("Chats"), () => frappe.set_route("whatsapp-chat-center"));
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
				if (!this.number) this.render_tab();
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
		this.$body.on("click", "[data-number]", (e) => {
			const $inner = $(e.target).closest("a[href], button, select, .wao-open-chat");
			if ($inner.length && $inner[0] !== e.currentTarget) return;
			e.preventDefault();
			frappe.set_route("whatsapp-overview", "number", $(e.currentTarget).attr("data-number"));
		});
		this.bind_number_actions();
		this.bind_employee_actions();
	}

	// /app/whatsapp-overview → tabs; /app/whatsapp-overview/number/<account> → number card.
	follow_route() {
		const route = frappe.get_route();
		const number = route[1] === "number" && route[2] ? route[2] : null;
		const changed = number !== this.number;
		this.number = number;
		if (changed) {
			this.card = null;
			this.$body.empty();
			if (!number) this.render();
		}
		this.refresh(!changed);
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
		// Background refresh must not throw away notes being typed.
		if (silent && this.number && this.notes_dirty) return;
		this.loading = true;
		const number = this.number;
		const call = number
			? frappe.call({
					method: `${WAO_API}.get_number`,
					args: { account: number, period: this.period },
					freeze: !silent && !this.card,
			  })
			: frappe.call({
					method: `${WAO_API}.get_overview`,
					args: { period: this.period },
					freeze: !silent && !this.data,
			  });
		call.then((r) => {
			if (number !== this.number) return;
			if (number) this.card = r.message;
			else this.data = r.message;
			this.render();
		}).always(() => {
			this.loading = false;
		});
		if (!this.timer && this.auto) this.start_timer();
	}

	render() {
		if (this.number) {
			this.$tabs.hide();
			if (this.card) this.render_number(this.card);
			this.render_meta();
			return;
		}
		if (!this.data) return;
		if (!this.data.installed) {
			this.$body.html(
				`<div class="text-muted wao-empty">${__(
					"The WhatsApp app is not installed on this site."
				)}</div>`
			);
			return;
		}
		this.$tabs.show();
		this.render_tabs();
		this.render_meta();
		this.render_tab();
	}

	render_tabs() {
		const d = this.data;
		const counts = {
			summary: "",
			numbers: d.accounts.length,
			employees: d.employees.filter((e) => e.level).length,
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
		const src = this.number ? this.card : this.data;
		if (!src || !src.generated_at) return;
		this.$meta.html(
			`${__("Updated")}: ${frappe.datetime.str_to_user(src.generated_at)} · ${__(
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

	// ------------------------------------------------------------------ pieces

	number_title(a) {
		return a.verified_name || a.account_name || a.name;
	}

	number_line(a) {
		return a.display_phone_number || `${__("Phone ID")}: ${a.phone_id || "—"}`;
	}

	number_avatar(a, size) {
		return erpnext.chat_render.avatar_html(
			a.profile_image
				? { image: a.profile_image }
				: { name: this.number_title(a), key: a.name, icon: "fa fa-whatsapp" },
			size
		);
	}

	person_avatar(p, size) {
		return erpnext.chat_render.avatar_html(
			{ name: p.full_name || p.user, key: p.user, image: p.user_image },
			size
		);
	}

	people(list) {
		if (!list || !list.length) return `<span class="text-muted">—</span>`;
		return `<span class="wao-people">${list
			.map(
				(p) =>
					`<span class="wao-person" title="${this.esc(p.full_name || p.user)}">${this.person_avatar(
						p,
						22
					)}<span>${this.esc(p.full_name || p.user)}</span></span>`
			)
			.join("")}</span>`;
	}

	status_pill(acc) {
		const active = acc.status === "Active";
		return `<span class="indicator-pill ${active ? "green" : "gray"} wao-pill">${this.esc(
			__(acc.status || "Inactive")
		)}</span>`;
	}

	level_pill(level) {
		const [color, label] = WAO_LEVELS[level || ""];
		return `<span class="indicator-pill ${color} wao-pill">${__(label)}</span>`;
	}

	access_pill(access) {
		return `<span class="indicator-pill ${
			access === "Responsible" ? "blue" : "gray"
		} wao-pill">${this.esc(__(access))}</span>`;
	}

	// ------------------------------------------------------------------ summary

	render_summary(d) {
		const replies = d.accounts.reduce((n, a) => n + a.replies, 0);
		const answering = d.employees.filter((m) => m.avg_reply !== null);
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
					"employees",
					"fa fa-clock-o",
					wao_duration(avg),
					__("Average reply time"),
					__("{0} replies, {1} people answered", [replies, answering.length])
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
			${this.number_cards(d)}
		`;
	}

	number_cards(d) {
		const cards = d.accounts
			.filter((a) =>
				this.match(a.label, a.account_name, a.verified_name, a.display_phone_number, a.phone_id)
			)
			.map((a) => this.number_card(a))
			.join("");
		return `<div class="wao-cards">${
			cards || `<div class="text-muted">${__("No WhatsApp numbers yet")}</div>`
		}</div>`;
	}

	number_card(a) {
		return `
			<div class="wao-card wao-card-link" data-number="${this.esc(a.name)}" title="${__("Open number card")}">
				<div class="wao-card-head">
					${this.number_avatar(a, 48)}
					<div class="wao-card-title">
						<div class="wao-number">${this.esc(this.number_title(a))}</div>
						<div class="wao-card-phone">${this.esc(this.number_line(a))}</div>
						${a.about ? `<div class="text-muted wao-card-sub">${this.esc(a.about)}</div>` : ""}
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
			.filter((a) =>
				this.match(a.label, a.account_name, a.verified_name, a.display_phone_number, a.phone_id)
			)
			.map(
				(a) => `
				<tr class="wao-row-link" data-number="${this.esc(a.name)}">
					<td>
						<div class="wao-who">${this.number_avatar(a, 32)}<div>
							<div class="wao-number">${this.esc(this.number_title(a))}</div>
							<div class="text-muted wao-small">${this.esc(this.number_line(a))}</div>
						</div></div>
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
			${this.number_cards(d)}
			<h5 class="wao-h">${__("Figures for the period")}</h5>
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

	// ------------------------------------------------------------------ number card

	render_number(c) {
		const a = c.number;
		const esc = (v) => this.esc(v);
		const quality = WAO_QUALITY[a.quality_rating];
		const pills = [
			this.status_pill(a),
			quality
				? `<span class="indicator-pill ${quality[0]} wao-pill">${__("Quality")}: ${__(
						quality[1]
				  )}</span>`
				: "",
			a.messaging_limit
				? `<span class="indicator-pill gray wao-pill">${__("Limit")}: ${esc(
						a.messaging_limit.replace("TIER_", "")
				  )}</span>`
				: "",
			a.vertical ? `<span class="indicator-pill gray wao-pill">${esc(a.vertical)}</span>` : "",
		].join("");

		const websites = (a.websites || "")
			.split("\n")
			.filter(Boolean)
			.map((url) => `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a>`)
			.join("<br>");
		const contact = [
			a.description ? ["fa fa-align-left", esc(a.description).replace(/\n/g, "<br>")] : null,
			a.email ? ["fa fa-envelope-o", `<a href="mailto:${esc(a.email)}">${esc(a.email)}</a>`] : null,
			websites ? ["fa fa-globe", websites] : null,
			a.address ? ["fa fa-map-marker", esc(a.address).replace(/\n/g, "<br>")] : null,
		]
			.filter(Boolean)
			.map(
				([icon, html]) =>
					`<div class="wao-contact-row"><i class="${icon}"></i><div>${html}</div></div>`
			)
			.join("");

		const group = (access, title, hint) => {
			const list = (a.people || []).filter((p) => p.access === access);
			const rows =
				list
					.map(
						(p) => `
					<div class="wao-member" data-user="${esc(p.user)}">
						${this.person_avatar(p, 32)}
						<div class="wao-member-name">${esc(p.full_name)}<div class="text-muted wao-small">${esc(p.user)}</div></div>
						<select class="form-control input-xs wao-member-access">
							<option value="Responsible" ${access === "Responsible" ? "selected" : ""}>${__("Responsible")}</option>
							<option value="Spectator" ${access === "Spectator" ? "selected" : ""}>${__("Spectator")}</option>
						</select>
						<button class="btn btn-xs btn-default wao-member-remove" title="${__(
							"Take the number away"
						)}"><i class="fa fa-times"></i></button>
					</div>`
					)
					.join("") || `<div class="text-muted wao-small">${__("Nobody")}</div>`;
			return `<div class="wao-group"><div class="wao-group-head">${title}<span class="text-muted wao-small">${hint}</span></div>${rows}</div>`;
		};

		const pending =
			c.pending
				.map(
					(p) => `
				<div class="wao-pending-row">
					<a href="#" class="wao-open-chat" data-chat="${esc(p.chat || "")}">${esc(p.title)}</a>
					<span class="text-muted wao-small wao-preview">${esc(p.preview)}</span>
					<span class="wao-wait">${wao_duration(p.waiting)}</span>
				</div>`
				)
				.join("") ||
			`<div class="wao-ok"><i class="fa fa-check-circle"></i> ${__(
				"Every customer got a reply"
			)}</div>`;

		this.$body.html(`
			<div class="wao-number-page" data-account="${esc(a.name)}">
				<a href="#" class="wao-back"><i class="fa fa-arrow-left"></i> ${__("All numbers")}</a>
				<div class="wao-hero">
					${this.number_avatar(a, 96)}
					<div class="wao-hero-main">
						<div class="wao-hero-name">${esc(this.number_title(a))}</div>
						<div class="wao-hero-phone">${esc(this.number_line(a))}</div>
						${a.about ? `<div class="wao-hero-about">${esc(a.about)}</div>` : ""}
						<div class="wao-hero-pills">${pills}</div>
					</div>
					<div class="wao-hero-actions">
						<button class="btn btn-sm btn-primary wao-chats"><i class="fa fa-comments"></i> ${__("Chats")}</button>
						<button class="btn btn-sm btn-default wao-sync"><i class="fa fa-refresh"></i> ${__("Sync from Meta")}</button>
						${
							c.can_edit_account
								? `<button class="btn btn-sm btn-default wao-account"><i class="fa fa-cog"></i> ${__(
										"WhatsApp Account"
								  )}</button>`
								: ""
						}
					</div>
				</div>
				<div class="wao-number-grid">
					<div class="wao-col">
						<div class="wao-panel">
							<h6>${__("Business profile")}</h6>
							${
								contact ||
								`<div class="text-muted wao-small">${__(
									"Meta has no description, email, website or address for this number."
								)}</div>`
							}
							<div class="text-muted wao-small wao-synced">${
								a.profile_synced_on
									? __("Synced from Meta {0}", [
											frappe.datetime.comment_when(a.profile_synced_on),
									  ])
									: __("Not synced from Meta yet")
							} · ${__("Phone ID")}: ${esc(a.phone_id)}${
			a.account_name ? ` · ${esc(a.account_name)}` : ""
		}</div>
						</div>
						<div class="wao-panel">
							<h6>${__("Notes")}</h6>
							<div class="wao-notes"></div>
							<button class="btn btn-xs btn-default wao-notes-save">${__("Save notes")}</button>
						</div>
					</div>
					<div class="wao-col">
						<div class="wao-panel">
							<div class="wao-panel-head">
								<h6>${__("People")}</h6>
								<button class="btn btn-xs btn-default wao-member-add"><i class="fa fa-user-plus"></i> ${__(
									"Add person"
								)}</button>
							</div>
							${group("Responsible", __("Responsible"), __("answer customers"))}
							${group("Spectator", __("Spectators"), __("read only"))}
						</div>
						<div class="wao-panel">
							<h6>${__("Figures for the period")}</h6>
							<div class="wao-kpis wao-kpis-wide">
								<div><span class="wao-kpi">${a.pending}</span><span class="text-muted">${__("waiting")}</span></div>
								<div><span class="wao-kpi">${wao_duration(a.avg_reply)}</span><span class="text-muted">${__(
			"avg reply"
		)}</span></div>
								<div><span class="wao-kpi">${wao_duration(a.median_reply)}</span><span class="text-muted">${__(
			"median reply"
		)}</span></div>
								<div><span class="wao-kpi">${
									a.reply_rate === null ? "—" : a.reply_rate + "%"
								}</span><span class="text-muted">${__("answered")}</span></div>
								<div><span class="wao-kpi">${a.chats_total}</span><span class="text-muted">${__("chats")}</span></div>
								<div><span class="wao-kpi">${a.chats_active}</span><span class="text-muted">${__("active chats")}</span></div>
								<div><span class="wao-kpi">${a.chats_new}</span><span class="text-muted">${__("new chats")}</span></div>
								<div><span class="wao-kpi">${a.messages_in} / ${a.messages_out}</span><span class="text-muted">${__(
			"messages in / out"
		)}</span></div>
							</div>
						</div>
						<div class="wao-panel">
							<h6>${__("Waiting for a reply")}</h6>
							${pending}
						</div>
					</div>
				</div>
			</div>
		`);
		this.make_notes(a.notes);
	}

	make_notes(value) {
		this.notes_dirty = false;
		this.notes = frappe.ui.form.make_control({
			parent: this.$body.find(".wao-notes"),
			df: {
				fieldtype: "Text Editor",
				fieldname: "notes",
				change: () => {
					if (this.notes_ready) this.notes_dirty = true;
				},
			},
			render_input: true,
		});
		this.notes_ready = false;
		Promise.resolve(this.notes.set_value(value || "")).then(() => {
			setTimeout(() => (this.notes_ready = true), 300);
		});
	}

	bind_number_actions() {
		const account = () => this.number;
		const reload = (r) => {
			if (r && r.message) this.card = r.message;
			this.render();
		};
		const set_access = (user, access) =>
			frappe
				.call({
					method: `${WAO_API}.set_number_access`,
					args: { account: account(), user, access: access || "" },
				})
				.then(() => this.refresh(true));

		this.$body.on("click", ".wao-back", (e) => {
			e.preventDefault();
			this.tab = "numbers";
			frappe.set_route("whatsapp-overview");
		});
		this.$body.on("click", ".wao-chats", () =>
			frappe.set_route("whatsapp-chat-center", { number: account() })
		);
		this.$body.on("click", ".wao-account", () => frappe.set_route("Form", "WhatsApp Account", account()));
		this.$body.on("click", ".wao-sync", () =>
			frappe
				.call({
					method: `${WAO_API}.sync_number`,
					args: { account: account(), period: this.period },
					freeze: true,
					freeze_message: __("Loading the profile from Meta…"),
				})
				.then(reload)
		);
		this.$body.on("click", ".wao-notes-save", () =>
			frappe
				.call({
					method: `${WAO_API}.save_notes`,
					args: { account: account(), notes: this.notes.get_value() || "" },
				})
				.then(() => {
					this.notes_dirty = false;
					if (this.card) this.card.number.notes = this.notes.get_value();
					frappe.show_alert({ message: __("Notes saved"), indicator: "green" });
				})
		);
		this.$body.on("change", ".wao-member-access", (e) => {
			const user = $(e.currentTarget).closest(".wao-member").data("user");
			set_access(user, $(e.currentTarget).val());
		});
		this.$body.on("click", ".wao-member-remove", (e) => {
			const $row = $(e.currentTarget).closest(".wao-member");
			frappe.confirm(
				__("Take number {0} away from {1}?", [
					this.esc(this.number_title(this.card.number)),
					this.esc($row.find(".wao-member-name").contents().first().text()),
				]),
				() => set_access($row.data("user"), "")
			);
		});
		this.$body.on("click", ".wao-member-add", () => this.add_person_dialog(set_access));
	}

	add_person_dialog(set_access) {
		const candidates = (this.card && this.card.candidates) || [];
		if (!candidates.length) {
			frappe.msgprint(
				__(
					"Everyone who works with WhatsApp already has this number. Add more people on the Employees tab."
				)
			);
			return;
		}
		const by_label = {};
		candidates.forEach((c) => (by_label[`${c.full_name} (${c.user})`] = c.user));
		const d = new frappe.ui.Dialog({
			title: __("Add person to {0}", [this.number_title(this.card.number)]),
			fields: [
				{
					fieldname: "person",
					fieldtype: "Select",
					label: __("Employee"),
					options: Object.keys(by_label),
					reqd: 1,
				},
				{
					fieldname: "access",
					fieldtype: "Select",
					label: __("Access"),
					options: [
						{ value: "Responsible", label: __("Responsible — answers customers") },
						{ value: "Spectator", label: __("Spectator — read only") },
					],
					default: "Responsible",
					reqd: 1,
				},
			],
			primary_action_label: __("Add"),
			primary_action: (v) => {
				d.hide();
				set_access(by_label[v.person], v.access);
			},
		});
		d.show();
	}

	// ------------------------------------------------------------------ employees

	render_employees(d) {
		const numbers = (e) =>
			e.numbers
				.map(
					(n) =>
						`<div class="wao-row-number"><a href="#" data-number="${this.esc(
							n.whatsapp_account
						)}">${this.esc(n.label)}</a>${this.access_pill(n.access)}</div>`
				)
				.join("") ||
			`<span class="text-muted">${
				e.level === "Admin" ? __("All numbers") : __("No number assigned")
			}</span>`;
		const level = (e) => {
			if (e.level === "Admin") return this.level_pill("Admin");
			return `<select class="form-control input-xs wao-level">
				<option value="" ${e.level ? "" : "selected"}>${__("No access")}</option>
				<option value="Employee" ${e.level === "Employee" ? "selected" : ""}>${__("Employee")}</option>
				<option value="Manager" ${e.level === "Manager" ? "selected" : ""}>${__("Manager")}</option>
			</select>`;
		};
		const rows = d.employees
			.filter((e) => this.match(e.full_name, e.user, ...e.numbers.map((n) => n.label)))
			.map(
				(e) => `
				<tr data-user="${this.esc(e.user)}" data-name="${this.esc(e.full_name)}">
					<td><div class="wao-who">${this.person_avatar(e, 32)}<div>
						<div class="wao-number">${this.esc(e.full_name)}</div>
						<div class="text-muted wao-small">${this.esc(e.user)}</div>
					</div></div></td>
					<td>${level(e)}</td>
					<td>${numbers(e)}</td>
					<td class="wao-num">${e.replies}</td>
					<td class="wao-num">${wao_duration(e.avg_reply)}<div class="text-muted wao-small">${__("median {0}", [
					wao_duration(e.median_reply),
				])}</div></td>
					<td class="wao-num">${e.messages_sent}</td>
					<td class="wao-num">${e.pending}</td>
					<td>${e.last_activity ? frappe.datetime.comment_when(e.last_activity) : "—"}</td>
				</tr>`
			)
			.join("");
		return `
			<div class="wao-toolbar">
				<button class="btn btn-sm btn-default wao-employee-add"><i class="fa fa-user-plus"></i> ${__(
					"Add employee"
				)}</button>
				<div class="text-muted wao-small wao-legend">
					<div><b>${__("Employee")}</b> — ${__("chats on the numbers given to them")}</div>
					<div><b>${__("Manager")}</b> — ${__("also opens this overview, edits number cards and gives access")}</div>
					<div><b>${__("System Manager")}</b> — ${__("everything, on every number")}</div>
				</div>
			</div>
			${
				rows
					? `<div class="wao-table-wrap"><table class="table table-bordered wao-table">
				<thead><tr>
					<th>${__("Employee")}</th>
					<th>${__("WhatsApp level")}</th>
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
			)}</div>`
					: `<div class="text-muted wao-empty">${__("Nobody works with WhatsApp yet")}</div>`
			}`;
	}

	bind_employee_actions() {
		const set_level = (user, level) =>
			frappe
				.call({ method: `${WAO_API}.set_employee`, args: { user, level: level || "" } })
				.then(() => this.refresh(true))
				.fail(() => this.render());

		this.$body.on("change", ".wao-level", (e) => {
			const $row = $(e.currentTarget).closest("tr");
			const level = $(e.currentTarget).val();
			if (level) return set_level($row.data("user"), level);
			frappe.confirm(
				__("Take WhatsApp away from {0}? They lose every number.", [this.esc($row.data("name"))]),
				() => set_level($row.data("user"), ""),
				() => this.render()
			);
		});
		this.$body.on("click", ".wao-employee-add", () => {
			const d = new frappe.ui.Dialog({
				title: __("Add employee"),
				fields: [
					{
						fieldname: "user",
						fieldtype: "Link",
						options: "User",
						label: __("User"),
						reqd: 1,
						get_query: () => ({ filters: { enabled: 1, user_type: "System User" } }),
					},
					{
						fieldname: "level",
						fieldtype: "Select",
						label: __("WhatsApp level"),
						options: [
							{ value: "Employee", label: __("Employee — chats on given numbers") },
							{ value: "Manager", label: __("Manager — also configures WhatsApp") },
						],
						default: "Employee",
						reqd: 1,
					},
				],
				primary_action_label: __("Add"),
				primary_action: (v) => {
					d.hide();
					set_level(v.user, v.level);
				},
			});
			d.show();
		});
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
					<td><a href="#" data-number="${this.esc(p.whatsapp_account)}">${this.esc(p.number_label)}</a></td>
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
		const admin = frappe.user.has_role("System Manager");
		return `
			<div class="wao-tiles">
				${link(
					"whatsapp-chat-settings",
					"fa fa-clock-o",
					__("Working Hours"),
					__("Hours and holidays counted in reply times")
				)}
				${
					admin
						? link(
								"whatsapp-account",
								"fa fa-phone",
								__("WhatsApp Accounts"),
								__("Business numbers and API keys")
						  )
						: ""
				}
			</div>
			<h5 class="wao-h">${__("Working hours")}</h5>
			<div class="wao-hours">${hours}</div>
			<div class="text-muted wao-small">${__("Holiday list")}: ${this.esc(d.schedule.holiday_list || "—")}</div>
		`;
	}
}
