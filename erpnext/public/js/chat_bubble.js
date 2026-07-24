// Floating chat bubble shown on every desk page (bottom right).
// Two tabs: WhatsApp (customer threads) and Employee Chat (internal).
// Click opens a compact popup: conversation list -> thread with quick reply,
// plus a button that jumps to the full chat page.

frappe.provide("erpnext.whatsapp");


const WA_API = "erpnext.crm.page.whatsapp_chat.whatsapp_chat";
const EC_API = "erpnext.crm.page.employee_chat.employee_chat";

// A user may use a chat only with both the doctype read permission and access to
// the page itself (server side enforces the same, see _require_wa_access).
function cb_page_allowed(page) {
	const pages = frappe.boot?.page_info || {};
	return !!pages[page];
}

erpnext.whatsapp.can_use = function () {
	return (
		(frappe.boot?.user?.can_read || []).includes("WhatsApp Message") &&
		cb_page_allowed("whatsapp-chat-center")
	);
};

erpnext.whatsapp.can_use_employee_chat = function () {
	return (
		(frappe.boot?.user?.can_read || []).includes("Chat Thread") &&
		cb_page_allowed("employee-chat")
	);
};

function cb_media_label(content_type) {
	return {
		image: "📷 " + __("Photo"),
		video: "🎬 " + __("Video"),
		audio: "🎤 " + __("Audio"),
		document: "📎 " + __("Document"),
		file: "📎 " + __("File"),
		sticker: "🩷 " + __("Sticker"),
	}[content_type];
}

function cb_fmt_time(dt) {
	if (!dt) return "";
	const tz = frappe.sys_defaults.time_zone || "UTC";
	return moment.tz(dt, tz).local().format("DD.MM HH:mm");
}

function cb_text(msg) {
	const caption = frappe.utils.escape_html((msg.message || "").replace(/<[^>]*>/g, ""));
	const label = cb_media_label(msg.content_type);
	if (label) return caption ? `${label}: ${caption}` : label;
	return caption || `<i>(${__("no text")})</i>`;
}

// --- WhatsApp source -------------------------------------------------------

class WhatsAppSource {
	constructor() {
		this.key = "whatsapp";
		this.label = __("WhatsApp");
		this.page_route = "/app/whatsapp-chat-center";
		this.realtime_events = ["whatsapp_message", "whatsapp_read"];
		this.chats = [];
	}

	static available() {
		return erpnext.whatsapp.can_use();
	}

	async load_list() {
		const chats = await frappe.xcall(`${WA_API}.get_chats`);
		this.chats = chats.map((c) => ({
			id: c.phone,
			title: c.title || c.phone,
			preview: c.preview,
			time: c.last_message_on,
			unread: c.unread || 0,
			muted: c.muted || 0,
		}));
		return this.chats;
	}

	async load_messages(id) {
		const msgs = await frappe.xcall(`${WA_API}.get_recent_messages`, { phone: id, limit: 20 });
		return msgs.map((m) => ({
			out: m.type === "Outgoing",
			html: cb_text(m),
			time: m.creation,
			author: null,
		}));
	}

	// Server-side read cursor (WhatsApp Chat Read), shared with the Chat Center page.
	async mark_read(id) {
		const chat = this.chats.find((c) => c.id === id);
		if (chat) chat.unread = 0;
		try {
			await frappe.xcall(`${WA_API}.mark_read`, { phone: id });
		} catch (e) {
			// non-fatal — the badge reappears on the next poll
		}
	}

	set_muted(id, muted) {
		return frappe.xcall(`${WA_API}.set_muted`, { phone: id, muted });
	}

	send(id, text) {
		return frappe.xcall(`${WA_API}.send_text`, { phone: id, message: text });
	}

	route_for(id) {
		return id ? `${this.page_route}?phone=${encodeURIComponent(id)}` : this.page_route;
	}
}

// --- Employee Chat source --------------------------------------------------

