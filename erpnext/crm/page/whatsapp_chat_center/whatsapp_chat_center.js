frappe.pages["whatsapp-chat-center"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("WhatsApp Chat"),
		single_column: true,
	});
	new WhatsAppChat(page);
};

const LINKABLE_DOCTYPES = ["Lead", "Contact", "Customer", "Opportunity", "Quotation", "Sales Order"];

// Emoji shown in the compose picker and (first 6) as quick reactions.
const EMOJI_SET = [
	"👍", "❤️", "😂", "😮", "😢", "🙏",
	"👏", "🔥", "🎉", "😊", "😍", "🤔",
	"👌", "✅", "❌", "⚠️", "💰", "📦",
	"😅", "😁", "😉", "🥳", "💪", "🚀",
];
const QUICK_REACTIONS = EMOJI_SET.slice(0, 6);

// WhatsApp media content types we render specially.
const MEDIA_TYPES = ["image", "video", "audio", "document", "sticker"];

// History is paged: only the newest PAGE_SIZE messages load with a conversation,
// older ones are fetched as the user scrolls up.
const PAGE_SIZE = 50;
// How many trailing messages are re-read on each refresh to pick up status changes.
const STATUS_TAIL = 30;

// Map whatever the file picker reports (MIME type or bare extension) to the
// WhatsApp content_type we send. Shared with Employee Chat.
function mime_to_content_type(type, file_name) {
	return erpnext.chat_media.detect_type(type, file_name);
}

// Short labelled icon for a non-text message (list preview + form panel).
function media_label(content_type) {
	return {
		image: "📷 " + __("Photo"),
		video: "🎬 " + __("Video"),
		audio: "🎤 " + __("Audio"),
		document: "📎 " + __("Document"),
		sticker: "🩷 " + __("Sticker"),
	}[content_type];
}

class WhatsAppChat {
	constructor(page) {
		this.page = page;
		this.active = null; // active conversation number
		this.account = null; // default outgoing WhatsApp Account
		this.conversations = {}; // number -> {number, name, last, messages:[]}
		this.manager = null; // manager filter
		this.context = null; // context of the open chat
		this.reply_to = null; // {message_id, preview} when composing a reply
		this.make_layout();
		this.load_managers();
		this.load_account().then(() => this.refresh());
		// realtime push from server on new/updated WhatsApp Message
		// Incoming messages ring (unless the conversation is muted); everything else just
		// refreshes.
		this.on_rt = (d) => {
			console.log("[chat] page realtime event", d);
			if (d && d.type === "Incoming" && d.number) {
				const c = this.conversations[d.number];
				console.log("[chat] page incoming ring", { number: d.number, conv_found: !!c, muted: c && c.muted });
				erpnext.chat_sound.play(c && c.muted);
			}
			this.refresh(true);
		};
		frappe.realtime.on("whatsapp_message", this.on_rt);
		// Another tab of ours read a conversation — drop the badge here too.
		frappe.realtime.on("whatsapp_read", this.on_rt);
		// slow poll as a safety net if the socket drops
		this.poll = setInterval(() => this.refresh(true), 30000);
		$(this.page.wrapper).on("remove", () => {
			clearInterval(this.poll);
			frappe.realtime.off("whatsapp_message", this.on_rt);
			frappe.realtime.off("whatsapp_read", this.on_rt);
		});
		// deep-link: /app/whatsapp-chat-center?phone=380...
		const phone = frappe.utils.get_url_arg("phone");
		if (phone) this.pending_open = phone;
	}

	make_layout() {
		this.page.main.html(`
			<div class="wa-chat">
				<div class="wa-sidebar">
					<div class="wa-search">
						<button class="btn btn-primary btn-xs wa-new-chat" style="width:100%;margin-bottom:6px;">+ ${__("New chat")}</button>
						<input type="text" class="form-control input-xs wa-search-input" placeholder="${__("Search number or name")}">
						<select class="form-control input-xs wa-manager-filter" style="margin-top:6px;">
							<option value="">${__("All managers")}</option>
						</select>
					</div>
					<div class="wa-conv-list"></div>
				</div>
				<div class="wa-thread-wrap">
					<div class="wa-thread-header text-muted">${__("Select a conversation")}</div>
					<div class="wa-thread"></div>
					<div class="wa-scroll-fab" title="${__("Scroll to latest")}">⬇<span class="wa-fab-badge" style="display:none;"></span></div>
					<div class="wa-compose-wrap" style="display:none;">
						<div class="wa-reply-bar" style="display:none;">
							<div class="wa-reply-bar-text"></div>
							<span class="wa-reply-cancel" title="${__("Cancel reply")}">&times;</span>
						</div>
						<div class="wa-compose">
							<button class="btn btn-default btn-sm wa-attach" title="${__("Attach file")}">📎</button>
							<button class="btn btn-default btn-sm wa-emoji" title="${__("Add emoji")}">😊</button>
							<button class="btn btn-default btn-sm wa-template" title="${__("Send template")}">📋</button>
							<textarea class="form-control" rows="1" placeholder="${__("Type a message")}"></textarea>
							<button class="btn btn-primary btn-sm wa-send">${__("Send")}</button>
						</div>
					</div>
				</div>
				<div class="wa-context">
					<div class="wa-context-empty text-muted">${__("Select a conversation")}</div>
				</div>
			</div>
		`);
		this.inject_styles();

		this.$list = this.page.main.find(".wa-conv-list");
		this.$thread = this.page.main.find(".wa-thread");
		this.$header = this.page.main.find(".wa-thread-header");
		this.$compose = this.page.main.find(".wa-compose-wrap");
		this.$input = this.page.main.find(".wa-compose textarea");
		this.$replyBar = this.page.main.find(".wa-reply-bar");
		this.$search = this.page.main.find(".wa-search-input");
		this.$manager = this.page.main.find(".wa-manager-filter");
		this.$context = this.page.main.find(".wa-context");
		this.$fab = this.page.main.find(".wa-scroll-fab");
		this.$fab.on("click", () => this.jump_to_latest());

		this.page.main.find(".wa-new-chat").on("click", () => this.new_chat_prompt());
		this.page.main.find(".wa-send").on("click", () => this.send());
		this.page.main.find(".wa-attach").on("click", () => this.attach_media());
		this.page.main.find(".wa-emoji").on("click", (e) => this.emoji_picker(e));
		this.page.main.find(".wa-template").on("click", () => this.template_dialog());
		this.$replyBar.find(".wa-reply-cancel").on("click", () => this.set_reply(null));
		this.$input.on("keydown", (e) => {
			if (e.key === "Enter" && !e.shiftKey) {
				e.preventDefault();
				this.send();
			}
		});
		this.$search.on("input", () => this.render_list());
		this.$manager.on("change", () => this.apply_manager_filter());
		this.$thread.on("scroll", () => {
			if (this.$thread.scrollTop() < 40) this.load_older();
			this.update_read_progress();
			this.update_fab();
		});
	}

