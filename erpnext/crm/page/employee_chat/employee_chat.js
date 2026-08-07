frappe.pages["employee-chat"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Employee Chat"),
		single_column: true,
	});
	new EmployeeChat(page);
};

const API = "erpnext.crm.page.employee_chat.employee_chat.";

// Emoji shown in the compose picker and (first 6) as quick reactions.
const EMOJI_SET = [
	"👍",
	"❤️",
	"😂",
	"😮",
	"😢",
	"🙏",
	"👏",
	"🔥",
	"🎉",
	"😊",
	"😍",
	"🤔",
	"👌",
	"✅",
	"❌",
	"⚠️",
	"💰",
	"📦",
	"😅",
	"😁",
	"😉",
	"🥳",
	"💪",
	"🚀",
];
const QUICK_REACTIONS = EMOJI_SET.slice(0, 6);

// Links shown in the chat overview. In a secret thread the scan happens here, on the
// decrypted text — the server never sees a body to scan.
const URL_RE = /https?:\/\/[^\s<>"']+/g;

// Chat Message only distinguishes image vs file; everything non-image collapses
// to "file". Detection itself is shared with the WhatsApp Chat Center.
function mime_to_content_type(type, file_name) {
	return erpnext.chat_media.detect_type(type, file_name) === "image" ? "image" : "file";
}

class EmployeeChat {
	constructor(page) {
		this.page = page;
		this.me = frappe.session.user;
		this.active = null; // active thread name
		this.threads = {}; // name -> thread meta
		this.messages = []; // messages of the active thread (oldest-first)
		this.reply_to = null; // {name, text} when composing a reply
		this.other_last_read = null; // other participant's last_read_on (direct threads)
		this.typing_timer = null; // hides the typing indicator
		this.typing_sent_at = 0; // throttle outgoing typing pings

		this.make_layout();
		// deep-link: /app/employee-chat?thread=<name>
		this.pending_open = frappe.utils.get_url_arg("thread");
		this.load_threads();

		// realtime — all events arrive only in our private user room
		this.on_message = (d) => this.on_realtime_message(d);
		this.on_typing = (d) => this.on_realtime_typing(d);
		this.on_seen = (d) => this.on_realtime_seen(d);
		this.on_reaction = (d) => this.on_realtime_reaction(d);
		frappe.realtime.on("chat_message", this.on_message);
		frappe.realtime.on("chat_typing", this.on_typing);
		frappe.realtime.on("chat_seen", this.on_seen);
		frappe.realtime.on("chat_reaction", this.on_reaction);
		// slow poll of the thread list as a safety net if the socket drops
		this.poll = setInterval(() => this.load_threads(), 30000);

		$(this.page.wrapper).on("remove", () => {
			clearInterval(this.poll);
			frappe.realtime.off("chat_message", this.on_message);
			frappe.realtime.off("chat_typing", this.on_typing);
			frappe.realtime.off("chat_seen", this.on_seen);
			frappe.realtime.off("chat_reaction", this.on_reaction);
		});
	}

	make_layout() {
		this.page.main.html(`
			<div class="ec-chat">
				<div class="ec-sidebar">
					<div class="ec-search">
						<button class="btn btn-primary btn-xs ec-new-chat" style="width:100%;margin-bottom:6px;">+ ${__(
							"New chat"
						)}</button>
						<input type="text" class="form-control input-xs ec-search-input" placeholder="${__("Search chats")}">
					</div>
					<div class="ec-thread-list"></div>
				</div>
				<div class="ec-thread-wrap">
					<div class="ec-thread-header text-muted">${__("Select a chat")}</div>
					<div class="ec-thread"></div>
					<div class="ec-scroll-fab" title="${__(
						"Scroll to latest"
					)}">⬇<span class="ec-fab-badge" style="display:none;"></span></div>
					<div class="ec-typing text-muted" style="display:none;"></div>
					<div class="ec-compose-wrap" style="display:none;">
						<div class="ec-reply-bar" style="display:none;">
							<div class="ec-reply-bar-text"></div>
							<span class="ec-reply-cancel" title="${__("Cancel reply")}">&times;</span>
						</div>
						<div class="ec-compose">
							<button class="btn btn-default btn-sm ec-attach" title="${__("Attach file")}">📎</button>
							<button class="btn btn-default btn-sm ec-mic" title="${__("Record voice message")}">🎤</button>
							<button class="btn btn-default btn-sm ec-emoji" title="${__("Add emoji")}">😊</button>
							<textarea class="form-control" rows="1" placeholder="${__("Type a message")}"></textarea>
							<button class="btn btn-primary btn-sm ec-send">${__("Send")}</button>
						</div>
					</div>
				</div>
			</div>
		`);
		this.inject_styles();

		this.$list = this.page.main.find(".ec-thread-list");
		this.$thread = this.page.main.find(".ec-thread");
		this.$header = this.page.main.find(".ec-thread-header");
		this.$typing = this.page.main.find(".ec-typing");
		this.$fab = this.page.main.find(".ec-scroll-fab");
		this.$fab.on("click", () => this.jump_to_latest());
		this.$compose = this.page.main.find(".ec-compose-wrap");
		this.$input = this.page.main.find(".ec-compose textarea");
		this.$replyBar = this.page.main.find(".ec-reply-bar");
		this.$search = this.page.main.find(".ec-search-input");

		this.page.add_menu_item(__("Secret chats"), () => this.secret_settings_dialog());
		this.page.main.find(".ec-new-chat").on("click", () => this.new_chat_dialog());
		this.page.main.find(".ec-send").on("click", () => this.send());
		this.page.main.find(".ec-attach").on("click", (e) => this.attach_menu(e));
		this.page.main.find(".ec-mic").on("click", () => this.record_voice());
		this.page.main.find(".ec-emoji").on("click", (e) => this.emoji_picker(e));
		this.$replyBar.find(".ec-reply-cancel").on("click", () => this.set_reply(null));
		this.$input.on("keydown", (e) => {
			if (e.key === "Enter" && !e.shiftKey) {
				e.preventDefault();
				this.send();
			} else {
				this.notify_typing();
			}
		});
		this.$search.on("input", () => this.render_list());
		this.$thread.on("scroll", () => {
			if (this.$thread.scrollTop() < 40) this.load_older();
			this.update_read_progress();
			this.update_fab();
		});
	}

	inject_styles() {
		erpnext.chat_media.inject_styles();
		erpnext.chat_sound.inject_styles();
		if (document.getElementById("ec-chat-styles-v5")) return;
		const css = `
		.ec-chat{display:flex;height:calc(100vh - 160px);border:1px solid var(--border-color);border-radius:var(--border-radius-md);overflow:hidden;background:var(--card-bg);}
		.ec-sidebar{width:280px;border-right:1px solid var(--border-color);display:flex;flex-direction:column;}
		.ec-search{padding:8px;border-bottom:1px solid var(--border-color);}
		.ec-thread-list{overflow-y:auto;flex:1;}
		.ec-conv{padding:10px 12px;cursor:pointer;border-bottom:1px solid var(--border-color);display:flex;align-items:center;gap:8px;}
		.ec-conv:hover{background:var(--bg-light-gray);}
		.ec-conv.active{background:var(--bg-blue);}
		.ec-avatar{flex:none;width:34px;height:34px;border-radius:50%;background:var(--bg-light-gray);display:flex;align-items:center;justify-content:center;font-weight:600;font-size:13px;color:var(--text-muted);overflow:hidden;}
		.ec-avatar img{width:100%;height:100%;object-fit:cover;}
		.ec-conv-main{flex:1;min-width:0;}
		.ec-conv .ec-name{font-weight:600;font-size:var(--text-md);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
		.ec-conv .ec-last{color:var(--text-muted);font-size:var(--text-sm);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
		.ec-badge{flex:none;background:var(--primary);color:#fff;border-radius:10px;min-width:18px;height:18px;line-height:18px;text-align:center;font-size:11px;padding:0 5px;}
		.ec-thread-wrap{flex:1;display:flex;flex-direction:column;min-width:0;position:relative;}
		.ec-thread-header{padding:12px;border-bottom:1px solid var(--border-color);font-weight:600;}
		.ec-thread{flex:1;overflow-y:auto;padding:12px 16px;background:var(--bg-gray);display:flex;flex-direction:column;gap:3px;position:relative;}
		.ec-bubble{position:relative;width:fit-content;max-width:65%;padding:5px 9px 3px;border-radius:8px;font-size:13px;line-height:1.35;text-align:left;word-break:break-word;}
		.ec-body{white-space:pre-wrap;}
		.ec-in{align-self:flex-start;background:var(--card-bg);border:1px solid var(--border-color);}
		.ec-out{align-self:flex-end;background:#d9fdd3;color:#111;}
		.ec-sender{font-size:11px;font-weight:600;color:var(--primary);margin-bottom:1px;}
		.ec-meta{font-size:10px;color:var(--text-muted);margin-top:1px;text-align:right;opacity:.7;}
		.ec-tick{margin-left:3px;}
		.ec-tick.seen{color:#34b7f1;opacity:1;}
		.ec-media .chat-img,.ec-media .chat-img img{max-width:220px;}
		.ec-doc{display:inline-flex;align-items:center;gap:6px;color:inherit;text-decoration:underline;}
		.ec-caption{white-space:pre-wrap;margin-top:4px;}
		.ec-quote{border-left:3px solid var(--primary);padding:2px 6px;margin-bottom:4px;background:rgba(0,0,0,.05);border-radius:4px;font-size:11px;opacity:.85;}
		.ec-quote .ec-quote-author{font-weight:600;}
		.ec-reactions{position:absolute;bottom:-11px;right:6px;display:flex;gap:2px;}
		.ec-bubble:has(.ec-reactions){margin-bottom:12px;}
		.ec-react-badge{cursor:pointer;background:var(--card-bg);border:1px solid var(--border-color);border-radius:10px;padding:0 4px;font-size:11px;line-height:16px;box-shadow:0 1px 2px rgba(0,0,0,.15);}
		.ec-react-badge.mine{border-color:var(--primary);}
		.ec-bubble-actions{position:absolute;top:-10px;display:none;gap:2px;}
		.ec-in .ec-bubble-actions{right:4px;}
		.ec-out .ec-bubble-actions{left:4px;}
		.ec-bubble:hover .ec-bubble-actions{display:flex;}
		.ec-act{cursor:pointer;background:var(--card-bg);border:1px solid var(--border-color);border-radius:50%;width:22px;height:22px;line-height:20px;text-align:center;font-size:12px;}
		.ec-act:hover{background:var(--bg-light-gray);}
		.ec-react-pop{position:absolute;z-index:10;background:var(--card-bg);border:1px solid var(--border-color);border-radius:16px;padding:3px 6px;display:flex;gap:4px;box-shadow:0 2px 8px rgba(0,0,0,.2);}
		.ec-react-pop span{cursor:pointer;font-size:16px;}
		.ec-react-pop span:hover{transform:scale(1.25);}
		.ec-emoji-pop{position:absolute;z-index:20;background:var(--card-bg);border:1px solid var(--border-color);border-radius:8px;padding:6px;display:grid;grid-template-columns:repeat(6,1fr);gap:2px;box-shadow:0 2px 8px rgba(0,0,0,.2);}
		.ec-emoji-pop span{cursor:pointer;font-size:18px;padding:2px;text-align:center;border-radius:4px;}
		.ec-emoji-pop span:hover{background:var(--bg-light-gray);}
		.ec-typing{padding:2px 16px;font-size:11px;font-style:italic;}
		.ec-reply-bar{display:flex;align-items:center;justify-content:space-between;padding:6px 10px;border-top:1px solid var(--border-color);background:var(--bg-light-gray);font-size:12px;}
		.ec-reply-bar-text{border-left:3px solid var(--primary);padding-left:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;}
		.ec-reply-cancel{cursor:pointer;color:var(--text-muted);margin-left:8px;font-size:16px;}
		.ec-reply-cancel:hover{color:var(--red-500);}
		.ec-compose{display:flex;gap:6px;padding:10px;border-top:1px solid var(--border-color);align-items:flex-end;}
		.ec-compose textarea{resize:none;flex:1;}
		.ec-attach,.ec-emoji{flex:none;}
		.ec-lock{font-size:11px;}
		.ec-locked{color:var(--text-muted);font-style:italic;}
		.ec-thread-header .ec-unlock{margin-left:8px;}
		.ec-thread-header .ec-header-title{cursor:pointer;}
		.ec-thread-header .ec-header-title:hover{text-decoration:underline;}
		.ec-new-divider{align-self:stretch;display:flex;align-items:center;gap:8px;margin:8px 0;color:var(--red-500,#e24c4c);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;}
		.ec-new-divider::before,.ec-new-divider::after{content:"";flex:1;height:1px;background:var(--red-500,#e24c4c);opacity:.5;}
		.ec-scroll-fab{position:absolute;right:16px;bottom:80px;z-index:5;width:40px;height:40px;border-radius:50%;background:var(--card-bg);border:1px solid var(--border-color);box-shadow:0 2px 8px rgba(0,0,0,.25);cursor:pointer;display:none;align-items:center;justify-content:center;font-size:18px;color:var(--text-color);}
		.ec-scroll-fab:hover{background:var(--bg-light-gray);}
		.ec-scroll-fab.show{display:flex;}
		.ec-scroll-fab .ec-fab-badge{position:absolute;top:-6px;right:-6px;min-width:18px;height:18px;padding:0 5px;border-radius:9px;background:var(--red-500,#e24c4c);color:#fff;font-size:10px;line-height:18px;text-align:center;font-weight:600;}
		.ec-link-card{display:flex;gap:8px;align-items:center;text-decoration:none;color:inherit;padding:6px 8px;border:1px solid var(--border-color);border-radius:8px;background:rgba(0,0,0,.03);max-width:280px;}
		.ec-link-card:hover{background:rgba(0,0,0,.06);}
		.ec-link-icon{flex:none;width:34px;height:34px;border-radius:6px;background:var(--bg-light-gray);display:flex;align-items:center;justify-content:center;font-size:18px;overflow:hidden;}
		.ec-link-icon img{width:100%;height:100%;object-fit:cover;}
		.ec-link-main{min-width:0;}
		.ec-link-title{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
		.ec-link-sub{color:var(--text-muted);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
		.ec-link-removed{opacity:.6;cursor:default;pointer-events:none;}
		.ec-removed-badge{display:inline-block;margin-left:6px;padding:0 6px;border-radius:8px;background:var(--red-500,#e24c4c);color:#fff;font-size:10px;font-weight:600;line-height:16px;vertical-align:middle;}
		.ec-archived-badge{background:var(--gray-500,#8d99a6);}
		.ec-ref-banner{position:sticky;top:0;z-index:6;display:flex;gap:8px;align-items:center;padding:8px 10px;margin-bottom:8px;border:1px solid var(--border-color);border-radius:8px;background:var(--card-bg);cursor:pointer;box-shadow:0 1px 4px rgba(0,0,0,.08);}
		.ec-ref-banner:hover{background:var(--bg-light-gray);}
		.ec-ref-banner.ec-link-removed:hover{background:var(--card-bg);}
		.ec-bubble.ec-highlight{animation:ec-flash 1.6s ease-out;}
		@keyframes ec-flash{0%,40%{background:var(--yellow-100,#fff3cd);}100%{}}
		.ec-attach-pop{position:absolute;z-index:30;background:var(--card-bg);border:1px solid var(--border-color);border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.2);padding:4px;min-width:160px;}
		.ec-attach-opt{padding:7px 10px;cursor:pointer;border-radius:6px;font-size:13px;}
		.ec-attach-opt:hover{background:var(--bg-light-gray);}
		`;
		$(`<style id="ec-chat-styles-v5">${css}</style>`).appendTo(document.head);
	}

	// --- thread list -------------------------------------------------------

	async load_threads() {
		const threads = await frappe.xcall(API + "get_threads");
		this.threads = {};
		for (const t of threads) this.threads[t.name] = t;
		this.render_list();

		if (this.pending_open && this.threads[this.pending_open]) {
			const name = this.pending_open;
			this.pending_open = null;
			this.open(name);
		}
	}

	render_list() {
		const q = (this.$search.val() || "").toLowerCase();
		let list = Object.values(this.threads);
		list = list
			.filter((t) => !q || (t.display_title || "").toLowerCase().includes(q))
			.sort((a, b) => (b.last_message_on || "").localeCompare(a.last_message_on || ""));

		this.$list.empty();
		if (!list.length) {
			this.$list.html(`<div class="text-muted" style="padding:12px;">${__("No chats yet")}</div>`);
			return;
		}
		for (const t of list) {
			const badge = t.unread ? `<span class="ec-badge">${t.unread}</span>` : "";
			// Secret threads keep no readable preview server-side — the lock is the preview.
			const preview = frappe.utils.escape_html(t.last_message_preview || "").slice(0, 40);
			const lock = t.is_secret ? `<span class="ec-lock" title="${__("Secret chat")}">🔒</span> ` : "";
			const $el = $(`
				<div class="ec-conv ${t.name === this.active ? "active" : ""}">
					<div class="ec-avatar">${this.avatar_html(t)}</div>
					<div class="ec-conv-main">
						<div class="ec-name">${lock}${frappe.utils.escape_html(t.display_title || __("Chat"))}</div>
						<div class="ec-last">${preview}</div>
					</div>
					${badge}
				</div>
			`);
			$el.on("click", () => this.open(t.name));
			this.$list.append($el);
		}
	}

	avatar_html(t) {
		const label = (t.display_title || "?").trim().charAt(0).toUpperCase();
		if (t.thread_type === "Group") return "👥";
		return frappe.utils.escape_html(label);
	}

	// --- open + render thread ---------------------------------------------

	async open(name) {
		this.active = name;
		this.set_reply(null);
		this.messages = [];
		this.hide_typing();
		const t = this.threads[name];
		this.set_header(t);
		this.$compose.show();
		this.render_list();

		// Ask for the key before loading: with it the bubbles render decrypted straight
		// away, without it they render locked and the banner offers to unlock.
		if (t && t.is_secret && !erpnext.chat_crypto.is_unlocked()) {
			await erpnext.chat_crypto.ensure_unlocked();
			this.set_header(t);
		}

		// other participant's read cursor (direct threads → seen ticks)
		this.other_last_read = null;
		if (t && t.thread_type === "Direct") {
			const other = (t.participants || []).find((p) => p.user !== this.me);
			this.other_last_read = other ? other.last_read_on : null;
		}

		// My read cursor at open time — used to place the "New messages" divider and to
		// decide whether to land on the first unread message or at the bottom.
		this.read_cursor = (t && t.my_last_read) || null;

		this.messages = await frappe.xcall(API + "get_messages", { thread: name });
		await this.decrypt_messages(this.messages);
		// Anchor the divider once per open; it stays put even as messages get marked read.
		this.new_divider_before = this.first_unread_name();
		this.render_thread(false);
		this.scroll_to_start();
	}

	// Name of the first message the current user hasn't read yet (incoming only). Null when
	// the thread is fully read.
	first_unread_name() {
		const cursor = this.read_cursor;
		const m = this.messages.find((x) => x.sender !== this.me && (!cursor || x.creation > cursor));
		return m ? m.name : null;
	}

	// On open: land on the first unread message (with the divider just above it) if there is
	// one, otherwise at the bottom. Then reconcile the read cursor with what's on screen.
	scroll_to_start() {
		const divider = this.$thread.find(".ec-new-divider")[0];
		if (divider) {
			this.$thread.scrollTop(Math.max(0, divider.offsetTop - 60));
		} else {
			this.$thread.scrollTop(this.$thread[0].scrollHeight);
		}
		this.update_read_progress();
		this.update_fab();
	}

	set_header(t) {
		const title = t ? t.display_title || __("Chat") : __("Chat");
		// The title is the entry point to the chat overview (participants, media, files,
		// links) — same gesture as in WhatsApp.
		const bind_info = () => {
			this.$header
				.find(".ec-header-title")
				.attr("title", __("Chat info"))
				.on("click", () => this.show_info());
		};
		const mute_html = t ? erpnext.chat_sound.button_html(t.muted) : "";
		const bind_mute = () => {
			this.$header.find(".chat-mute-btn").on("click", () => this.toggle_mute());
		};
		if (!t || !t.is_secret) {
			this.$header.html(`<span class="ec-header-title"></span>${mute_html}`);
			this.$header.find(".ec-header-title").text(title);
			bind_info();
			bind_mute();
			return;
		}
		const locked = !erpnext.chat_crypto.is_unlocked();
		this.$header.html(
			`🔒 <span class="ec-header-title"></span>${mute_html}${
				locked ? ` <button class="btn btn-xs btn-primary ec-unlock">${__("Unlock")}</button>` : ""
			}`
		);
		this.$header.find(".ec-header-title").text(title);
		bind_info();
		bind_mute();
		this.$header.find(".ec-unlock").on("click", async () => {
			await erpnext.chat_crypto.ensure_unlocked();
			if (erpnext.chat_crypto.is_unlocked()) this.open(this.active);
		});
	}

	async toggle_mute() {
		const t = this.threads[this.active];
		if (!t) return;
		const muted = t.muted ? 0 : 1;
		t.muted = muted;
		this.set_header(t);
		try {
			await frappe.xcall(API + "set_muted", { thread: this.active, muted });
		} catch (e) {
			t.muted = muted ? 0 : 1;
			this.set_header(t);
			return;
		}
		frappe.show_alert({
			message: muted ? __("Chat muted") : __("Chat unmuted"),
			indicator: "blue",
		});
	}

	// Decrypt in place: every message carries `_dec` once opened, so rendering stays
	// synchronous and a locked thread simply has no `_dec` anywhere.
	async decrypt_messages(list) {
		if (!erpnext.chat_crypto.is_unlocked()) return;
		for (const m of list) {
			if (!m.is_encrypted || m._dec) continue;
			try {
				m._dec = await erpnext.chat_crypto.decrypt(m.thread, m.message, m.enc_iv);
			} catch (e) {
				m._dec_failed = true;
			}
			const rp = m.reply_preview;
			if (rp && rp.is_encrypted && rp.ciphertext) {
				try {
					const dec = await erpnext.chat_crypto.decrypt(m.thread, rp.ciphertext, rp.enc_iv);
					rp.text = this.preview_of_payload(rp.content_type, dec);
				} catch (e) {
					rp.text = "🔒 " + __("Encrypted");
				}
			}
		}
	}

	async load_older() {
		if (!this.active || !this.messages.length || this.loading_older) return;
		this.loading_older = true;
		const before = this.messages[0].creation;
		const older = await frappe.xcall(API + "get_messages", {
			thread: this.active,
			before,
		});
		if (older.length) {
			await this.decrypt_messages(older);
			const prev_h = this.$thread[0].scrollHeight;
			this.messages = older.concat(this.messages);
			this.render_thread(false);
			const new_h = this.$thread[0].scrollHeight;
			console.log("[chat] employee load_older: restoring scroll", {
				older_count: older.length,
				prev_h,
				new_h,
				new_scrollTop: new_h - prev_h,
			});
			this.$thread.scrollTop(new_h - prev_h);
		}
		this.loading_older = false;
		return older.length > 0;
	}

	// Scroll a message into view (paging older history in if it isn't loaded yet) and
	// flash it — used when tapping a shared link in the chat overview.
	async jump_to_message(name) {
		if (!name) return;
		let el = document.getElementById("ec-msg-" + name);
		let guard = 0;
		while (!el && guard++ < 30) {
			const grew = await this.load_older();
			if (!grew) break;
			el = document.getElementById("ec-msg-" + name);
		}
		if (!el) {
			frappe.show_alert({ message: __("Message not found"), indicator: "orange" });
			return;
		}
		el.scrollIntoView({ behavior: "smooth", block: "center" });
		const $b = $(el);
		$b.addClass("ec-highlight");
		setTimeout(() => $b.removeClass("ec-highlight"), 1700);
	}

	render_thread(scroll) {
		this.$thread.empty();
		const t = this.threads[this.active] || {};
		const is_group = t.thread_type === "Group";

		if (t.thread_type === "Document" && t.reference_doctype) {
			const $ref = $(this.reference_banner_html(t)).appendTo(this.$thread);
			$ref.filter("[data-dt]").on("click", (e) => {
				frappe.set_route(
					"Form",
					$(e.currentTarget).attr("data-dt"),
					$(e.currentTarget).attr("data-name")
				);
			});
		}

		// index for reply lookups
		this.msg_by_name = {};
		for (const m of this.messages) this.msg_by_name[m.name] = m;

		// last outgoing message that the other party has seen (direct threads)
		let last_out_name = null;
		for (const m of this.messages) if (m.sender === this.me) last_out_name = m.name;

		for (const m of this.messages) {
			// "New messages" divider, anchored at the first message that was unread on open.
			if (this.new_divider_before && m.name === this.new_divider_before) {
				this.$thread.append(`<div class="ec-new-divider">${__("New messages")}</div>`);
			}
			const out = m.sender === this.me;
			const time = frappe.datetime.str_to_user(m.creation).split(" ").slice(1).join(" ");

			const sender_html =
				is_group && !out
					? `<div class="ec-sender">${frappe.utils.escape_html(m.sender_name || m.sender)}</div>`
					: "";

			let quote = "";
			if (m.reply_preview) {
				quote = `<div class="ec-quote"><div class="ec-quote-author">${frappe.utils.escape_html(
					m.reply_preview.sender_name || ""
				)}</div>${frappe.utils.escape_html((m.reply_preview.text || "").slice(0, 80))}</div>`;
			}

			const react_html = this.reactions_html(m);

			let tick = "";
			if (out && !is_group && m.name === last_out_name) {
				const seen = this.other_last_read && this.other_last_read >= m.creation;
				tick = `<span class="ec-tick ${seen ? "seen" : ""}">${seen ? "✓✓" : "✓"}</span>`;
			}

			const actions = `<div class="ec-bubble-actions"><span class="ec-act ec-do-react" title="${__(
				"React"
			)}">😊</span><span class="ec-act ec-do-reply" title="${__("Reply")}">↩</span></div>`;

			const $b = $(
				`<div class="ec-bubble ${out ? "ec-out" : "ec-in"}" id="ec-msg-${frappe.utils.escape_html(
					m.name
				)}">${actions}${sender_html}${quote}${this.render_body(
					m
				)}<div class="ec-meta">${time}${tick}</div>${react_html}</div>`
			);
			$b.data("msg", m);
			this.$thread.append($b);
		}

		erpnext.chat_media.bind(this.$thread, "chat");
		// Encrypted documents have no directly usable URL — decrypt, then hand the blob
		// to the browser as a normal download.
		this.$thread.find(".ec-enc-doc").on("click", (e) => {
			e.preventDefault();
			this.download_encrypted(JSON.parse($(e.currentTarget).attr("data-file")));
		});
		this.$thread.find(".ec-do-reply").on("click", (e) => {
			const m = $(e.currentTarget).closest(".ec-bubble").data("msg");
			this.set_reply({ name: m.name, text: this.preview_of(m) });
		});
		this.$thread.find(".ec-do-react").on("click", (e) => this.react_popover(e));
		this.$thread.find(".ec-react-badge").on("click", (e) => {
			const $badge = $(e.currentTarget);
			const m = $badge.closest(".ec-bubble").data("msg");
			this.toggle_reaction(m, $badge.data("emoji"));
		});

		console.log("[chat] employee render_thread", {
			scroll: !!scroll,
			msg_count: this.messages.length,
			scrollHeight: this.$thread[0].scrollHeight,
		});
		if (scroll) this.$thread.scrollTop(this.$thread[0].scrollHeight);
	}

	// Encrypted documents have no directly usable URL — decrypt, then hand the blob to
	// the browser as a normal download.
	async download_encrypted(file) {
		frappe.dom.freeze(__("Decrypting…"));
		try {
			const blob = await erpnext.chat_media.fetch_encrypted(file.url, file.key, file.iv, file.mime);
			const url = URL.createObjectURL(blob);
			$("<a>")
				.attr({ href: url, download: file.name || "file" })[0]
				.click();
			setTimeout(() => URL.revokeObjectURL(url), 10000);
		} catch (err) {
			frappe.msgprint(__("Cannot decrypt this file"));
		} finally {
			frappe.dom.unfreeze();
		}
	}

	// --- chat overview -----------------------------------------------------

	async show_info() {
		if (!this.active) return;
		console.log("[chat] employee show_info (conversation name pressed)", { thread: this.active });
		const info = await frappe.xcall(API + "get_thread_info", { thread: this.active });
		const media = [];
		const files = [];
		const links = [];

		if (info.is_secret) {
			// Nothing was classified server-side: decrypt each row here and sort it.
			const unlocked = await erpnext.chat_crypto.ensure_unlocked();
			if (unlocked) {
				for (const m of info.attachments) {
					let dec;
					try {
						dec = await erpnext.chat_crypto.decrypt(m.thread, m.message, m.enc_iv);
					} catch (e) {
						continue;
					}
					const file = dec.file;
					if (!file) continue;
					const item = {
						sender_name: m.sender_name,
						creation: m.creation,
						caption: dec.text || "",
					};
					if (m.content_type === "image") {
						media.push({
							...item,
							html: erpnext.chat_media.encrypted_image_html({
								url: file.url,
								key: file.key,
								iv: file.iv,
								mime: file.mime,
								file_name: file.name,
								thumb_url: (dec.thumb || {}).url,
								thumb_key: (dec.thumb || {}).key,
								thumb_iv: (dec.thumb || {}).iv,
							}),
						});
					} else {
						files.push({
							...item,
							file_name: file.name,
							file_size: file.size,
							on_click: () => this.download_encrypted(file),
						});
					}
					for (const url of (dec.text || "").match(URL_RE) || []) {
						links.push({
							url,
							sender_name: m.sender_name,
							creation: m.creation,
							on_click: () => {
								dialog.hide();
								this.jump_to_message(m.name);
							},
						});
					}
				}
				for (const m of info.links) {
					let dec;
					try {
						dec = await erpnext.chat_crypto.decrypt(m.thread, m.message, m.enc_iv);
					} catch (e) {
						continue;
					}
					for (const url of (dec.text || "").match(URL_RE) || []) {
						links.push({
							url,
							sender_name: m.sender_name,
							creation: m.creation,
							on_click: () => {
								dialog.hide();
								this.jump_to_message(m.name);
							},
						});
					}
				}
			}
		} else {
			for (const m of info.attachments) {
				const item = {
					sender_name: m.sender_name,
					creation: m.creation,
					caption: m.message || "",
				};
				if (m.content_type === "image") {
					media.push({ ...item, html: erpnext.chat_media.image_html(m.attach) });
				} else {
					files.push({
						...item,
						file_name: m.file_name,
						file_size: m.file_size,
						url: m.attach,
					});
				}
			}
			for (const l of info.links) {
				links.push({
					...l,
					on_click: l.message
						? () => {
								dialog.hide();
								this.jump_to_message(l.message);
						  }
						: null,
				});
			}
		}

		const is_group = info.thread_type === "Group";
		const me = (info.participants || []).find((p) => p.is_me);
		const can_admin = is_group && me && me.role === "Admin";

		const people = info.participants.map((p) => ({
			name: p.name,
			user: p.user,
			image: p.image,
			is_me: p.is_me,
			subtitle: [p.user, p.role === "Admin" ? __("Admin") : null].filter(Boolean).join(" · "),
			on_remove:
				can_admin && !p.is_me
					? async () => {
							await frappe.xcall(API + "remove_participant", {
								thread: this.active,
								user: p.user,
							});
							dialog.hide();
							await this.load_threads();
							this.show_info();
					  }
					: null,
		}));

		const actions = [
			{
				label: info.muted ? __("Unmute chat") : __("Mute chat"),
				on_click: async () => {
					await this.toggle_mute();
					dialog.hide();
				},
			},
		];
		if (can_admin) {
			actions.push({
				label: __("Rename chat"),
				on_click: () => {
					frappe.prompt(
						{
							fieldname: "title",
							label: __("Chat name"),
							fieldtype: "Data",
							default: info.title,
							reqd: 1,
						},
						async (v) => {
							await frappe.xcall(API + "rename_thread", {
								thread: this.active,
								title: v.title,
							});
							dialog.hide();
							await this.load_threads();
							this.set_header(this.threads[this.active]);
						},
						__("Rename chat")
					);
				},
			});
		}

		const dialog = erpnext.chat_info.show({
			title: info.display_title,
			subtitle: [
				is_group ? __("Group chat") : __("Direct chat"),
				info.is_secret ? "🔒 " + __("Secret") : null,
				__("{0} participants", [info.participants.length]),
			]
				.filter(Boolean)
				.join(" · "),
			source: "chat",
			people,
			media,
			files,
			links,
			actions,
			on_add_person: can_admin
				? () => {
						dialog.hide();
						this.add_people_dialog();
				  }
				: null,
		});
	}

	link_card_html(card) {
		if (!card || !card.url) return `<i>(${__("link")})</i>`;
		const icon = card.image
			? `<img src="${frappe.utils.escape_html(card.image)}">`
			: {
					document: "📄",
					report: "📊",
					list: "🗂️",
			  }[card.kind] || "🔗";
		const title = frappe.utils.escape_html(card.title || card.url);
		const sub = frappe.utils.escape_html(card.subtitle || card.doctype || "");
		const removed = !!card.removed;
		const badge = removed ? `<span class="ec-removed-badge">${__("Removed")}</span>` : "";
		// A deleted target has nowhere to go: drop the href so the card is inert but still legible.
		const cls = "ec-link-card" + (removed ? " ec-link-removed" : "");
		const attrs = removed
			? ""
			: ` href="${frappe.utils.escape_html(card.url)}" target="_blank" rel="noopener"`;
		return `<a class="${cls}"${attrs}>
			<div class="ec-link-icon">${icon}</div>
			<div class="ec-link-main">
				<div class="ec-link-title">${title}${badge}</div>
				${sub ? `<div class="ec-link-sub">${sub}</div>` : ""}
			</div>
		</a>`;
	}

	// Pinned card at the top of a Document thread: the record the chat is about. Clickable
	// (routes to the form) unless the record was deleted, in which case it shows a Removed
	// badge and stays inert — the ghost label keeps the conversation legible.
	reference_banner_html(t) {
		const dt = t.reference_doctype;
		const name = t.reference_name;
		const removed = !!t.reference_removed;
		const title = frappe.utils.escape_html(t.reference_label || name || __("Document"));
		const sub = frappe.utils.escape_html(dt ? `${__(dt)} · ${name}` : "");
		const badge = removed ? `<span class="ec-removed-badge">${__("Removed")}</span>` : "";
		const arch =
			t.is_archived && !removed
				? `<span class="ec-removed-badge ec-archived-badge">${__("Archived")}</span>`
				: "";
		const data = removed
			? ""
			: ` data-dt="${frappe.utils.escape_html(dt)}" data-name="${frappe.utils.escape_html(name)}"`;
		return `<div class="ec-ref-banner${removed ? " ec-link-removed" : ""}"${data}>
			<div class="ec-link-icon">📄</div>
			<div class="ec-link-main">
				<div class="ec-link-title">${title}${badge}${arch}</div>
				${sub ? `<div class="ec-link-sub">${sub}</div>` : ""}
			</div>
		</div>`;
	}

	render_body(m) {
		if (m.is_encrypted) return this.render_encrypted_body(m);
		const caption = m.message || "";
		const cap_html = caption ? `<div class="ec-caption">${frappe.utils.escape_html(caption)}</div>` : "";
		if (m.content_type === "link") {
			return this.link_card_html(m.link_data);
		}
		if (m.content_type === "image" && m.attach) {
			return `<div class="ec-media">${erpnext.chat_media.image_html(m.attach)}</div>${cap_html}`;
		}
		if (m.content_type === "audio" && m.attach) {
			return `<div class="ec-media">${erpnext.chat_media.audio_html(m.attach)}</div>${cap_html}`;
		}
		if (m.content_type === "file" && m.attach) {
			const url = frappe.utils.escape_html(m.attach);
			const fname = frappe.utils.escape_html(
				decodeURIComponent(m.attach.split("/").pop() || __("File"))
			);
			return `<a class="ec-doc" href="${url}" target="_blank" download>📎 ${fname}</a>${cap_html}`;
		}
		return caption
			? `<span class="ec-body">${frappe.utils.escape_html(caption)}</span>`
			: `<i>(${__("no text")})</i>`;
	}

	// A secret message renders from its decrypted payload; without the key there is
	// nothing to show but the lock — the ciphertext is all the page ever received.
	render_encrypted_body(m) {
		if (m._dec_failed) {
			return `<span class="ec-locked">🔒 ${__("Cannot decrypt this message")}</span>`;
		}
		if (!m._dec) return `<span class="ec-locked">🔒 ${__("Encrypted")}</span>`;

		if (m._dec.link) {
			return this.link_card_html(m._dec.link);
		}

		const text = m._dec.text || "";
		const cap_html = text ? `<div class="ec-caption">${frappe.utils.escape_html(text)}</div>` : "";
		const file = m._dec.file;
		if (file && m.content_type === "audio") {
			return `<div class="ec-media">${erpnext.chat_media.encrypted_audio_html({
				url: file.url,
				key: file.key,
				iv: file.iv,
				mime: file.mime,
				file_name: file.name,
			})}</div>${cap_html}`;
		}
		if (file && m.content_type === "image") {
			return `<div class="ec-media">${erpnext.chat_media.encrypted_image_html({
				url: file.url,
				key: file.key,
				iv: file.iv,
				mime: file.mime,
				file_name: file.name,
				thumb_url: (m._dec.thumb || {}).url,
				thumb_key: (m._dec.thumb || {}).key,
				thumb_iv: (m._dec.thumb || {}).iv,
			})}</div>${cap_html}`;
		}
		if (file) {
			const fname = frappe.utils.escape_html(file.name || __("File"));
			return `<a class="ec-doc ec-enc-doc" href="#" data-file="${frappe.utils.escape_html(
				JSON.stringify(file)
			)}">📎 ${fname}</a>${cap_html}`;
		}
		return text
			? `<span class="ec-body">${frappe.utils.escape_html(text)}</span>`
			: `<i>(${__("no text")})</i>`;
	}

	reactions_html(m) {
		const r = m.reactions || {};
		const keys = Object.keys(r).filter((e) => (r[e] || []).length);
		if (!keys.length) return "";
		const badges = keys
			.map((e) => {
				const users = r[e] || [];
				const mine = users.includes(this.me) ? "mine" : "";
				const count = users.length > 1 ? users.length : "";
				return `<span class="ec-react-badge ${mine}" data-emoji="${frappe.utils.escape_html(
					e
				)}">${frappe.utils.escape_html(e)}${count}</span>`;
			})
			.join("");
		return `<div class="ec-reactions">${badges}</div>`;
	}

	preview_of(m) {
		if (m.is_encrypted) {
			if (!m._dec) return "🔒 " + __("Encrypted");
			return this.preview_of_payload(m.content_type, m._dec);
		}
		if (m.content_type === "image") return "📷 " + __("Photo");
		if (m.content_type === "audio") return "🎤 " + __("Audio");
		if (m.content_type === "file") return "📎 " + __("File");
		if (m.content_type === "link") {
			return "🔗 " + ((m.link_data || {}).title || m.message || __("Link"));
		}
		return m.message || "";
	}

	preview_of_payload(content_type, payload) {
		if (content_type === "image") return "📷 " + __("Photo");
		if (content_type === "audio") return "🎤 " + __("Audio");
		if (content_type === "file") {
			return "📎 " + (((payload || {}).file || {}).name || __("File"));
		}
		if (content_type === "link" || (payload || {}).link) {
			return "🔗 " + (((payload || {}).link || {}).title || __("Link"));
		}
		return (payload || {}).text || "";
	}

	// --- realtime handlers -------------------------------------------------

	async on_realtime_message(d) {
		console.log("[chat] employee page realtime message", d);
		// Someone else's message rings, unless this user muted the thread.
		if (d && d.sender && d.sender !== this.me) {
			const t = this.threads[d.thread];
			console.log("[chat] employee ring", {
				thread: d.thread,
				sender: d.sender,
				thread_found: !!t,
				muted: t && t.muted,
			});
			erpnext.chat_sound.play(t && t.muted);
		}
		if (d && d.thread === this.active && d.name) {
			// avoid duplicating our own optimistic append
			if (this.push_message(d)) {
				await this.decrypt_messages([d]);
				// Only follow the conversation to the bottom if the user was already there;
				// otherwise keep their scroll position so reading history isn't yanked.
				const el = this.$thread[0];
				const at_bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
				const mine = d.sender === this.me;
				this.render_thread(at_bottom || mine);
				if (at_bottom || mine) {
					// At the bottom (or it's our own message) → it's read as it lands.
					this.update_read_progress();
				} else {
					// Scrolled up → leave it unread, just refresh the badge + FAB counter.
					this.recount_unread(this.active);
				}
				this.update_fab();
			}
		}
		this.load_threads();
	}

	on_realtime_typing(d) {
		if (!d || d.thread !== this.active || d.user === this.me) return;
		const t = this.threads[this.active] || {};
		const who = t.thread_type === "Group" ? (t.participants || []).find((p) => p.user === d.user) : null;
		const name = who ? who.employee_name || d.user : "";
		this.$typing.text(name ? `${name} ${__("is typing…")}` : __("typing…")).show();
		clearTimeout(this.typing_timer);
		this.typing_timer = setTimeout(() => this.hide_typing(), 3000);
	}

	hide_typing() {
		clearTimeout(this.typing_timer);
		this.$typing.hide().text("");
	}

	on_realtime_seen(d) {
		if (!d || d.thread !== this.active || d.user === this.me) return;
		this.other_last_read = d.last_read_on;
		this.render_thread(false);
	}

	on_realtime_reaction(d) {
		if (!d || d.thread !== this.active) return;
		const m = this.msg_by_name && this.msg_by_name[d.message];
		if (m) {
			m.reactions = d.reactions;
			this.render_thread(false);
		}
	}

	// --- compose actions ---------------------------------------------------

	set_reply(reply) {
		this.reply_to = reply;
		if (reply) {
			this.$replyBar
				.find(".ec-reply-bar-text")
				.text(`${__("Replying to")}: ${reply.text.slice(0, 60)}`);
			this.$replyBar.show();
			this.$input.focus();
		} else {
			this.$replyBar.hide();
		}
	}

	// Append a message unless it is already in the thread. The realtime echo of
	// our own message can arrive before the send call resolves (it is published
	// after_commit, i.e. before the HTTP response), so both paths dedupe here.
	push_message(m) {
		if (!m || !m.name) return false;
		if (this.messages.some((x) => x.name === m.name)) return false;
		this.messages.push(m);
		return true;
	}

	notify_typing() {
		if (!this.active) return;
		const nowms = new Date().getTime();
		if (nowms - this.typing_sent_at < 2500) return;
		this.typing_sent_at = nowms;
		frappe.xcall(API + "typing", { thread: this.active });
	}

	is_secret_thread() {
		return !!(this.threads[this.active] || {}).is_secret;
	}

	// Everything a secret thread sends goes through here: the payload is encrypted with
	// the thread key before it leaves the page, so the server only ever gets base64.
	async encrypted_args(payload) {
		const { ciphertext, iv } = await erpnext.chat_crypto.encrypt(this.active, payload);
		return { message: ciphertext, is_encrypted: 1, enc_iv: iv };
	}

	async send() {
		const text = (this.$input.val() || "").trim();
		if (!text || !this.active) return;
		const secret = this.is_secret_thread();
		if (secret && !(await erpnext.chat_crypto.ensure_unlocked())) return;

		// Autoparse: a message that is nothing but a desk URL becomes a rich link card.
		let card = null;
		if (/^https?:\/\/\S+$/.test(text)) {
			try {
				const c = await frappe.xcall(API + "resolve_link", { url: text });
				if (c && c.kind && c.kind !== "external") card = c;
			} catch (e) {
				// fall back to plain text
			}
		}

		this.$input.val("");
		const reply_to = this.reply_to ? this.reply_to.name : null;
		this.set_reply(null);
		try {
			let args;
			if (card) {
				args = { content_type: "link" };
				if (secret) Object.assign(args, await this.encrypted_args({ link: card }));
				else args.link_data = JSON.stringify(card);
			} else {
				args = secret ? await this.encrypted_args({ text }) : { message: text };
			}
			const msg = await frappe.xcall(API + "send_message", {
				thread: this.active,
				reply_to,
				...args,
			});
			if (this.push_message(msg)) await this.decrypt_messages([msg]);
			this.render_thread(true);
			this.load_threads();
		} catch (e) {
			frappe.msgprint(__("Failed to send message"));
			this.$input.val(text);
		}
	}

	// The paperclip offers two things: a file/photo upload (existing) or an ERPNext link.
	attach_menu(e) {
		if (!this.active) return;
		$(".ec-attach-pop").remove();
		const $btn = $(e.currentTarget);
		const off = $btn.offset();
		const $pop = $(`<div class="ec-attach-pop">
			<div class="ec-attach-opt" data-act="media">📎 ${__("Media / File")}</div>
			<div class="ec-attach-opt" data-act="link">🔗 ${__("Link")}</div>
		</div>`);
		$("body").append($pop);
		$pop.css({ top: off.top - $pop.outerHeight() - 6, left: off.left });
		$pop.find('[data-act="media"]').on("click", () => {
			$pop.remove();
			this.attach_media();
		});
		$pop.find('[data-act="link"]').on("click", () => {
			$pop.remove();
			this.attach_link_dialog();
		});
		setTimeout(() => $(document).one("click", () => $pop.remove()), 0);
	}

	attach_link_dialog() {
		const d = new frappe.ui.Dialog({
			title: __("Share a link"),
			fields: [
				{
					fieldtype: "Link",
					fieldname: "link_doctype",
					label: __("Document Type"),
					options: "DocType",
					reqd: 1,
				},
				{
					fieldtype: "Dynamic Link",
					fieldname: "link_name",
					label: __("Document"),
					options: "link_doctype",
					reqd: 1,
				},
			],
			primary_action_label: __("Send"),
			primary_action: async (v) => {
				d.hide();
				const url = frappe.urllib.get_full_url(
					frappe.utils.get_form_link(v.link_doctype, v.link_name)
				);
				await this.send_link(url);
			},
		});
		d.show();
	}

	// Resolve a desk URL to a card and post it as a link message (secret-aware).
	async send_link(url) {
		if (!this.active) return;
		const secret = this.is_secret_thread();
		if (secret && !(await erpnext.chat_crypto.ensure_unlocked())) return;
		let card;
		try {
			card = await frappe.xcall(API + "resolve_link", { url });
		} catch (e) {
			card = { kind: "page", url, title: url };
		}
		if (!card || !card.url) card = { kind: "page", url, title: url };
		const reply_to = this.reply_to ? this.reply_to.name : null;
		this.set_reply(null);
		frappe.dom.freeze(__("Sending…"));
		try {
			const args = { content_type: "link" };
			if (secret) Object.assign(args, await this.encrypted_args({ link: card }));
			else args.link_data = JSON.stringify(card);
			const msg = await frappe.xcall(API + "send_message", {
				thread: this.active,
				reply_to,
				...args,
			});
			if (this.push_message(msg)) await this.decrypt_messages([msg]);
			this.render_thread(true);
			this.load_threads();
		} catch (e) {
			frappe.msgprint(__("Failed to send message"));
		} finally {
			frappe.dom.unfreeze();
		}
	}

	attach_media() {
		if (!this.active) return;
		if (this.is_secret_thread()) return this.attach_media_secret();
		new frappe.ui.FileUploader({
			folder: "Home/Attachments",
			on_success: async (file) => {
				const content_type = mime_to_content_type(
					file.file_type || file.type,
					file.file_name || file.file_url
				);
				frappe.dom.freeze(__("Sending…"));
				try {
					const msg = await frappe.xcall(API + "send_message", {
						thread: this.active,
						content_type,
						attach: file.file_url,
						message: (this.$input.val() || "").trim(),
						reply_to: this.reply_to ? this.reply_to.name : null,
					});
					this.$input.val("");
					this.set_reply(null);
					this.push_message(msg);
					this.render_thread(true);
					this.load_threads();
				} catch (err) {
					frappe.msgprint(__("Failed to send file"));
				} finally {
					frappe.dom.unfreeze();
				}
			},
		});
	}

	// Secret attachments never touch frappe.ui.FileUploader: the bytes are encrypted in
	// the page and uploaded as opaque blobs, together with a preview built here.
	attach_media_secret() {
		const input = $('<input type="file" style="display:none">').appendTo(document.body);
		input.on("change", async () => {
			const file = input[0].files && input[0].files[0];
			input.remove();
			if (!file) return;
			if (!(await erpnext.chat_crypto.ensure_unlocked())) return;

			const content_type = mime_to_content_type(file.type, file.name) === "image" ? "image" : "file";
			frappe.dom.freeze(__("Encrypting…"));
			try {
				const enc = await erpnext.chat_crypto.encrypt_blob(file);
				const url = await erpnext.chat_media.upload_encrypted(enc.blob, file.name);
				const payload = {
					text: (this.$input.val() || "").trim(),
					file: {
						url,
						key: enc.key,
						iv: enc.iv,
						name: file.name,
						mime: file.type,
						size: file.size,
					},
				};

				const preview = await erpnext.chat_media.make_preview_blob(file);
				if (preview) {
					const enc_thumb = await erpnext.chat_crypto.encrypt_blob(preview);
					payload.thumb = {
						url: await erpnext.chat_media.upload_encrypted(
							enc_thumb.blob,
							"preview-" + file.name
						),
						key: enc_thumb.key,
						iv: enc_thumb.iv,
					};
				}

				const args = await this.encrypted_args(payload);
				const msg = await frappe.xcall(API + "send_message", {
					thread: this.active,
					content_type,
					// The ciphertext URL is kept for housekeeping; it reveals nothing.
					attach: url,
					reply_to: this.reply_to ? this.reply_to.name : null,
					...args,
				});
				this.$input.val("");
				this.set_reply(null);
				if (this.push_message(msg)) await this.decrypt_messages([msg]);
				this.render_thread(true);
				this.load_threads();
			} catch (err) {
				frappe.msgprint(__("Failed to send file"));
			} finally {
				frappe.dom.unfreeze();
			}
		});
		input.trigger("click");
	}

	// Record a voice message and send it as an audio message. Secret threads encrypt the
	// blob in the browser, exactly like attach_media_secret.
	async record_voice() {
		if (!this.active) return;
		const rec = await erpnext.chat_media.record_audio();
		if (!rec) return;
		if (this.is_secret_thread()) return this.send_voice_secret(rec);
		frappe.dom.freeze(__("Sending…"));
		try {
			const url = await erpnext.chat_media.upload_audio(rec.blob, rec.ext);
			const msg = await frappe.xcall(API + "send_message", {
				thread: this.active,
				content_type: "audio",
				attach: url,
				message: "",
				reply_to: this.reply_to ? this.reply_to.name : null,
			});
			this.set_reply(null);
			this.push_message(msg);
			this.render_thread(true);
			this.load_threads();
		} catch (err) {
			frappe.msgprint(__("Failed to send voice message"));
		} finally {
			frappe.dom.unfreeze();
		}
	}

	async send_voice_secret(rec) {
		if (!(await erpnext.chat_crypto.ensure_unlocked())) return;
		frappe.dom.freeze(__("Encrypting…"));
		try {
			const enc = await erpnext.chat_crypto.encrypt_blob(rec.blob);
			const url = await erpnext.chat_media.upload_encrypted(
				enc.blob,
				"voice-" + Date.now() + "." + rec.ext
			);
			const payload = {
				text: "",
				file: {
					url,
					key: enc.key,
					iv: enc.iv,
					name: "voice." + rec.ext,
					mime: rec.mime,
					size: rec.blob.size,
				},
			};
			const args = await this.encrypted_args(payload);
			const msg = await frappe.xcall(API + "send_message", {
				thread: this.active,
				content_type: "audio",
				attach: url,
				reply_to: this.reply_to ? this.reply_to.name : null,
				...args,
			});
			this.set_reply(null);
			if (this.push_message(msg)) await this.decrypt_messages([msg]);
			this.render_thread(true);
			this.load_threads();
		} catch (err) {
			frappe.msgprint(__("Failed to send voice message"));
		} finally {
			frappe.dom.unfreeze();
		}
	}

	emoji_picker(e) {
		e.stopPropagation();
		$(".ec-emoji-pop").remove();
		const $pop = $(
			`<div class="ec-emoji-pop">${EMOJI_SET.map((x) => `<span>${x}</span>`).join("")}</div>`
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

	// --- reactions ---------------------------------------------------------

	react_popover(e) {
		e.stopPropagation();
		this.page.main.find(".ec-react-pop").remove();
		const m = $(e.currentTarget).closest(".ec-bubble").data("msg");
		const $pop = $(
			`<div class="ec-react-pop">${QUICK_REACTIONS.map((x) => `<span data-e="${x}">${x}</span>`).join(
				""
			)}</div>`
		);
		$("body").append($pop);
		const off = $(e.currentTarget).offset();
		$pop.css({ top: off.top - 40, left: off.left });
		$pop.find("span").on("click", (ev) => {
			$pop.remove();
			this.toggle_reaction(m, $(ev.currentTarget).data("e"));
		});
		setTimeout(() => $(document).one("click", () => $pop.remove()), 0);
	}

	async toggle_reaction(m, emoji) {
		const users = (m.reactions && m.reactions[emoji]) || [];
		const mine = users.includes(this.me);
		try {
			const reactions = await frappe.xcall(API + (mine ? "clear_reaction" : "set_reaction"), {
				message: m.name,
				emoji,
			});
			m.reactions = reactions;
			this.render_thread(false);
		} catch (e) {
			frappe.msgprint(__("Failed to react"));
		}
	}

	// --- read receipts -----------------------------------------------------

	// Advance the read cursor. `upto` (a message creation timestamp) marks read only that far,
	// leaving anything below the fold unread; omit it to mark the whole thread read.
	mark_read(upto) {
		if (!this.active) return;
		const thread = this.active;
		frappe.xcall(API + "mark_read", { thread, upto: upto || null }).then((res) => {
			const cursor = (res && res.last_read_on) || upto || frappe.datetime.now_datetime();
			if (this.active === thread) this.read_cursor = cursor;
			this.recount_unread(thread);
		});
	}

	// Recompute the per-thread unread badge from the local cursor (messages the current user
	// hasn't reached yet). Cheap — the open thread's messages are already in memory.
	recount_unread(thread) {
		const t = this.threads[thread];
		if (!t) return;
		if (thread === this.active) {
			const cursor = this.read_cursor;
			t.unread = this.messages.filter(
				(m) => m.sender !== this.me && (!cursor || m.creation > cursor)
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
		this.$thread.find(".ec-bubble").each((_, b) => {
			const m = $(b).data("msg");
			if (!m || m.sender === this.me) return;
			if (b.offsetTop < bottom_edge && m.creation > newest) newest = m.creation;
		});
		if (newest && newest > (this.read_cursor || "")) {
			this.read_cursor = newest;
			this.recount_unread(this.active);
			clearTimeout(this._read_timer);
			const upto = newest;
			this._read_timer = setTimeout(() => this.mark_read(upto), 350);
		}
	}

	// Show the scroll-to-latest button when the user is away from the bottom; badge it with
	// how many messages still sit below the fold unread.
	update_fab() {
		if (!this.$fab) return;
		const el = this.$thread[0];
		if (!el || !this.active) return this.$fab.removeClass("show");
		const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
		const away = dist > 120;
		this.$fab.toggleClass("show", away);
		const t = this.threads[this.active];
		const n = (t && t.unread) || 0;
		this.$fab
			.find(".ec-fab-badge")
			.toggle(n > 0)
			.text(n > 99 ? "99+" : n);
	}

	// FAB / "mark all read": jump to the newest message and clear the whole thread's unread.
	jump_to_latest() {
		this.$thread.scrollTop(this.$thread[0].scrollHeight);
		this.mark_read();
		this.update_fab();
	}

	// --- new chat ----------------------------------------------------------

	new_chat_dialog() {
		const d = new frappe.ui.Dialog({
			title: __("New chat"),
			fields: [
				{
					fieldname: "people",
					fieldtype: "MultiSelectList",
					label: __("People"),
					reqd: 1,
					get_data: (txt) =>
						frappe.xcall(API + "search_employees", { txt }).then((rows) => {
							if (!rows.length) {
								d.set_df_property(
									"people",
									"description",
									__(
										"No employees found. An Employee must be Active and have a User linked in the field 'User ID'."
									)
								);
							}
							// 🔒 marks people who can already receive an encrypted thread key.
							this.secret_ready = new Set(
								rows.filter((r) => r.secret_ready).map((r) => r.user_id)
							);
							return rows.map((r) => ({
								value: r.user_id,
								description: `${r.employee_name}${r.department ? " · " + r.department : ""}${
									r.secret_ready ? " · 🔒" : ""
								}`,
							}));
						}),
				},
				{
					fieldname: "title",
					fieldtype: "Data",
					label: __("Group name"),
					description: __("Only used when chatting with more than one person"),
				},
				{
					fieldname: "is_secret",
					fieldtype: "Check",
					label: __("Secret chat (end-to-end encrypted)"),
					description: __(
						"Only the participants can read it. Everyone must have secret chats enabled, and the history is lost if the passphrase is forgotten."
					),
				},
			],
			primary_action_label: __("Start"),
			primary_action: async (v) => {
				const people = v.people || [];
				if (!people.length) return;
				const thread_type = people.length > 1 ? "Group" : "Direct";
				const args = {
					participant_users: JSON.stringify(people),
					thread_type,
					title: v.title || null,
				};

				if (v.is_secret) {
					const ready = this.secret_ready || new Set();
					const not_ready = people.filter((u) => !ready.has(u));
					if (not_ready.length) {
						frappe.msgprint(
							__("These people have not enabled secret chats yet: {0}", [not_ready.join(", ")])
						);
						return;
					}
					if (!(await erpnext.chat_crypto.ensure_unlocked())) return;
					// The thread key is generated here and wrapped per participant — the
					// server only ever files the wrapped copies.
					const { wrapped } = await erpnext.chat_crypto.new_thread_key(people.concat([this.me]));
					args.is_secret = 1;
					args.thread_keys = JSON.stringify(wrapped);
				}

				d.hide();
				const res = await frappe.xcall(API + "create_thread", args);
				await this.load_threads();
				this.open(res.name);
			},
		});
		d.show();
	}

	// Add people to the open group. In a secret group the thread key has to be re-wrapped
	// for the newcomer here — the server cannot do it, it never holds the key.
	add_people_dialog() {
		const t = this.threads[this.active];
		if (!t || t.thread_type !== "Group") return;
		const present = new Set((t.participants || []).map((p) => p.user));

		const d = new frappe.ui.Dialog({
			title: __("Add people"),
			fields: [
				{
					fieldname: "people",
					fieldtype: "MultiSelectList",
					label: __("People"),
					reqd: 1,
					get_data: (txt) =>
						frappe.xcall(API + "search_employees", { txt }).then((rows) => {
							this.secret_ready = new Set(
								rows.filter((r) => r.secret_ready).map((r) => r.user_id)
							);
							return rows
								.filter((r) => !present.has(r.user_id))
								.map((r) => ({
									value: r.user_id,
									description: `${r.employee_name}${
										r.department ? " · " + r.department : ""
									}${r.secret_ready ? " · 🔒" : ""}`,
								}));
						}),
				},
			],
			primary_action_label: __("Add"),
			primary_action: async (v) => {
				const people = v.people || [];
				if (!people.length) return;

				let wrapped = [];
				if (t.is_secret) {
					const ready = this.secret_ready || new Set();
					const not_ready = people.filter((u) => !ready.has(u));
					if (not_ready.length) {
						frappe.msgprint(
							__("These people have not enabled secret chats yet: {0}", [not_ready.join(", ")])
						);
						return;
					}
					if (!(await erpnext.chat_crypto.ensure_unlocked())) return;
					const key = await erpnext.chat_crypto.thread_key(this.active);
					wrapped = await erpnext.chat_crypto.wrap_for_users(key, people);
				}

				d.hide();
				for (const user of people) {
					const thread_key = wrapped.find((w) => w.user === user);
					await frappe.xcall(API + "add_participant", {
						thread: this.active,
						user,
						thread_key: thread_key ? JSON.stringify(thread_key) : null,
					});
				}
				await this.load_threads();
				this.set_header(this.threads[this.active]);
				this.show_info();
			},
		});
		d.show();
	}

	// Enrolment, biometric devices, passphrase change. Nothing here can read messages —
	// it only manages the key material that does.
	async secret_settings_dialog() {
		const cc = erpnext.chat_crypto;
		const key = await cc.my_key(true);
		if (!key) return cc.setup_dialog();

		const devices = (key.devices || [])
			.map(
				(dev) =>
					`<li>${frappe.utils.escape_html(dev.label || __("Device"))} — ` +
					`<a href="#" class="ec-revoke" data-name="${dev.name}">${__("Revoke")}</a></li>`
			)
			.join("");

		const d = new frappe.ui.Dialog({
			title: __("Secret chats"),
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "info",
					options:
						`<p>${__("Secret chats are enabled for your account.")}</p>` +
						`<p><b>${__("Devices with biometric unlock")}</b></p>` +
						`<ul>${devices || `<li class="text-muted">${__("None")}</li>`}</ul>` +
						`<p class="text-muted small">${__(
							"Your passphrase never leaves this browser. It cannot be reset — if you forget it, the history is lost."
						)}</p>`,
				},
				{
					fieldtype: "Password",
					fieldname: "new_passphrase",
					label: __("New passphrase"),
					description: __("Leave empty to keep the current one"),
				},
			],
			primary_action_label: __("Save"),
			primary_action: async (v) => {
				if (v.new_passphrase) {
					if (!(await cc.ensure_unlocked())) return;
					await cc.change_passphrase(v.new_passphrase);
					frappe.show_alert({ message: __("Passphrase changed"), indicator: "green" });
				}
				d.hide();
			},
			secondary_action_label: __("Add biometric unlock"),
			secondary_action: async () => {
				if (!(await cc.ensure_unlocked())) return;
				try {
					await cc.register_biometric();
					frappe.show_alert({
						message: __("Biometric unlock enabled"),
						indicator: "green",
					});
					d.hide();
				} catch (e) {
					frappe.msgprint(__("This device does not support biometric unlock"));
				}
			},
		});
		d.$wrapper.on("click", ".ec-revoke", async (e) => {
			e.preventDefault();
			await cc.revoke_biometric($(e.currentTarget).data("name"));
			d.hide();
			frappe.show_alert({ message: __("Device removed"), indicator: "green" });
		});
		d.show();
	}
}