class EmployeeChatSource {
	constructor() {
		this.key = "employee";
		this.label = __("Employees");
		this.page_route = "/app/employee-chat";
		this.realtime_events = ["chat_message", "chat_seen"];
		this.chats = [];
	}

	static available() {
		return erpnext.whatsapp.can_use_employee_chat();
	}

	async load_list() {
		const threads = await frappe.xcall(`${EC_API}.get_threads`);
		this.chats = threads.map((t) => ({
			id: t.name,
			title: (t.is_secret ? "🔒 " : "") + (t.display_title || t.title || t.name),
			preview: t.last_message_preview,
			time: t.last_message_on,
			unread: t.unread || 0,
			muted: t.muted || 0,
			is_secret: t.is_secret,
		}));
		return this.chats;
	}

	is_secret(id) {
		const chat = this.chats.find((c) => c.id === id);
		return !!(chat && chat.is_secret);
	}

	async load_messages(id) {
		const msgs = await frappe.xcall(`${EC_API}.get_messages`, { thread: id, limit: 20 });
		const me = frappe.session.user;
		// Secret threads unlock from the full chat page; here we decrypt only if the key
		// already happens to be in memory, and never render raw ciphertext.
		const unlocked = erpnext.chat_crypto.is_unlocked();
		const out = [];
		for (const m of msgs) {
			let html;
			if (m.is_encrypted) {
				html = `🔒 ${__("Encrypted")}`;
				if (unlocked) {
					try {
						const dec = await erpnext.chat_crypto.decrypt(id, m.message, m.enc_iv);
						html = cb_text({
							content_type: m.content_type,
							message: dec.text || "",
						});
					} catch (e) {
						// leave the lock
					}
				}
			} else {
				html = cb_text(m);
			}
			out.push({
				out: m.sender === me,
				html,
				time: m.creation,
				author: m.sender === me ? null : m.sender_name,
			});
		}
		return out;
	}

	async mark_read(id) {
		try {
			await frappe.xcall(`${EC_API}.mark_read`, { thread: id });
		} catch (e) {
			return;
		}
		const chat = this.chats.find((c) => c.id === id);
		if (chat) chat.unread = 0;
	}

	set_muted(id, muted) {
		return frappe.xcall(`${EC_API}.set_muted`, { thread: id, muted });
	}

	async send(id, text) {
		if (!this.is_secret(id)) {
			return frappe.xcall(`${EC_API}.send_message`, { thread: id, message: text });
		}
		if (!(await erpnext.chat_crypto.ensure_unlocked())) return;
		const { ciphertext, iv } = await erpnext.chat_crypto.encrypt(id, { text });
		return frappe.xcall(`${EC_API}.send_message`, {
			thread: id,
			message: ciphertext,
			is_encrypted: 1,
			enc_iv: iv,
		});
	}

	route_for(id) {
		return id ? `${this.page_route}?thread=${encodeURIComponent(id)}` : this.page_route;
	}
}

// --- Bubble widget ---------------------------------------------------------

class ChatBubble {
	constructor(sources) {
		this.sources = sources;
		this.source = sources[0];
		this.active = null; // open conversation id
		this.open = false;
		this.inject_styles();
		this.make_dom();
		this.bind_events();
		this.refresh();

		this.on_rt = (d) => {
			console.log("[chat] bubble realtime event", d);
			this.ring(d);
			this.refresh();
		};
		this.sources.forEach((s) =>
			s.realtime_events.forEach((ev) => frappe.realtime.on(ev, this.on_rt))
		);
		this.poll = setInterval(() => this.refresh(), 60000);
	}