	inject_styles() {
		erpnext.chat_media.inject_styles();
		erpnext.chat_sound.inject_styles();
		if (document.getElementById("wa-chat-styles-v6")) return;
		const css = `
		.wa-chat{display:flex;height:calc(100vh - 160px);border:1px solid var(--border-color);border-radius:var(--border-radius-md);overflow:hidden;background:var(--card-bg);}
		.wa-sidebar{width:280px;border-right:1px solid var(--border-color);display:flex;flex-direction:column;}
		.wa-search{padding:8px;border-bottom:1px solid var(--border-color);}
		.wa-conv-list{overflow-y:auto;flex:1;}
		.wa-conv{padding:10px 12px;cursor:pointer;border-bottom:1px solid var(--border-color);}
		.wa-conv:hover{background:var(--bg-light-gray);}
		.wa-conv.active{background:var(--bg-blue);}
		.wa-conv .wa-name{font-weight:600;font-size:var(--text-md);display:flex;align-items:center;justify-content:space-between;gap:6px;}
		.wa-conv .wa-name span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
		.wa-badge{flex:none;background:var(--primary);color:#fff;border-radius:10px;min-width:18px;height:18px;line-height:18px;text-align:center;font-size:11px;padding:0 5px;}
		.wa-conv.wa-unread .wa-last{color:var(--text-color);font-weight:600;}
		.wa-conv .wa-last{color:var(--text-muted);font-size:var(--text-sm);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
		.wa-thread-wrap{flex:1;display:flex;flex-direction:column;min-width:0;position:relative;}
		.wa-thread-header{padding:12px;border-bottom:1px solid var(--border-color);font-weight:600;}
		.wa-thread{flex:1;overflow-y:auto;padding:12px 16px;background:var(--bg-gray);display:flex;flex-direction:column;gap:3px;position:relative;}
		.wa-new-divider{align-self:stretch;display:flex;align-items:center;gap:8px;margin:8px 0;color:var(--red-500,#e24c4c);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;}
		.wa-new-divider::before,.wa-new-divider::after{content:"";flex:1;height:1px;background:var(--red-500,#e24c4c);opacity:.5;}
		.wa-scroll-fab{position:absolute;right:16px;bottom:80px;z-index:5;width:40px;height:40px;border-radius:50%;background:var(--card-bg);border:1px solid var(--border-color);box-shadow:0 2px 8px rgba(0,0,0,.25);cursor:pointer;display:none;align-items:center;justify-content:center;font-size:18px;color:var(--text-color);}
		.wa-scroll-fab:hover{background:var(--bg-light-gray);}
		.wa-scroll-fab.show{display:flex;}
		.wa-scroll-fab .wa-fab-badge{position:absolute;top:-6px;right:-6px;min-width:18px;height:18px;padding:0 5px;border-radius:9px;background:var(--red-500,#e24c4c);color:#fff;font-size:10px;line-height:18px;text-align:center;font-weight:600;}
		.wa-bubble{position:relative;width:fit-content;max-width:65%;padding:5px 9px 3px;border-radius:8px;font-size:13px;line-height:1.35;text-align:left;word-break:break-word;}
		.wa-body{white-space:pre-wrap;}
		.wa-in{align-self:flex-start;background:var(--card-bg);border:1px solid var(--border-color);}
		.wa-out{align-self:flex-end;background:#d9fdd3;color:#111;}
		.wa-meta{font-size:10px;color:var(--text-muted);margin-top:1px;text-align:right;opacity:.7;}
		.wa-media .chat-img,.wa-media .chat-img img{max-width:220px;}
		.wa-media video{max-width:240px;border-radius:6px;display:block;}
		.wa-media audio{max-width:240px;display:block;}
		.wa-media.wa-sticker img{max-width:130px;}
		.wa-doc{display:inline-flex;align-items:center;gap:6px;color:inherit;text-decoration:underline;}
		.wa-caption{white-space:pre-wrap;margin-top:4px;}
		.wa-quote{border-left:3px solid var(--primary);padding:2px 6px;margin-bottom:4px;background:rgba(0,0,0,.05);border-radius:4px;font-size:11px;opacity:.85;}
		.wa-quote .wa-quote-author{font-weight:600;}
		.wa-bubble-failed{border:1px solid #e24c4c;}
		.wa-fail{margin-top:4px;font-size:11px;color:#c0392b;background:rgba(226,76,76,.08);border-radius:4px;padding:3px 6px;white-space:pre-wrap;}
		.wa-resend{display:inline-block;margin-left:6px;cursor:pointer;font-weight:600;color:#c0392b;text-decoration:underline;white-space:nowrap;}
		.wa-resend:hover{color:#e24c4c;}
		.wa-reactions{position:absolute;bottom:-11px;right:6px;display:flex;gap:2px;}
		.wa-react-badge{background:var(--card-bg);border:1px solid var(--border-color);border-radius:10px;padding:0 4px;font-size:11px;line-height:16px;box-shadow:0 1px 2px rgba(0,0,0,.15);}
		.wa-bubble-actions{position:absolute;top:-10px;display:none;gap:2px;}
		.wa-in .wa-bubble-actions{right:4px;}
		.wa-out .wa-bubble-actions{left:4px;}
		.wa-bubble:hover .wa-bubble-actions{display:flex;}
		.wa-act{cursor:pointer;background:var(--card-bg);border:1px solid var(--border-color);border-radius:50%;width:22px;height:22px;line-height:20px;text-align:center;font-size:12px;}
		.wa-act:hover{background:var(--bg-light-gray);}
		.wa-react-pop{position:absolute;z-index:10;background:var(--card-bg);border:1px solid var(--border-color);border-radius:16px;padding:3px 6px;display:flex;gap:4px;box-shadow:0 2px 8px rgba(0,0,0,.2);}
		.wa-react-pop span{cursor:pointer;font-size:16px;}
		.wa-react-pop span:hover{transform:scale(1.25);}
		.wa-emoji-pop{position:absolute;z-index:20;background:var(--card-bg);border:1px solid var(--border-color);border-radius:8px;padding:6px;display:grid;grid-template-columns:repeat(6,1fr);gap:2px;box-shadow:0 2px 8px rgba(0,0,0,.2);}
		.wa-emoji-pop span{cursor:pointer;font-size:18px;padding:2px;text-align:center;border-radius:4px;}
		.wa-emoji-pop span:hover{background:var(--bg-light-gray);}
		.wa-reply-bar{display:flex;align-items:center;justify-content:space-between;padding:6px 10px;border-top:1px solid var(--border-color);background:var(--bg-light-gray);font-size:12px;}
		.wa-reply-bar-text{border-left:3px solid var(--primary);padding-left:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;}
		.wa-reply-cancel{cursor:pointer;color:var(--text-muted);margin-left:8px;font-size:16px;}
		.wa-reply-cancel:hover{color:var(--red-500);}
		.wa-compose{display:flex;gap:6px;padding:10px;border-top:1px solid var(--border-color);align-items:flex-end;}
		.wa-compose textarea{resize:none;flex:1;}
		.wa-attach,.wa-emoji{flex:none;}
		.wa-context{width:280px;border-left:1px solid var(--border-color);overflow-y:auto;padding:12px;}
		.wa-context h6{margin:12px 0 6px;font-size:var(--text-sm);text-transform:uppercase;color:var(--text-muted);letter-spacing:.04em;}
		.wa-ent{display:flex;align-items:center;justify-content:space-between;padding:5px 8px;border:1px solid var(--border-color);border-radius:6px;margin-bottom:5px;font-size:var(--text-sm);}
		.wa-ent .wa-ent-main{cursor:pointer;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
		.wa-ent .wa-ent-main:hover{color:var(--primary);}
		.wa-ent .wa-ent-dt{color:var(--text-muted);font-size:10px;}
		.wa-ent .wa-unlink{cursor:pointer;color:var(--text-muted);margin-left:6px;}
		.wa-ent .wa-unlink:hover{color:var(--red-500);}
		.wa-context-actions{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;}
		.wa-thread-header .wa-header-title{cursor:pointer;}
		.wa-thread-header .wa-header-title:hover{text-decoration:underline;}
		`;
		$(`<style id="wa-chat-styles-v6">${css}</style>`).appendTo(document.head);
	}