	// A message from someone else rings, unless the conversation is muted for this user
	// or the sound is switched off on this device.
	ring(d) {
		if (!d) return;
		let chat = null;
		if (d.type === "Incoming" && d.number) {
			// WhatsApp: {name, number, type}
			chat = (this.sources.find((s) => s.key === "whatsapp")?.chats || []).find(
				(c) => c.id === d.number
			);
			console.log("[chat] ring: whatsapp incoming", { number: d.number, chat_found: !!chat, muted: chat && chat.muted });
		} else if (d.sender && d.sender !== frappe.session.user && d.thread) {
			// Employee Chat: a full message payload
			chat = (this.sources.find((s) => s.key === "employee")?.chats || []).find(
				(c) => c.id === d.thread
			);
			console.log("[chat] ring: employee message", { thread: d.thread, sender: d.sender, chat_found: !!chat, muted: chat && chat.muted });
		} else {
			console.log("[chat] ring: event ignored (not an incoming/foreign message)", d);
			return;
		}
		erpnext.chat_sound.play(chat && chat.muted);
	}

	render_sound_toggle() {
		const on = erpnext.chat_sound.enabled();
		this.$sound.text(on ? "🔊" : "🔇").attr(
			"title",
			on ? __("Notification sound is on") : __("Notification sound is off")
		);
	}

	// The per-conversation mute is only meaningful with a thread open.
	render_mute_toggle() {
		const chat = this.active
			? (this.source.chats || []).find((c) => c.id === this.active)
			: null;
		if (!chat || !this.source.set_muted) return this.$mute.hide();
		this.$mute
			.show()
			.text(chat.muted ? "🔕" : "🔔")
			.attr("title", chat.muted ? __("Unmute chat") : __("Mute chat"));
	}

	async toggle_mute() {
		const chat = (this.source.chats || []).find((c) => c.id === this.active);
		if (!chat || !this.source.set_muted) return;
		const muted = chat.muted ? 0 : 1;
		chat.muted = muted;
		this.render_mute_toggle();
		try {
			await this.source.set_muted(this.active, muted);
		} catch (e) {
			chat.muted = muted ? 0 : 1;
			this.render_mute_toggle();
		}
	}

	inject_styles() {
		if (document.getElementById("cb-bubble-styles")) return;
		const css = `
		.cb-fab{position:fixed;right:24px;bottom:24px;z-index:1035;width:56px;height:56px;border-radius:50%;
			background:#25d366;color:#fff;border:none;box-shadow:0 4px 14px rgba(0,0,0,.28);font-size:26px;line-height:56px;
			text-align:center;cursor:pointer;transition:transform .15s ease;}
		.cb-fab:hover{transform:scale(1.06);}
		.cb-badge{position:absolute;top:-2px;right:-2px;min-width:20px;height:20px;padding:0 5px;border-radius:10px;
			background:var(--red-500,#e24c4c);color:#fff;font-size:11px;line-height:20px;font-weight:600;text-align:center;display:none;}
		.cb-panel{position:fixed;right:24px;bottom:92px;z-index:1035;width:360px;height:480px;display:none;
			flex-direction:column;background:var(--card-bg);border:1px solid var(--border-color);
			border-radius:var(--border-radius-md);box-shadow:0 8px 28px rgba(0,0,0,.25);overflow:hidden;}
		.cb-panel.open{display:flex;}
		.cb-head{display:flex;align-items:center;gap:6px;padding:8px 10px;border-bottom:1px solid var(--border-color);
			background:#075e54;color:#fff;}
		.cb-title{flex:1;font-weight:600;font-size:var(--text-md);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
		.cb-head .cb-act{cursor:pointer;opacity:.85;font-size:15px;line-height:1;padding:2px 4px;}
		.cb-head .cb-act:hover{opacity:1;}
		.cb-tabs{display:flex;border-bottom:1px solid var(--border-color);}
		.cb-tab{flex:1;padding:6px 8px;text-align:center;cursor:pointer;font-size:var(--text-sm);color:var(--text-muted);
			border-bottom:2px solid transparent;}
		.cb-tab.active{color:var(--text-color);font-weight:600;border-bottom-color:#25d366;}
		.cb-tab .cb-tab-count{display:inline-block;min-width:16px;height:16px;padding:0 4px;margin-left:4px;border-radius:8px;
			background:var(--red-500,#e24c4c);color:#fff;font-size:10px;line-height:16px;}
		.cb-body{flex:1;overflow-y:auto;}
		.cb-conv{padding:9px 12px;border-bottom:1px solid var(--border-color);cursor:pointer;}
		.cb-conv:hover{background:var(--bg-light-gray);}
		.cb-conv .cb-name{font-weight:600;font-size:var(--text-sm);display:flex;justify-content:space-between;gap:6px;}
		.cb-conv .cb-time{font-weight:400;color:var(--text-muted);font-size:10px;white-space:nowrap;}
		.cb-conv .cb-prev{color:var(--text-muted);font-size:var(--text-sm);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
		.cb-conv.unread .cb-prev{color:var(--text-color);font-weight:600;}
		.cb-thread{display:flex;flex-direction:column;gap:3px;padding:10px;background:var(--bg-gray);min-height:100%;}
		.cb-msg{width:fit-content;max-width:82%;padding:4px 8px 2px;border-radius:8px;font-size:12px;line-height:1.35;word-break:break-word;}
		.cb-msg .cb-msg-text{white-space:pre-wrap;}
		.cb-msg .cb-author{font-size:10px;font-weight:600;color:var(--primary);margin-bottom:1px;}
		.cb-in{align-self:flex-start;background:var(--card-bg);border:1px solid var(--border-color);}
		.cb-out{align-self:flex-end;background:#d9fdd3;color:#111;}
		.cb-msg .cb-meta{font-size:10px;color:var(--text-muted);text-align:right;opacity:.75;margin-top:1px;}
		.cb-empty{padding:24px 12px;text-align:center;color:var(--text-muted);font-size:var(--text-sm);}
		.cb-compose{display:flex;gap:6px;padding:8px;border-top:1px solid var(--border-color);align-items:flex-end;}
		.cb-compose textarea{resize:none;flex:1;font-size:12px;}
		.cb-foot{padding:6px 8px;border-top:1px solid var(--border-color);}
		@media (max-width:600px){
			.cb-panel{right:12px;left:12px;width:auto;bottom:84px;height:70vh;}
			.cb-fab{right:16px;bottom:16px;}
		}
		`;
		$(`<style id="cb-bubble-styles">${css}</style>`).appendTo(document.head);
	}

	make_dom() {
		this.$fab = $(`
			<button class="cb-fab" title="${__("Chat")}">
				<span>💬</span>
				<span class="cb-badge"></span>
			</button>
		`).appendTo(document.body);

		const tabs = this.sources
			.map(
				(s) =>
					`<div class="cb-tab" data-key="${s.key}">${frappe.utils.escape_html(s.label)}<span class="cb-tab-count" style="display:none;"></span></div>`
			)
			.join("");

		this.$panel = $(`
			<div class="cb-panel">
				<div class="cb-head">
					<span class="cb-act cb-back" title="${__("Back")}" style="display:none;">←</span>
					<span class="cb-title">${__("Chat")}</span>
					<span class="cb-act cb-mute" title="${__("Mute chat")}" style="display:none;"></span>
					<span class="cb-act cb-sound" title="${__("Notification sound")}"></span>
					<span class="cb-act cb-open-page" title="${__("Open full page")}">⤢</span>
					<span class="cb-act cb-close" title="${__("Close")}">&times;</span>
				</div>
				<div class="cb-tabs" ${this.sources.length > 1 ? "" : 'style="display:none;"'}>${tabs}</div>
				<div class="cb-body"></div>
				<div class="cb-compose" style="display:none;">
					<textarea class="form-control" rows="1" placeholder="${__("Type a message")}"></textarea>
					<button class="btn btn-primary btn-xs cb-send">${__("Send")}</button>
				</div>
				<div class="cb-foot">
					<button class="btn btn-default btn-xs cb-goto" style="width:100%;">${__("Open full page")}</button>
				</div>
			</div>
		`).appendTo(document.body);

		this.$body = this.$panel.find(".cb-body");
		this.$badge = this.$fab.find(".cb-badge");
		this.$title = this.$panel.find(".cb-title");
		this.$back = this.$panel.find(".cb-back");
		this.$mute = this.$panel.find(".cb-mute");
		this.$sound = this.$panel.find(".cb-sound");
		this.render_sound_toggle();
		this.$compose = this.$panel.find(".cb-compose");
		this.$input = this.$compose.find("textarea");
		this.$panel.find(`.cb-tab[data-key="${this.source.key}"]`).addClass("active");
	}