	async load_account() {
		const r = await frappe.db.get_list("WhatsApp Account", {
			filters: { is_default_outgoing: 1 },
			fields: ["name"],
			limit: 1,
		});
		if (r.length) this.account = r[0].name;
	}

	async load_managers() {
		try {
			const managers = await frappe.xcall(
				"erpnext.crm.page.whatsapp_chat.whatsapp_chat.get_managers"
			);
			for (const m of managers) {
				this.$manager.append(
					`<option value="${frappe.utils.escape_html(m.name)}">${frappe.utils.escape_html(
						m.full_name || m.name
					)}</option>`
				);
			}
		} catch (e) {
			// non-fatal
		}
	}

	async apply_manager_filter() {
		this.manager = this.$manager.val() || null;
		await this.refresh(true);
	}

	// Reload the conversation list (cheap — one row per dialog) and top up the open
	// thread with whatever arrived since its newest loaded message. Message history
	// itself is never bulk-loaded; see load_page / load_older.
	async refresh(silent) {
		const chats = await frappe.xcall(
			"erpnext.crm.page.whatsapp_chat.whatsapp_chat.get_chats",
			{ manager: this.manager || null }
		);

		const next = {};
		for (const c of chats) {
			const prev = this.conversations[c.phone] || {};
			next[c.phone] = {
				number: c.phone,
				name: c.title || prev.name || c.phone,
				preview: c.preview,
				preview_content_type: c.preview_content_type,
				last_message_on: c.last_message_on,
				// Server-derived message count (reflects this user's read cursor). Progressive
				// read-on-scroll advances that cursor, so the open conversation shows however
				// many messages still sit below the fold — no longer forced to 0.
				unread: c.unread || 0,
				my_last_read: c.my_last_read || prev.my_last_read || null,
				muted: c.muted || 0,
				messages: prev.messages || [],
				all_loaded: !!prev.all_loaded,
			};
		}
		// Keep an open but empty conversation (new chat / deep-link to a number with no
		// messages yet) alive across the rebuild above so it doesn't vanish on poll.
		if (this.active && !next[this.active]) {
			next[this.active] = this.conversations[this.active] || {
				number: this.active,
				name: this.active,
				messages: [],
			};
		}
		this.conversations = next;
		this.render_list();

		if (this.active) await this.load_new(!silent);

		if (this.pending_open) {
			const p = this.ensure_conv(this.pending_open);
			this.pending_open = null;
			if (p) this.open(p);
		}
	}

	// Newest page of history for the open conversation.
	async load_page() {
		const c = this.conversations[this.active];
		if (!c) return;
		const msgs = await frappe.xcall(
			"erpnext.crm.page.whatsapp_chat.whatsapp_chat.get_messages",
			{ phone: this.active, limit: PAGE_SIZE }
		);
		c.messages = msgs;
		c.all_loaded = msgs.length < PAGE_SIZE;
		// Anchor the "New messages" divider once per open, then land on the first unread
		// message (or the bottom when nothing is unread) and reconcile the read cursor.
		this.new_divider_before = this.first_unread_name();
		this.render_thread(false);
		this.scroll_to_start();
	}

	// Name of the first message the current user hasn't read yet (incoming, non-reaction).
	// Null when the conversation is fully read.
	first_unread_name() {
		const c = this.conversations[this.active];
		if (!c) return null;
		const cursor = this.read_cursor;
		const m = (c.messages || []).find(
			(x) =>
				x.type === "Incoming" &&
				x.content_type !== "reaction" &&
				(!cursor || x.creation > cursor)
		);
		return m ? m.name : null;
	}

	// On open: land on the first unread message (divider just above) if any, else the bottom.
	scroll_to_start() {
		const divider = this.$thread.find(".wa-new-divider")[0];
		if (divider) {
			this.$thread.scrollTop(Math.max(0, divider.offsetTop - 60));
		} else {
			this.$thread.scrollTop(this.$thread[0].scrollHeight);
		}
		this.update_read_progress();
		this.update_fab();
	}