	bind_events() {
		this.$fab.on("click", () => this.toggle());
		this.$panel.find(".cb-close").on("click", () => this.toggle(false));
		this.$back.on("click", () => this.show_list());
		this.$panel.find(".cb-goto, .cb-open-page").on("click", () => this.goto_page());
		this.$sound.on("click", () => {
			erpnext.chat_sound.set_enabled(!erpnext.chat_sound.enabled());
			this.render_sound_toggle();
		});
		this.$mute.on("click", () => this.toggle_mute());
		this.$panel.find(".cb-send").on("click", () => this.send());
		this.$input.on("keydown", (e) => {
			if (e.key === "Enter" && !e.shiftKey) {
				e.preventDefault();
				this.send();
			}
		});
		this.$panel.find(".cb-tab").on("click", (e) => {
			this.switch_source($(e.currentTarget).attr("data-key"));
		});
		this.$body.on("click", ".cb-conv", (e) => {
			this.open_thread($(e.currentTarget).attr("data-id"));
		});
	}

	switch_source(key) {
		const src = this.sources.find((s) => s.key === key);
		if (!src || src === this.source) return;
		this.source = src;
		this.$panel.find(".cb-tab").removeClass("active");
		this.$panel.find(`.cb-tab[data-key="${key}"]`).addClass("active");
		this.show_list();
		this.refresh();
	}

	goto_page() {
		window.location.href = this.source.route_for(this.active);
	}

	toggle(state) {
		this.open = state === undefined ? !this.open : state;
		this.$panel.toggleClass("open", this.open);
		if (this.open) {
			this.refresh();
			if (!this.active) this.show_list();
		}
	}

	async refresh() {
		await Promise.all(
			this.sources.map(async (s) => {
				try {
					await s.load_list();
				} catch (e) {
					s.chats = s.chats || [];
				}
			})
		);
		this.render_badges();
		if (!this.open) return;
		if (this.active) {
			this.load_thread(this.active);
		} else {
			this.render_list();
		}
	}

	render_badges() {
		let total = 0;
		this.sources.forEach((s) => {
			// Sum unread *messages* across conversations (each c.unread is already a message
			// count, secret threads included — the server counts rows, never plaintext), not
			// the number of conversations that have something unread.
			const count = (s.chats || []).reduce((n, c) => n + (c.unread || 0), 0);
			console.log("[chat] render_badges source=" + s.key, {
				convs_with_unread: count,
				rows: (s.chats || []).map((c) => ({ id: c.id, unread: c.unread })),
			});
			total += count;
			this.$panel
				.find(`.cb-tab[data-key="${s.key}"] .cb-tab-count`)
				.text(count > 99 ? "99+" : count)
				.toggle(count > 0);
		});
		this.$badge.text(total > 99 ? "99+" : total).toggle(total > 0);
	}

	show_list() {
		this.active = null;
		if (this.$mute) this.$mute.hide();
		this.$back.hide();
		this.$compose.hide();
		this.$title.text(this.source.label);
		this.render_list();
	}

	render_list() {
		const chats = this.source.chats || [];
		if (!chats.length) {
			this.$body.html(`<div class="cb-empty">${__("No conversations yet")}</div>`);
			return;
		}
		const rows = chats
			.map((c) => {
				const name = frappe.utils.escape_html(c.title);
				const prev = frappe.utils.escape_html(
					(c.preview || "").replace(/<[^>]*>/g, "").slice(0, 80)
				);
				return `<div class="cb-conv ${c.unread ? "unread" : ""}" data-id="${frappe.utils.escape_html(c.id)}">
					<div class="cb-name"><span>${name}</span><span class="cb-time">${cb_fmt_time(c.time)}</span></div>
					<div class="cb-prev">${prev || __("(no text)")}</div>
				</div>`;
			})
			.join("");
		this.$body.html(rows);
	}

	open_thread(id) {
		console.log("[chat] open_thread (conversation clicked)", { source: this.source.key, id });
		this.active = id;
		const chat = (this.source.chats || []).find((c) => c.id === id);
		this.$title.text(chat ? chat.title : id);
		this.render_mute_toggle();
		this.$back.show();
		this.$compose.show();
		this.$body.html(`<div class="cb-empty">${__("Loading")}...</div>`);
		this.load_thread(id);
	}

	async load_thread(id) {
		const source = this.source;
		let msgs = [];
		try {
			msgs = await source.load_messages(id);
		} catch (e) {
			this.$body.html(`<div class="cb-empty">${__("Could not load messages")}</div>`);
			return;
		}
		if (this.active !== id || this.source !== source) return;

		// Only move the read cursor when there is actually something unread. mark_read
		// publishes a realtime event (chat_seen / whatsapp_read) that every open bubble —
		// including this one — reacts to with a refresh() that re-enters load_thread. Marking
		// unconditionally on every refresh therefore feedback-loops at socket speed. Gating on
		// unread breaks it: after the first mark the count is 0, so the echo can't re-arm it.
		const chat = (source.chats || []).find((c) => c.id === id);
		if (chat && chat.unread) {
			console.log("[chat] load_thread: marking read (unread=" + chat.unread + ")", { id });
			await source.mark_read(id);
			this.render_badges();
		}

		const bubbles = msgs
			.map(
				(m) => `<div class="cb-msg ${m.out ? "cb-out" : "cb-in"}">
					${m.author ? `<div class="cb-author">${frappe.utils.escape_html(m.author)}</div>` : ""}
					<div class="cb-msg-text">${m.html}</div>
					<div class="cb-meta">${cb_fmt_time(m.time)}</div>
				</div>`
			)
			.join("");

		this.$body.html(
			`<div class="cb-thread">${bubbles || `<div class="cb-empty">${__("No messages yet")}</div>`}</div>`
		);
		this.$body.scrollTop(this.$body[0].scrollHeight);
	}

	async send() {
		const text = (this.$input.val() || "").trim();
		if (!text || !this.active) return;
		this.$input.val("");
		try {
			await this.source.send(this.active, text);
		} catch (e) {
			this.$input.val(text);
			return;
		}
		this.load_thread(this.active);
	}
}

erpnext.whatsapp.init_bubble = function () {
	if (erpnext.whatsapp.bubble) return;
	if (!frappe.session || frappe.session.user === "Guest") return;

	const sources = [];
	if (WhatsAppSource.available()) sources.push(new WhatsAppSource());
	if (EmployeeChatSource.available()) sources.push(new EmployeeChatSource());
	if (!sources.length) return;

	erpnext.whatsapp.bubble = new ChatBubble(sources);
	erpnext.whatsapp.toggle_bubble_visibility();
	frappe.router?.on("change", () => erpnext.whatsapp.toggle_bubble_visibility());
};

// Hide the bubble on the full chat pages themselves.
erpnext.whatsapp.toggle_bubble_visibility = function () {
	const b = erpnext.whatsapp.bubble;
	if (!b) return;
	const route = (frappe.get_route() || []).join("/");
	const on_chat_page =
		route.includes("whatsapp-chat-center") || route.includes("employee-chat");
	b.$fab.toggle(!on_chat_page);
	if (on_chat_page) b.toggle(false);
};

$(document).on("app_ready", function () {
	erpnext.whatsapp.init_bubble();
});