	// Older page, prepended; keeps the viewport anchored where the user was reading.
	async load_older() {
		const c = this.conversations[this.active];
		if (!c || this.loading_older || c.all_loaded || !c.messages.length) return;
		this.loading_older = true;
		try {
			const older = await frappe.xcall(
				"erpnext.crm.page.whatsapp_chat.whatsapp_chat.get_messages",
				{ phone: this.active, before: c.messages[0].creation, limit: PAGE_SIZE }
			);
			if (older.length < PAGE_SIZE) c.all_loaded = true;
			if (older.length) {
				const prev_h = this.$thread[0].scrollHeight;
				c.messages = older.concat(c.messages);
				this.render_thread(false);
				const new_h = this.$thread[0].scrollHeight;
				console.log("[chat] load_older: restoring scroll", {
					older_count: older.length,
					prev_h,
					new_h,
					new_scrollTop: new_h - prev_h,
				});
				this.$thread.scrollTop(new_h - prev_h);
			}
		} finally {
			this.loading_older = false;
		}
	}

	// Messages that arrived since the newest one we hold (realtime / poll).
	async load_new(force_scroll) {
		const c = this.conversations[this.active];
		if (!c) return;
		if (!c.messages.length) return this.load_page();

		const el = this.$thread[0];
		const at_bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
		console.log("[chat] load_new: before fetch", {
			scrollTop: el.scrollTop,
			scrollHeight: el.scrollHeight,
			clientHeight: el.clientHeight,
			dist_from_bottom: el.scrollHeight - el.scrollTop - el.clientHeight,
			at_bottom,
		});
		// Re-read the recent tail rather than only what is strictly newer: outgoing
		// rows change status (sent → delivered → failed) after they were loaded.
		const tail = c.messages.slice(-STATUS_TAIL);
		const fresh = await frappe.xcall(
			"erpnext.crm.page.whatsapp_chat.whatsapp_chat.get_messages",
			{ phone: this.active, after: tail[0].creation, limit: 200 }
		);
		const index = {};
		c.messages.forEach((m, i) => (index[m.name] = i));
		let changed = false;
		for (const m of fresh) {
			if (index[m.name] === undefined) {
				c.messages.push(m);
				index[m.name] = c.messages.length - 1;
				changed = true;
			} else {
				const old = c.messages[index[m.name]];
				if (old.status !== m.status || old.message !== m.message || old.attach !== m.attach) {
					c.messages[index[m.name]] = m;
					changed = true;
				}
			}
		}
		if (changed || force_scroll) this.render_thread(force_scroll || at_bottom);
		if (changed) {
			// At the bottom → new arrivals are read as they land; scrolled up → they stay
			// unread and just bump the badge + FAB counter.
			if (force_scroll || at_bottom) this.update_read_progress();
			else this.recount_unread(this.active);
			this.update_fab();
		}
	}

	// Advance the read cursor for a conversation. `upto` (a message creation timestamp) marks
	// read only that far; omit it to mark the whole conversation read.
	async mark_read(number, upto) {
		if (!number) return;
		const c = this.conversations[number];
		try {
			const res = await frappe.xcall(
				"erpnext.crm.page.whatsapp_chat.whatsapp_chat.mark_read",
				{ phone: number, upto: upto || null }
			);
			const cursor = (res && res.last_read_on) || upto || frappe.datetime.now_datetime();
			if (c) c.my_last_read = cursor;
			if (number === this.active) this.read_cursor = cursor;
			this.recount_unread(number);
		} catch (e) {
			// non-fatal — the badge simply reappears on the next poll
		}
	}

	// Recompute a conversation's unread badge from the local read cursor.
	recount_unread(number) {
		const c = this.conversations[number];
		if (!c) return;
		if (number === this.active) {
			const cursor = this.read_cursor;
			c.unread = (c.messages || []).filter(
				(m) =>
					m.type === "Incoming" &&
					m.content_type !== "reaction" &&
					(!cursor || m.creation > cursor)
			).length;
		}
		this.render_list();
	}

	// Progressive read-on-scroll: any unread incoming message whose top has scrolled into the
	// viewport counts as seen. Advance the cursor to the newest such message (never backwards),
	// debounced so a scroll gesture makes at most one server call.
	update_read_progress() {
		if (!this.active) return;
		const el = this.$thread[0];
		if (!el) return;
		const bottom_edge = el.scrollTop + el.clientHeight;
		let newest = this.read_cursor || "";
		this.$thread.find(".wa-bubble").each((_, b) => {
			const m = $(b).data("msg");
			if (!m || m.type !== "Incoming" || m.content_type === "reaction") return;
			if (b.offsetTop < bottom_edge && m.creation > newest) newest = m.creation;
		});
		if (newest && newest > (this.read_cursor || "")) {
			this.read_cursor = newest;
			this.recount_unread(this.active);
			clearTimeout(this._read_timer);
			const upto = newest;
			this._read_timer = setTimeout(() => this.mark_read(this.active, upto), 350);
		}
	}

	// Show the scroll-to-latest button when the user is away from the bottom; badge it with
	// how many messages still sit below the fold unread.
	update_fab() {
		if (!this.$fab) return;
		const el = this.$thread[0];
		if (!el || !this.active) return this.$fab.removeClass("show");
		const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
		this.$fab.toggleClass("show", dist > 120);
		const c = this.conversations[this.active];
		const n = (c && c.unread) || 0;
		this.$fab.find(".wa-fab-badge").toggle(n > 0).text(n > 99 ? "99+" : n);
	}

	// FAB / "mark all read": jump to the newest message and clear the conversation's unread.
	jump_to_latest() {
		this.$thread.scrollTop(this.$thread[0].scrollHeight);
		this.mark_read(this.active);
		this.update_fab();
	}

	// Normalize to a digits-only number and make sure a conversation entry exists.
	ensure_conv(raw) {
		const number = String(raw || "").replace(/\D/g, "");
		if (!number) return null;
		if (!this.conversations[number]) {
			this.conversations[number] = { number, name: number, messages: [] };
		}
		return number;
	}

	// Open (or create) a conversation for an arbitrary number, e.g. from the New chat button.
	open_new(raw) {
		const number = this.ensure_conv(raw);
		if (!number) return;
		this.render_list();
		this.open(number);
	}

	new_chat_prompt() {
		frappe.prompt(
			[{ fieldname: "phone", fieldtype: "Data", label: __("Phone number"), reqd: 1,
				description: __("Include country code, e.g. 380XXXXXXXXX") }],
			({ phone }) => this.open_new(phone),
			__("New chat"),
			__("Start")
		);
	}

	render_list() {
		const q = (this.$search.val() || "").toLowerCase();
		let convs = Object.values(this.conversations);
		convs = convs
			.filter((c) => !q || c.number.toLowerCase().includes(q) || (c.name || "").toLowerCase().includes(q))
			.sort((a, b) => (b.last_message_on || "").localeCompare(a.last_message_on || ""));

		this.$list.empty();
		if (!convs.length) {
			this.$list.html(`<div class="text-muted" style="padding:12px;">${__("No conversations yet")}</div>`);
			return;
		}
		for (const c of convs) {
			const preview = frappe.utils
				.escape_html(
					this.preview_text({ content_type: c.preview_content_type, message: c.preview })
				)
				.slice(0, 40);
			const badge = c.unread
				? `<span class="wa-badge">${c.unread > 99 ? "99+" : c.unread}</span>`
				: "";
			const $el = $(`
				<div class="wa-conv ${c.number === this.active ? "active" : ""} ${c.unread ? "wa-unread" : ""}">
					<div class="wa-name"><span>${frappe.utils.escape_html(c.name)}</span>${badge}</div>
					<div class="wa-last">${preview}</div>
				</div>
			`);
			$el.on("click", () => this.open(c.number));
			this.$list.append($el);
		}
	}

	open(number) {
		this.active = number;
		this.set_reply(null);
		const c = this.conversations[number];
		// My read cursor at open time — drives the divider and first-unread scroll. load_page
		// takes over read tracking from here (progressive on scroll), so no blanket mark_read.
		this.read_cursor = (c && c.my_last_read) || null;
		this.render_list();
		this.$thread.empty();
		this.$compose.show();
		this.render_header(number);
		this.load_context(number);
		this.load_page();
	}

	// Short one-line description of a message for the conversation list.
	preview_text(m) {
		if (!m) return "";
		if (m.content_type === "reaction") return `${m.message || ""} ${__("reacted")}`.trim();
		if (MEDIA_TYPES.includes(m.content_type)) {
			const label = media_label(m.content_type) || "";
			const cap = (m.message || "").replace(/<[^>]*>/g, "").trim();
			return cap ? `${label}: ${cap}` : label;
		}
		return (m.message || "").replace(/<[^>]*>/g, "");
	}

	// The media / text body HTML for a bubble.
	render_body(m) {
		const ct = m.content_type;
		const caption = (m.message || "").replace(/<[^>]*>/g, "");
		const cap_html = caption ? `<div class="wa-caption">${frappe.utils.escape_html(caption)}</div>` : "";

		if (MEDIA_TYPES.includes(ct) && m.attach) {
			const url = frappe.utils.escape_html(m.attach);
			if (ct === "image" || ct === "sticker") {
				const cls = ct === "sticker" ? "wa-media wa-sticker" : "wa-media";
				const img = erpnext.chat_media.image_html(
					m.attach,
					ct === "sticker" ? "chat-img-sticker" : ""
				);
				return `<div class="${cls}">${img}</div>${ct === "sticker" ? "" : cap_html}`;
			}
			if (ct === "video") return `<div class="wa-media"><video controls src="${url}"></video></div>${cap_html}`;
			if (ct === "audio") return `<div class="wa-media"><audio controls src="${url}"></audio></div>${cap_html}`;
			if (ct === "document") {
				const fname = frappe.utils.escape_html(decodeURIComponent(m.attach.split("/").pop() || __("Document")));
				return `<a class="wa-doc" href="${url}" target="_blank" download>📎 ${fname}</a>${cap_html}`;
			}
		}
		// Unresolved media (attach missing) or text.
		if (MEDIA_TYPES.includes(ct)) return `<i>${frappe.utils.escape_html(media_label(ct) || __("Media"))}</i>${cap_html}`;
		return caption
			? `<span class="wa-body">${frappe.utils.escape_html(caption)}</span>`
			: `<i>(${__("no text")})</i>`;
	}

	render_thread(scroll) {
		const c = this.conversations[this.active];
		if (!c) return;
		this.$thread.empty();

		// Index messages by whatsapp message_id and collect reactions by target.
		this.msg_by_id = {};
		const reactions = {}; // target message_id -> [emoji, ...]
		for (const m of c.messages) {
			if (m.message_id) this.msg_by_id[m.message_id] = m;
		}
		for (const m of c.messages) {
			if (m.content_type === "reaction" && m.reply_to_message_id && m.message) {
				(reactions[m.reply_to_message_id] = reactions[m.reply_to_message_id] || []).push(m.message);
			}
		}

		const sys_tz = frappe.sys_defaults.time_zone || "UTC";
		for (const m of c.messages) {
			if (m.content_type === "reaction") continue; // rendered as badges, not bubbles
			// "New messages" divider, anchored at the first message that was unread on open.
			if (this.new_divider_before && m.name === this.new_divider_before) {
				this.$thread.append(`<div class="wa-new-divider">${__("New messages")}</div>`);
			}
			const out = m.type === "Outgoing";
			const time = moment.tz(m.creation, sys_tz).local().format("HH:mm");
			const failed = out && (m.status || "").toLowerCase() === "failed";
			const status = out ? ` · ${frappe.utils.escape_html(m.status || "")}` : "";

			// Failure notice + Resend for outgoing messages Meta rejected.
			let fail_html = "";
			if (failed && m.content_type !== "reaction") {
				const reason = frappe.utils.escape_html(m.status_error || __("Message failed to send"));
				fail_html = `<div class="wa-fail">⚠ ${reason}
					<span class="wa-resend" title="${__("Resend")}">↻ ${__("Resend")}</span></div>`;
			}

			// Reply quote.
			let quote = "";
			if (m.is_reply && m.reply_to_message_id && this.msg_by_id[m.reply_to_message_id]) {
				const tgt = this.msg_by_id[m.reply_to_message_id];
				const author = tgt.type === "Outgoing" ? __("You") : (c.name || tgt.from || "");
				quote = `<div class="wa-quote"><div class="wa-quote-author">${frappe.utils.escape_html(
					author
				)}</div>${frappe.utils.escape_html(this.preview_text(tgt).slice(0, 80))}</div>`;
			}

			// Reaction badges.
			const rs = m.message_id ? reactions[m.message_id] : null;
			const react_html = rs
				? `<div class="wa-reactions">${rs
						.map((e) => `<span class="wa-react-badge">${frappe.utils.escape_html(e)}</span>`)
						.join("")}</div>`
				: "";

			// Hover actions (react needs a message_id to target).
			const react_btn = m.message_id ? `<span class="wa-act wa-do-react" title="${__("React")}">😊</span>` : "";
			const actions = `<div class="wa-bubble-actions">${react_btn}<span class="wa-act wa-do-reply" title="${__(
				"Reply"
			)}">↩</span></div>`;

			const $b = $(
				`<div class="wa-bubble ${out ? "wa-out" : "wa-in"}" data-mid="${frappe.utils.escape_html(
					m.message_id || ""
				)} ${failed ? "wa-bubble-failed" : ""}">${actions}${quote}${this.render_body(m)}<div class="wa-meta">${time}${status}</div>${fail_html}${react_html}</div>`
			);
			$b.data("msg", m);
			this.$thread.append($b);
		}

		erpnext.chat_media.bind(this.$thread, "whatsapp");
		this.$thread.find(".wa-do-reply").on("click", (e) => {
			const m = $(e.currentTarget).closest(".wa-bubble").data("msg");
			this.set_reply({ message_id: m.message_id, preview: this.preview_text(m) });
		});
		this.$thread.find(".wa-do-react").on("click", (e) => this.react_popover(e));
		this.$thread.find(".wa-resend").on("click", (e) => {
			const m = $(e.currentTarget).closest(".wa-bubble").data("msg");
			this.resend(m);
		});

		console.log("[chat] render_thread", {
			scroll: !!scroll,
			msg_count: c.messages.length,
			scrollHeight: this.$thread[0].scrollHeight,
		});
		if (scroll) this.$thread.scrollTop(this.$thread[0].scrollHeight);
	}

	// Re-send a message that Meta rejected, as a fresh outgoing message.
	async resend(m) {
		if (!m || !this.active) return;
		frappe.dom.freeze(__("Resending..."));
		try {
			if (MEDIA_TYPES.includes(m.content_type) && m.attach) {
				await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.send_media", {
					phone: this.active,
					attach: m.attach,
					content_type: m.content_type,
					caption: (m.message || "").replace(/<[^>]*>/g, "").trim(),
				});
			} else {
				const text = (m.message || "").replace(/<[^>]*>/g, "").trim();
				if (!text) {
					frappe.msgprint(__("Nothing to resend"));
					return;
				}
				await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.send_text", {
					phone: this.active,
					message: text,
				});
			}
			await this.refresh();
			this.render_thread(true);
		} catch (e) {
			frappe.msgprint(__("Failed to resend"));
		} finally {
			frappe.dom.unfreeze();
		}
	}

	set_reply(reply) {
		this.reply_to = reply;
		if (reply) {
			this.$replyBar.find(".wa-reply-bar-text").text(`${__("Replying to")}: ${reply.preview.slice(0, 60)}`);
			this.$replyBar.show();
			this.$input.focus();
		} else {
			this.$replyBar.hide();
		}
	}

	react_popover(e) {
		e.stopPropagation();
		this.page.main.find(".wa-react-pop").remove();
		const m = $(e.currentTarget).closest(".wa-bubble").data("msg");
		const $pop = $(
			`<div class="wa-react-pop">${QUICK_REACTIONS.map(
				(x) => `<span data-e="${x}">${x}</span>`
			).join("")}</div>`
		);
		$("body").append($pop);
		const off = $(e.currentTarget).offset();
		$pop.css({ top: off.top - 40, left: off.left });
		$pop.find("span").on("click", async (ev) => {
			const emoji = $(ev.currentTarget).data("e");
			$pop.remove();
			await this.send_reaction(m.message_id, emoji);
		});
		setTimeout(() => $(document).one("click", () => $pop.remove()), 0);
	}

	async send_reaction(message_id, emoji) {
		try {
			await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.send_reaction", {
				phone: this.active,
				message_id,
				emoji,
			});
			await this.refresh();
			this.render_thread(true);
		} catch (err) {
			frappe.msgprint(__("Failed to send reaction"));
		}
	}

	attach_media() {
		if (!this.active) return;
		new frappe.ui.FileUploader({
			folder: "Home/Attachments",
			on_success: async (file) => {
				const content_type = mime_to_content_type(
					file.file_type || file.type,
					file.file_name || file.file_url
				);
				frappe.dom.freeze(__("Sending..."));
				try {
					await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.send_media", {
						phone: this.active,
						attach: file.file_url,
						content_type,
						caption: (this.$input.val() || "").trim(),
						reply_to_message_id: this.reply_to ? this.reply_to.message_id : null,
					});
					this.$input.val("");
					this.set_reply(null);
					await this.refresh();
					this.render_thread(true);
				} catch (err) {
					frappe.msgprint(__("Failed to send media"));
				} finally {
					frappe.dom.unfreeze();
				}
			},
		});
	}

	emoji_picker(e) {
		e.stopPropagation();
		$(".wa-emoji-pop").remove();
		const $pop = $(
			`<div class="wa-emoji-pop">${EMOJI_SET.map((x) => `<span>${x}</span>`).join("")}</div>`
		);
		$("body").append($pop);
		const off = $(e.currentTarget).offset();
		$pop.css({ top: off.top - 160, left: off.left });
		$pop.find("span").on("click", (ev) => {
			const el = this.$input[0];
			const emoji = $(ev.currentTarget).text();
			const start = el.selectionStart || 0;
			const val = this.$input.val();
			this.$input.val(val.slice(0, start) + emoji + val.slice(el.selectionEnd || start));
			$pop.remove();
			el.focus();
			el.selectionStart = el.selectionEnd = start + emoji.length;
		});
		setTimeout(() => $(document).one("click", () => $pop.remove()), 0);
	}

	// Send an approved template — the only way to message a number outside Meta's 24h
	// customer-service window (free text/media get rejected with error 131047).
	async template_dialog() {
		if (!this.active) return;
		let templates;
		try {
			templates = await frappe.xcall(
				"erpnext.crm.page.whatsapp_chat.whatsapp_chat.list_templates"
			);
		} catch (e) {
			frappe.msgprint(__("Could not load templates"));
			return;
		}
		if (!templates || !templates.length) {
			frappe.msgprint(
				__("No approved templates found. Create and sync a WhatsApp Template first.")
			);
			return;
		}

		if (!templates.length) {
			frappe.msgprint(__("No approved templates found. Create and sync a WhatsApp Template first."));
			return;
		}
		const by_name = {};
		templates.forEach((t) => (by_name[t.name] = t));

		// Step 1: pick the template. Plain-string options so the selected docname is
		// returned verbatim (object {value,label} options don't bind in frappe.prompt).
		frappe.prompt(
			[
				{
					fieldname: "template",
					label: __("Template"),
					fieldtype: "Select",
					reqd: 1,
					options: templates.map((t) => t.name).join("\n"),
					default: templates[0].name,
				},
			],
			({ template }) => {
				const t = by_name[template];
				if (t && (t.params || []).length) {
					// Step 2: fill the template's body placeholders.
					frappe.prompt(
						t.params.map((p, i) => ({
							fieldname: `param_${i}`,
							label: p,
							fieldtype: "Data",
							reqd: 1,
						})),
						(vals) => {
							const body = {};
							t.params.forEach((p, i) => (body[p] = vals[`param_${i}`]));
							this._send_template(template, body);
						},
						__("Template parameters"),
						__("Send")
					);
				} else {
					this._send_template(template, null);
				}
			},
			__("Send template"),
			__("Next")
		);
	}

	async _send_template(template, body_params) {
		frappe.dom.freeze(__("Sending..."));
		try {
			await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.send_template", {
				phone: this.active,
				template,
				body_params: body_params ? JSON.stringify(body_params) : null,
			});
			await this.refresh();
			this.render_thread(true);
		} catch (e) {
			frappe.msgprint(__("Failed to send template"));
		} finally {
			frappe.dom.unfreeze();
		}
	}

	// Header: the title opens the chat overview, the bell mutes the conversation.
	render_header(number) {
		const c = this.conversations[number] || { number, name: number };
		this.$header.html(
			`<span class="wa-header-title"></span>${erpnext.chat_sound.button_html(c.muted)}`
		);
		this.$header
			.find(".wa-header-title")
			.text(c.name === number ? number : `${c.name} · ${number}`)
			.attr("title", __("Chat info"))
			.on("click", () => this.show_info());
		this.$header.find(".chat-mute-btn").on("click", () => this.toggle_mute(number));
	}

	async toggle_mute(number) {
		const c = this.conversations[number];
		if (!c) return;
		const muted = c.muted ? 0 : 1;
		c.muted = muted;
		this.render_header(number);
		try {
			await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.set_muted", {
				phone: number,
				muted,
			});
		} catch (e) {
			c.muted = muted ? 0 : 1;
			this.render_header(number);
		}
		frappe.show_alert({
			message: muted ? __("Chat muted") : __("Chat unmuted"),
			indicator: "blue",
		});
	}

	// --- chat overview -----------------------------------------------------

	async show_info() {
		if (!this.active) return;
		console.log("[chat] page show_info (conversation name pressed)", { phone: this.active });
		const info = await frappe.xcall(
			"erpnext.crm.page.whatsapp_chat.whatsapp_chat.get_chat_overview",
			{ phone: this.active }
		);

		const media = info.media.map((m) => ({
			sender_name: m.sender_name,
			creation: m.creation,
			caption: m.caption,
			html:
				m.content_type === "image" || m.content_type === "sticker"
					? erpnext.chat_media.image_html(m.attach)
					: null,
			icon: m.content_type === "video" ? "🎬" : "🎵",
			on_click:
				m.content_type === "image" || m.content_type === "sticker"
					? null
					: () => window.open(m.attach, "_blank"),
		}));

		const files = info.files.map((f) => ({
			file_name: f.file_name,
			file_size: f.file_size,
			sender_name: f.sender_name,
			creation: f.creation,
			url: f.attach,
		}));

		const people = [
			{
				name: info.title,
				subtitle: info.phone,
				user: info.phone,
			},
		];
		if (info.contact) {
			people.push({
				name: info.contact,
				subtitle: __("Contact"),
			});
		}
		for (const m of info.managers || []) {
			people.push({ name: m.full_name || m.user, subtitle: __("Manager") });
		}

		const to_items = (rows) =>
			(rows || []).map((e) => ({
				title: e.label || e.name,
				subtitle: e.doctype,
				on_click: () => frappe.set_route("Form", e.doctype, e.name),
			}));

		const dialog = erpnext.chat_info.show({
			title: info.title,
			subtitle: info.phone,
			actions: [
				{
					label: info.muted ? __("Unmute chat") : __("Mute chat"),
					on_click: async () => {
						await this.toggle_mute(this.active);
						dialog.hide();
					},
				},
			],
			source: "whatsapp",
			people,
			media,
			files,
			links: info.links,
			sections: [
				{ label: __("Linked"), items: to_items(info.linked) },
				{ label: __("Derived"), items: to_items(info.derived) },
			],
		});
	}

	async load_context(number) {
		this.$context.html(`<div class="text-muted">${__("Loading...")}</div>`);
		try {
			this.context = await frappe.xcall(
				"erpnext.crm.page.whatsapp_chat.whatsapp_chat.get_chat_context",
				{ phone: number }
			);
		} catch (e) {
			this.$context.html(`<div class="text-muted">${__("Could not load context")}</div>`);
			return;
		}
		this.render_context(number);
	}

	render_context(number) {
		const ctx = this.context || { linked: [], derived: [], managers: [] };
		const ent = (e, removable) => {
			const unlink = removable
				? `<span class="wa-unlink" title="${__("Unlink")}">&times;</span>`
				: "";
			return `<div class="wa-ent" data-dt="${frappe.utils.escape_html(e.doctype)}" data-nm="${frappe.utils.escape_html(e.name)}">
				<span class="wa-ent-main">${frappe.utils.escape_html(e.label)}<div class="wa-ent-dt">${frappe.utils.escape_html(e.doctype)}</div></span>${unlink}
			</div>`;
		};

		const linked = (ctx.linked || []).map((e) => ent(e, true)).join("") ||
			`<div class="text-muted" style="font-size:var(--text-sm);">${__("None")}</div>`;
		const derived = (ctx.derived || []).map((e) => ent(e, false)).join("");
		const managerNames = (ctx.managers || []).map((m) => frappe.utils.escape_html(m.full_name || m.user)).join(", ");

		this.$context.html(`
			<div class="wa-context-actions">
				<button class="btn btn-xs btn-default wa-link-btn">${__("Link Document")}</button>
				<button class="btn btn-xs btn-default wa-managers-btn">${__("Managers")}</button>
			</div>
			<h6>${__("Create from Chat")}</h6>
			<div class="wa-context-actions">
				<button class="btn btn-xs btn-default wa-new-opp">${__("Opportunity")}</button>
				<button class="btn btn-xs btn-default wa-new-todo">${__("Task")}</button>
				<button class="btn btn-xs btn-default wa-new-note">${__("Note")}</button>
				<button class="btn btn-xs btn-default wa-new-event">${__("Event")}</button>
			</div>
			<h6>${__("Linked Documents")}</h6>
			<div class="wa-linked">${linked}</div>
			${derived ? `<h6>${__("Related (by contact)")}</h6><div class="wa-derived">${derived}</div>` : ""}
			<h6>${__("Assigned Managers")}</h6>
			<div class="text-muted" style="font-size:var(--text-sm);">${managerNames || __("None")}</div>
		`);

		this.$context.find(".wa-ent-main").on("click", (e) => {
			const $c = $(e.currentTarget).closest(".wa-ent");
			frappe.set_route("Form", $c.data("dt"), $c.data("nm"));
		});
		this.$context.find(".wa-unlink").on("click", async (e) => {
			const $c = $(e.currentTarget).closest(".wa-ent");
			this.context = await frappe.xcall(
				"erpnext.crm.page.whatsapp_chat.whatsapp_chat.unlink_entity",
				{ phone: number, link_doctype: $c.data("dt"), link_name: $c.data("nm") }
			);
			this.render_context(number);
		});
		this.$context.find(".wa-link-btn").on("click", () => this.link_dialog(number));
		this.$context.find(".wa-managers-btn").on("click", () => this.managers_dialog(number));
		this.$context.find(".wa-new-opp").on("click", () => this.create_opportunity(number));
		this.$context.find(".wa-new-todo").on("click", () => this.create_todo(number));
		this.$context.find(".wa-new-note").on("click", () => this.create_note(number));
		this.$context.find(".wa-new-event").on("click", () => this.create_event(number));
	}

	_goto(res) {
		frappe.show_alert({ message: __("Created {0}", [res.name]), indicator: "green" });
		frappe.set_route("Form", res.doctype, res.name);
	}

	async create_opportunity(number) {
		try {
			const res = await frappe.xcall(
				"erpnext.crm.page.whatsapp_chat.whatsapp_chat.create_opportunity",
				{ phone: number }
			);
			await this.load_context(number);
			this._goto(res);
		} catch (e) {
			// server throw already shown
		}
	}

	create_todo(number) {
		frappe.prompt(
			[{ fieldname: "description", fieldtype: "Small Text", label: __("Task"), reqd: 1 }],
			async (v) => {
				const res = await frappe.xcall(
					"erpnext.crm.page.whatsapp_chat.whatsapp_chat.create_todo",
					{ phone: number, description: v.description }
				);
				this._goto(res);
			},
			__("New Task"),
			__("Create")
		);
	}

	create_note(number) {
		frappe.prompt(
			[
				{ fieldname: "title", fieldtype: "Data", label: __("Title"), reqd: 1 },
				{ fieldname: "content", fieldtype: "Text Editor", label: __("Content") },
			],
			async (v) => {
				const res = await frappe.xcall(
					"erpnext.crm.page.whatsapp_chat.whatsapp_chat.create_note",
					{ phone: number, title: v.title, content: v.content }
				);
				this._goto(res);
			},
			__("New Note"),
			__("Create")
		);
	}

	create_event(number) {
		frappe.prompt(
			[
				{ fieldname: "subject", fieldtype: "Data", label: __("Subject"), reqd: 1 },
				{ fieldname: "starts_on", fieldtype: "Datetime", label: __("Starts On"), reqd: 1 },
			],
			async (v) => {
				const res = await frappe.xcall(
					"erpnext.crm.page.whatsapp_chat.whatsapp_chat.create_event",
					{ phone: number, subject: v.subject, starts_on: v.starts_on }
				);
				this._goto(res);
			},
			__("New Event"),
			__("Create")
		);
	}

	link_dialog(number) {
		const d = new frappe.ui.Dialog({
			title: __("Link Document"),
			fields: [
				{
					fieldname: "link_doctype",
					fieldtype: "Select",
					label: __("Type"),
					options: LINKABLE_DOCTYPES.join("\n"),
					reqd: 1,
				},
				{ fieldname: "link_name", fieldtype: "Dynamic Link", label: __("Document"), options: "link_doctype", reqd: 1 },
			],
			primary_action_label: __("Link"),
			primary_action: async (v) => {
				this.context = await frappe.xcall(
					"erpnext.crm.page.whatsapp_chat.whatsapp_chat.link_entity",
					{ phone: number, link_doctype: v.link_doctype, link_name: v.link_name }
				);
				d.hide();
				this.render_context(number);
			},
		});
		d.show();
	}

	async managers_dialog(number) {
		const managers = await frappe.xcall(
			"erpnext.crm.page.whatsapp_chat.whatsapp_chat.get_managers"
		);
		const current = (this.context?.managers || []).map((m) => m.user);
		const d = new frappe.ui.Dialog({
			title: __("Assigned Managers"),
			fields: [
				{
					fieldname: "users",
					fieldtype: "MultiSelectList",
					label: __("Managers"),
					get_data: () =>
						managers.map((m) => ({ value: m.name, description: m.full_name || m.name })),
				},
			],
			primary_action_label: __("Save"),
			primary_action: async (v) => {
				this.context = await frappe.xcall(
					"erpnext.crm.page.whatsapp_chat.whatsapp_chat.set_managers",
					{ phone: number, users: JSON.stringify(v.users || []) }
				);
				d.hide();
				this.render_context(number);
			},
		});
		d.show();
		d.set_value("users", current);
	}

	async send() {
		const text = (this.$input.val() || "").trim();
		if (!text || !this.active) return;
		this.$input.val("");
		const reply_id = this.reply_to ? this.reply_to.message_id : null;
		this.set_reply(null);
		try {
			await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.send_text", {
				phone: this.active,
				message: text,
				reply_to_message_id: reply_id,
			});
			await this.refresh();
			this.render_thread(true);
		} catch (e) {
			frappe.msgprint(__("Failed to send message"));
			this.$input.val(text);
		}
	}
}
