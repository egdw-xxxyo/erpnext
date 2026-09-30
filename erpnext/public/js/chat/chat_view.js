// The full-page chat screen shared by WhatsApp Chat and Employee Chat.
//
// ChatView owns the screen: conversation list, header, message thread, typing line,
// read-only bar, composer, scroll-to-latest button and the optional side panel. It knows
// nothing about WhatsApp or Employee Chat — everything specific comes from a chat
// source (erpnext/public/js/chat/sources/*.js), which the floating chat bubble uses too.
//
// Source contract (optional members marked ?):
//   key, media_source, list_empty_text?, search_placeholder?
//   tabs?, tab_of?(chat), sidebar_tools_html?(), bind_sidebar_tools?($el, view)
//   load_list() -> [chat]          chat = {id, title, avatar, preview, preview_icon?, time,
//                                   unread, muted, read_only, read_only_reason?, is_archived?,
//                                   list_badge_html?, title_prefix_html?, header_sub?}
//   new_chat?(view), open_request?(view, route_options) -> handled?
//   before_open?(chat, view)       async; e.g. unlock a secret chat
//   placeholder_html?(chat), bind_placeholder?($thread, chat, view)   (nothing to load, e.g. deep archive)
//   prelude_html?(chat)            pinned above the messages (document banner)
//   fetch(chat, {before, after, limit}) -> raw rows oldest-first
//   build(raw, chat) -> normalized messages (see chat_render.js)
//   show_authors?(chat) -> "in" | "out" | "all" | false
//   header_actions?(chat) -> [{icon, title, disabled?, on_click}]
//   header_badges_html?(chat)
//   compose_buttons?(chat) -> [{icon, title, on_click}]
//   send_text(chat, text, reply), attach(chat, {caption, reply, event}), send_voice(chat, rec, reply)
//   react?(chat, msg, emoji), resend?(chat, msg), menu_items?(msg, chat) -> [{icon, label, action}]
//   mark_read(chat, upto) -> {last_read_on}, set_muted(chat, muted), notify_typing?(chat)
//   show_info?(chat, view), side_panel?, render_side?(chat, $el, view)
//   realtime?(view) -> {event: handler}

frappe.provide("erpnext.chat_view");

const CV_PAGE_SIZE = 50;
// Trailing messages re-read on every refresh to pick up status changes (sent → read).
const CV_STATUS_TAIL = 30;

erpnext.chat_view.ChatView = class ChatView {
	constructor(page, source, opts) {
		this.page = page;
		this.source = source;
		this.opts = opts || {};
		this.chats = {}; // id -> chat
		this.active = null;
		this.raw = []; // raw rows of the open chat, oldest first
		this.messages = []; // normalized
		this.msg_by_id = {};
		this.rendered = []; // ids in DOM order
		this.sig = {}; // id -> rendered html, to patch only what changed
		this.reply_to = null;
		this.tab = source.tabs ? source.tabs[0].key : null;
		this.arch_open = localStorage.getItem(`cv_arch_open_${source.key}`) === "1";
		this.typing_sent_at = 0;

		erpnext.chat_render.inject_styles();
		this.inject_styles();
		this.make_layout();
		this.bind_realtime();

		this.poll = setInterval(() => this.refresh(true), 30000);
		this.on_resize = frappe.utils.debounce(() => this.fit_height(), 100);
		$(window).on("resize", this.on_resize);
		$(this.page.wrapper).on("remove", () => this.destroy());
		setTimeout(() => this.fit_height(), 0);

		const ro = frappe.route_options || {};
		frappe.route_options = null;
		this.pending_route = ro;
		this.refresh();
	}

	// Fill the window down to a small bottom gap, whatever the desk header above it
	// measures (it differs between v15, v16 and a page with a filter bar).
	fit_height() {
		const el = this.page.main.find(".cv-page")[0];
		if (!el || !el.offsetParent) return;
		const top = el.getBoundingClientRect().top + window.scrollY;
		el.style.height = `${Math.max(420, window.innerHeight - top - 16)}px`;
	}

	destroy() {
		$(window).off("resize", this.on_resize);
		clearInterval(this.poll);
		for (const [event, handler] of Object.entries(this.rt_handlers || {}))
			frappe.realtime.off(event, handler);
	}

	bind_realtime() {
		this.rt_handlers = this.source.realtime ? this.source.realtime(this) : {};
		for (const [event, handler] of Object.entries(this.rt_handlers)) frappe.realtime.on(event, handler);
	}

	// ------------------------------------------------------------------ layout

	make_layout() {
		const s = this.source;
		this.page.main.html(`
			<div class="cv-root cv-page">
				<div class="cv-sidebar">
					<div class="cv-search">
						<div class="cv-search-row">
							<div class="cv-search-box">
								<i class="fa fa-search"></i>
								<input type="text" class="cv-search-input" placeholder="${frappe.utils.escape_html(
									s.search_placeholder || __("Search")
								)}">
							</div>
							${
								s.new_chat
									? `<button class="cv-ico cv-new-chat" title="${__(
											"New chat"
									  )}"><i class="fa fa-pencil-square-o"></i></button>`
									: ""
							}
						</div>
						<div class="cv-sidebar-tools">${s.sidebar_tools_html ? s.sidebar_tools_html() : ""}</div>
					</div>
					<div class="cv-tabs"></div>
					<div class="cv-list"></div>
				</div>
				<div class="cv-thread-wrap">
					<div class="cv-header"><span class="text-muted">${__("Select a conversation")}</span></div>
					<div class="cv-thread cv-scroll">
						<div class="cv-empty"><i class="fa fa-comments-o"></i><div>${__("Select a conversation")}</div></div>
					</div>
					<div class="cv-fab" title="${__(
						"Scroll to latest"
					)}"><i class="fa fa-chevron-down"></i><span class="cv-fab-badge" style="display:none;"></span></div>
					<div class="cv-typing" style="display:none;"></div>
					<div class="cv-readonly" style="display:none;"></div>
					<div class="cv-compose-wrap" style="display:none;">
						<div class="cv-reply-bar" style="display:none;">
							<i class="fa fa-reply cv-reply-icon"></i>
							<div class="cv-reply-text"></div>
							<span class="cv-reply-cancel" title="${__("Cancel reply")}"><i class="fa fa-times"></i></span>
						</div>
						<div class="cv-compose">
							<button class="cv-ico cv-attach" title="${__("Attach file")}"><i class="fa fa-paperclip"></i></button>
							<span class="cv-extra-tools"></span>
							<textarea rows="1" placeholder="${__("Type a message")}"></textarea>
							<button class="cv-ico cv-emoji" title="${__("Add emoji")}"><i class="fa fa-smile-o"></i></button>
							<button class="cv-ico cv-mic" title="${__("Record voice message")}"><i class="fa fa-microphone"></i></button>
							<button class="cv-ico cv-send" title="${__(
								"Send"
							)}" style="display:none;"><i class="fa fa-paper-plane"></i></button>
						</div>
					</div>
				</div>
				${
					s.side_panel
						? `<div class="cv-side"><div class="text-muted">${__(
								"Select a conversation"
						  )}</div></div>`
						: ""
				}
			</div>
		`);

		const $m = this.page.main;
		this.$root = $m.find(".cv-root");
		this.$list = $m.find(".cv-list");
		this.$tabs = $m.find(".cv-tabs");
		this.$search = $m.find(".cv-search-input");
		this.$header = $m.find(".cv-header");
		this.$thread = $m.find(".cv-thread");
		this.$fab = $m.find(".cv-fab");
		this.$typing = $m.find(".cv-typing");
		this.$readonly = $m.find(".cv-readonly");
		this.$compose = $m.find(".cv-compose-wrap");
		this.$input = $m.find(".cv-compose textarea");
		this.$replyBar = $m.find(".cv-reply-bar");
		this.$tools = $m.find(".cv-extra-tools");
		this.$side = $m.find(".cv-side");

		if (s.bind_sidebar_tools) s.bind_sidebar_tools($m.find(".cv-sidebar-tools"), this);
		$m.find(".cv-new-chat").on("click", () => s.new_chat(this));
		this.$search.on("input", () => this.render_list());
		this.$tabs.on("click", ".cv-tab", (e) => {
			this.tab = $(e.currentTarget).attr("data-tab");
			this.render_list();
		});
		this.$list.on("click", ".cv-arch-head", (e) => {
			const group = $(e.currentTarget).attr("data-group") || "";
			this.set_arch_open(group, !this.is_arch_open(group));
			this.render_list();
		});
		this.$list.on("click", ".cv-conv", (e) => this.open($(e.currentTarget).attr("data-id")));

		this.$fab.on("click", () => this.jump_to_latest());
		$m.find(".cv-send").on("click", () => this.send());
		$m.find(".cv-attach").on("click", (e) => this.attach(e));
		$m.find(".cv-mic").on("click", () => this.record_voice());
		$m.find(".cv-emoji").on("click", (e) => this.emoji_picker(e));
		this.$replyBar.find(".cv-reply-cancel").on("click", () => this.set_reply(null));
		this.$input.on("keydown", (e) => {
			if (e.key === "Enter" && !e.shiftKey) {
				e.preventDefault();
				this.send();
			}
		});
		this.$input.on("input", () => {
			this.autosize();
			this.notify_typing();
		});
		this.$thread.on("scroll", () => {
			if (this.$thread.scrollTop() < 40) this.load_older();
			this.update_read_progress();
			this.update_fab();
			this.close_popovers();
		});
		this.bind_thread_events();
	}

	inject_styles() {
		if (document.getElementById("cv-page-styles-v1")) return;
		const css = `
		.cv-group-head{display:flex;align-items:center;gap:10px;margin:12px 8px 6px;padding:8px 12px 8px 20px;
			position:sticky;top:0;z-index:1;border-radius:10px;background:var(--gray-200,#e2e6e9);
			color:var(--text-color);font-weight:600;font-size:13px;box-shadow:0 1px 0 var(--border-color);}
		.cv-group-head:first-child{margin-top:4px;}
		[data-theme="dark"] .cv-group-head{background:var(--gray-800,#2c3035);}
		.cv-group-head .cv-avatar{flex:none;}
		.cv-group-people{display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px;margin-top:4px;
			font-weight:400;font-size:12px;color:var(--text-muted);}
		.cv-group-people .ent{font-size:12px;color:var(--text-color);}
		.cv-side-ent{display:flex;align-items:center;gap:8px;padding:2px 0 8px;font-size:13px;}
		.cv-side-note{font-size:12px;}
		.cv-side-people{font-size:13px;margin-bottom:8px;}
		.cv-side-people .ent-list{display:flex;flex-direction:column;gap:6px;}
		.cv-group-title{flex:1;min-width:0;}
		.cv-group-title > .ent{font-size:13px;}
		.cv-page{display:flex;height:calc(100vh - 120px);min-height:420px;margin:12px 20px 0;border:1px solid var(--border-color);
			border-radius:var(--border-radius-lg,12px);overflow:hidden;background:var(--card-bg);}
		.cv-sidebar{width:300px;border-right:1px solid var(--border-color);display:flex;flex-direction:column;}
		.cv-search{padding:10px;display:flex;flex-direction:column;gap:6px;}
		.cv-search-row{display:flex;align-items:center;gap:4px;}
		.cv-search-box{flex:1;display:flex;align-items:center;gap:8px;padding:0 12px;height:36px;border-radius:18px;
			background:var(--control-bg);color:var(--text-muted);}
		.cv-search-box input{flex:1;min-width:0;border:none;background:none;outline:none;color:var(--text-color);font-size:var(--text-md);}
		.cv-sidebar-tools:empty{display:none;}
		.cv-sidebar-tools select{border-radius:18px;}
		.cv-tabs{display:flex;gap:4px;padding:0 10px 6px;}
		.cv-tabs:empty{display:none;}
		.cv-tab{flex:1;display:flex;align-items:center;justify-content:center;gap:6px;padding:5px 8px;cursor:pointer;
			border-radius:16px;font-size:var(--text-sm);font-weight:600;color:var(--text-muted);}
		.cv-tab:hover{background:var(--bg-light-gray);}
		.cv-tab.active{background:var(--cv-accent);color:#fff;}
		.cv-tab .cv-badge{min-width:18px;height:18px;line-height:18px;font-size:11px;}
		.cv-tab.active .cv-badge{background:#fff;color:var(--cv-accent);}
		.cv-list{overflow-y:auto;flex:1;padding:0 6px 6px;}
		.cv-conv{display:flex;gap:10px;align-items:center;padding:8px;border-radius:10px;cursor:pointer;}
		.cv-conv:hover{background:var(--bg-light-gray);}
		.cv-conv.active{background:var(--cv-accent);color:#fff;}
		.cv-conv.active .cv-last,.cv-conv.active .cv-list-time{color:rgba(255,255,255,.85);}
		.cv-conv.active .cv-badge{background:#fff;color:var(--cv-accent);}
		.cv-conv.active .cv-via{color:#fff;border-color:rgba(255,255,255,.6);}
		.cv-conv-main{flex:1;min-width:0;}
		.cv-name{font-weight:600;font-size:var(--text-md);display:flex;align-items:baseline;gap:6px;}
		.cv-name .cv-title{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
		.cv-name .fa{font-size:11px;opacity:.6;}
		.cv-list-time{flex:none;font-weight:400;font-size:11px;color:var(--text-muted);}
		.cv-conv-sub{display:flex;align-items:center;gap:6px;margin-top:2px;}
		.cv-last{flex:1;color:var(--text-muted);font-size:var(--text-sm);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
		.cv-conv.cv-unread .cv-last{color:var(--text-color);}
		.cv-badge{flex:none;background:var(--cv-accent);color:#fff;border-radius:11px;min-width:22px;height:22px;line-height:22px;
			text-align:center;font-size:12px;font-weight:600;padding:0 6px;}
		.cv-badge.cv-muted{background:var(--gray-500,#a0a8b0);}
		.cv-via{flex:none;font-size:10px;color:var(--text-muted);border:1px solid var(--border-color);border-radius:8px;padding:0 5px;white-space:nowrap;}
		.cv-arch-head{display:flex;align-items:center;gap:8px;padding:8px 10px;margin-top:4px;border-radius:10px;cursor:pointer;
			font-size:var(--text-sm);font-weight:600;color:var(--text-muted);}
		.cv-arch-head:hover{background:var(--bg-light-gray);color:var(--text-color);}
		.cv-arch-head .cv-badge{margin-left:auto;}
		.cv-arch-group{margin:2px 0 4px 12px;}
		.cv-conv.cv-finished:not(.active){opacity:.55;}
		.cv-conv.cv-finished:not(.active):hover{opacity:.85;}
		.cv-done-mark{color:var(--green-500,#38a169);opacity:1 !important;}
		.cv-conv.active .cv-done-mark{color:#fff;}
		.cv-side{display:flex;flex-direction:column;}
		.cv-side-foot{margin:auto -14px -14px;padding:12px 14px;border-top:1px solid var(--border-color);
			background:var(--card-bg);position:sticky;bottom:-14px;}
		.cv-conv-state{font-size:13px;font-weight:600;margin-bottom:8px;}
		.cv-conv-state .fa{color:var(--text-muted);margin-right:4px;}
		.cv-conv-done .fa-check-circle{color:var(--green-500,#38a169);}
		.cv-conv-state .text-muted{font-weight:400;}
		.cv-conv-by{margin-top:6px;font-weight:400;}
		.cv-conv-actions{display:flex;gap:6px;}
		.cv-conv-main-btn{flex:1;}
		.cv-list-empty{padding:12px;color:var(--text-muted);}
		.cv-thread-wrap{flex:1;display:flex;flex-direction:column;min-width:0;position:relative;background:var(--cv-thread-bg);}
		.cv-header{display:flex;align-items:center;gap:10px;padding:8px 14px;min-height:56px;
			border-bottom:1px solid var(--border-color);background:var(--card-bg);}
		.cv-header-main{flex:1;min-width:0;cursor:pointer;}
		.cv-header-title{font-weight:600;font-size:var(--text-md);color:var(--text-color);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
		.cv-header-main:hover .cv-header-title{color:var(--cv-accent);}
		.cv-header-sub{font-size:var(--text-sm);color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
		.cv-header-sub .cv-typing-sub{color:var(--cv-accent);}
		.cv-chip{display:inline-flex;align-items:center;gap:4px;margin-left:6px;padding:0 6px;border-radius:8px;
			background:var(--bg-light-gray);color:var(--text-color);font-size:11px;font-weight:500;}
		.cv-chip .fa-whatsapp{color:#25d366;}
		.cv-header .cv-ico{width:32px;height:32px;line-height:32px;font-size:16px;}
		.cv-thread{flex:1;overflow-y:auto;padding:12px 8%;position:relative;}
		.cv-empty{margin:auto;text-align:center;color:var(--text-muted);}
		.cv-empty .fa{font-size:48px;opacity:.35;margin-bottom:8px;}
		.cv-fab{position:absolute;right:20px;bottom:84px;z-index:5;width:44px;height:44px;border-radius:50%;background:var(--card-bg);
			box-shadow:0 2px 8px rgba(0,0,0,.2);cursor:pointer;display:none;align-items:center;justify-content:center;font-size:16px;color:var(--text-muted);}
		.cv-fab:hover{color:var(--text-color);}
		.cv-fab.show{display:flex;}
		.cv-fab-badge{position:absolute;top:-6px;right:-4px;min-width:20px;height:20px;padding:0 6px;border-radius:10px;
			background:var(--cv-accent);color:#fff;font-size:11px;line-height:20px;text-align:center;font-weight:600;}
		.cv-typing{padding:3px 16px;font-size:12px;font-style:italic;color:var(--cv-accent);background:var(--cv-thread-bg);}
		.cv-readonly{background:var(--card-bg);border-top:1px solid var(--border-color);padding:12px 16px;color:var(--text-muted);
			text-align:center;font-size:13px;}
		.cv-compose-wrap{background:var(--card-bg);border-top:1px solid var(--border-color);}
		.cv-reply-bar{display:flex;align-items:center;gap:10px;padding:6px 14px 0;font-size:13px;}
		.cv-reply-icon{color:var(--cv-accent);font-size:16px;}
		.cv-reply-text{border-left:2px solid var(--cv-accent);padding-left:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;}
		.cv-reply-cancel{cursor:pointer;color:var(--text-muted);font-size:15px;padding:4px;}
		.cv-reply-cancel:hover{color:var(--text-color);}
		.cv-compose{display:flex;gap:2px;padding:8px 10px;align-items:flex-end;}
		.cv-extra-tools{display:contents;}
		.cv-compose textarea{flex:1;min-width:0;resize:none;border:none;outline:none;box-shadow:none;background:none;
			color:var(--text-color);font-size:14px;line-height:20px;padding:8px 6px;max-height:180px;overflow-y:auto;}
		.cv-side{width:280px;border-left:1px solid var(--border-color);overflow-y:auto;padding:14px;}
		.cv-side h6{margin:16px 0 6px;font-size:var(--text-xs,11px);text-transform:uppercase;color:var(--text-muted);letter-spacing:.06em;}
		.cv-side h6:first-child{margin-top:0;}
		.cv-ent{display:flex;align-items:center;justify-content:space-between;padding:7px 10px;border-radius:8px;margin-bottom:4px;
			font-size:var(--text-sm);background:var(--bg-light-gray);}
		.cv-ent-main{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
		.cv-ent-main[data-dt]{cursor:pointer;}
		.cv-ent-main[data-dt]:hover{color:var(--cv-accent);}
		.cv-ent-sub{color:var(--text-muted);font-size:10px;}
		.cv-unlink{cursor:pointer;color:var(--text-muted);margin-left:6px;}
		.cv-unlink:hover{color:var(--red-500);}
		.cv-side-actions{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;}
		.cv-side-actions .btn .fa{margin-right:4px;color:var(--text-muted);}
		@media (max-width:1200px){.cv-side{display:none;}}
		@media (max-width:768px){.cv-sidebar{width:220px;}.cv-thread{padding:10px;}}
		`;
		$(`<style id="cv-page-styles-v1">${css}</style>`).appendTo(document.head);
	}

	// ------------------------------------------------------------------ list

	async refresh(silent) {
		let list;
		try {
			list = await this.source.load_list();
		} catch (e) {
			return;
		}
		const next = {};
		for (const c of list) next[c.id] = c;
		// A chat just started from a number has no row until its first message.
		if (this.active && !next[this.active] && this.chats[this.active])
			next[this.active] = this.chats[this.active];
		this.chats = next;
		this.loaded = true;
		this.render_list();
		if (this.active && this.chats[this.active]) {
			this.render_header();
			this.render_composer();
			if (!this.placeholder_active) await this.load_new(!silent);
		}
		this.handle_pending_route();
	}

	// Deep links wait for the first list load — the chat has to be known to open it.
	route_to(ro) {
		this.pending_route = ro || {};
		if (this.loaded) this.handle_pending_route();
	}

	handle_pending_route() {
		const ro = this.pending_route;
		if (!ro || !this.loaded) return;
		this.pending_route = null;
		if (this.source.open_request && this.source.open_request(this, ro)) return;
		const id =
			ro.chat || ro.thread || frappe.utils.get_url_arg("chat") || frappe.utils.get_url_arg("thread");
		if (id && this.chats[id]) this.open(id);
	}

	// Open a chat that may not be in the list yet (just created).
	async open_new(id) {
		await this.refresh(true);
		if (this.chats[id]) this.open(id);
	}

	visible_chats() {
		const s = this.source;
		let list = Object.values(this.chats);
		if (s.tabs && s.tab_of) list = list.filter((c) => s.tab_of(c) === this.tab);
		const q = (this.$search.val() || "").trim().toLowerCase();
		if (q) {
			list = list.filter((c) =>
				[c.title, c.search_text].some((v) => v && String(v).toLowerCase().includes(q))
			);
		}
		return list.sort((a, b) => (b.time || "").localeCompare(a.time || ""));
	}

	render_tabs() {
		const s = this.source;
		if (!s.tabs) return;
		const all = Object.values(this.chats);
		this.$tabs.html(
			s.tabs
				.map((t) => {
					const unread = all
						.filter((c) => s.tab_of(c) === t.key)
						.reduce((n, c) => n + (c.unread || 0), 0);
					return `<div class="cv-tab ${t.key === this.tab ? "active" : ""}" data-tab="${t.key}">
						<span>${frappe.utils.escape_html(t.label)}</span>${
						unread ? `<span class="cv-badge">${unread > 99 ? "99+" : unread}</span>` : ""
					}</div>`;
				})
				.join("")
		);
	}

	conv_html(c) {
		const R = erpnext.chat_render;
		const esc = frappe.utils.escape_html;
		const badge = c.unread
			? `<span class="cv-badge ${c.muted ? "cv-muted" : ""}">${c.unread > 99 ? "99+" : c.unread}</span>`
			: "";
		const muted = c.muted ? `<i class="fa fa-bell-slash-o"></i>` : "";
		const preview = esc((c.preview || "").replace(/<[^>]*>/g, "").slice(0, 80));
		const done = c.is_finished
			? `<i class="fa fa-check-circle cv-done-mark" title="${__("Conversation finished")}"></i>`
			: "";
		return `<div class="cv-conv ${c.id === this.active ? "active" : ""} ${c.unread ? "cv-unread" : ""} ${
			c.is_finished ? "cv-finished" : ""
		}" data-id="${esc(c.id)}">
			${R.avatar_html(c.avatar || { name: c.title, key: c.id })}
			<div class="cv-conv-main">
				<div class="cv-name">${c.title_prefix_html || ""}<span class="cv-title">${esc(
			c.title
		)}</span>${done}${muted}<span class="cv-list-time">${R.list_time(c.time)}</span></div>
				<div class="cv-conv-sub"><span class="cv-last">${c.preview_icon || ""}${
			preview || `<i>${__("No messages yet")}</i>`
		}</span>${c.list_badge_html || ""}${badge}</div>
			</div>
		</div>`;
	}

	render_list() {
		this.render_tabs();
		const list = this.visible_chats();
		const active = list.filter((c) => !c.is_archived);
		const archived = list.filter((c) => c.is_archived);
		if (!list.length) {
			this.$list.html(
				`<div class="cv-list-empty">${
					this.source.list_empty_text || __("No conversations yet")
				}</div>`
			);
			return;
		}
		// A source may split the list into groups under a header (WhatsApp: per number);
		// each group then folds its own archived chats.
		const html = this.source.list_groups
			? this.source
					.list_groups(list)
					.map((g) => {
						const own = g.chats.filter((c) => c.is_archived);
						const rest = g.chats.filter((c) => !c.is_archived);
						return (
							g.html +
							rest.map((c) => this.conv_html(c)).join("") +
							this.archive_html(own, g.key)
						);
					})
					.join("")
			: active.map((c) => this.conv_html(c)).join("") + this.archive_html(archived, "");
		this.$list.html(html);
	}

	// Archived chats keep receiving messages, so the collapsed header carries their unread.
	archive_html(chats, group) {
		if (!chats.length) return "";
		const esc = frappe.utils.escape_html;
		const open = this.is_arch_open(group || "");
		const unread = chats.reduce((n, c) => n + (c.unread || 0), 0);
		const s = this.source;
		return `<div class="cv-arch-head${group ? " cv-arch-group" : ""}" data-group="${esc(
			group || ""
		)}" title="${esc(s.archive_hint || "")}"><i class="fa fa-caret-${open ? "down" : "right"}"></i>
			<i class="fa fa-archive"></i><span>${esc(s.archive_label || __("Archived"))}</span>
			<span class="text-muted">${chats.length}</span>
			${unread ? `<span class="cv-badge">${unread > 99 ? "99+" : unread}</span>` : ""}</div>${
			open ? chats.map((c) => this.conv_html(c)).join("") : ""
		}`;
	}

	arch_key(group) {
		return `cv_arch_open_${this.source.key}${group ? "_" + group : ""}`;
	}

	is_arch_open(group) {
		if (!group) return this.arch_open;
		try {
			return localStorage.getItem(this.arch_key(group)) === "1";
		} catch (e) {
			return false;
		}
	}

	set_arch_open(group, open) {
		if (!group) this.arch_open = open;
		try {
			localStorage.setItem(this.arch_key(group), open ? "1" : "0");
		} catch (e) {
			// Private mode: the state lives until the next render only.
		}
	}

	// ------------------------------------------------------------------ open

	chat() {
		return this.chats[this.active];
	}

	async open(id) {
		const chat = this.chats[id];
		if (!chat) return;
		const s = this.source;
		this.active = id;
		if (s.tabs && s.tab_of) this.tab = s.tab_of(chat);
		this.set_reply(null);
		this.hide_typing();
		this.raw = [];
		this.messages = [];
		this.msg_by_id = {};
		this.all_loaded = false;
		this.read_cursor = chat.my_last_read || null;
		this.render_list();
		this.render_header();
		this.render_composer();
		this.render_side();
		this.$thread.empty();

		if (s.before_open) {
			await s.before_open(chat, this);
			if (this.active !== id) return;
			this.render_header();
		}

		const placeholder = s.placeholder_html && s.placeholder_html(chat);
		this.placeholder_active = !!placeholder;
		if (placeholder) {
			this.render_placeholder();
			return;
		}
		await this.load_page();
	}

	render_placeholder() {
		const chat = this.chat();
		this.rendered = [];
		this.sig = {};
		this.$thread.html(
			(this.source.prelude_html ? this.source.prelude_html(chat) : "") +
				this.source.placeholder_html(chat)
		);
		if (this.source.bind_placeholder) this.source.bind_placeholder(this.$thread, chat, this);
		this.update_fab();
	}

	// The chat's state changed (archive restored, unlocked…): reload it in place.
	reopen() {
		if (this.active) this.open(this.active);
	}

	forget(id) {
		delete this.chats[id];
		if (this.active === id) {
			this.active = null;
			this.$thread.html(
				`<div class="cv-empty"><i class="fa fa-comments-o"></i><div>${__(
					"Select a conversation"
				)}</div></div>`
			);
			this.$header.html(`<span class="text-muted">${__("Select a conversation")}</span>`);
			this.$compose.hide();
			this.$readonly.hide();
			this.$side.html("");
		}
		this.render_list();
	}

	// ------------------------------------------------------------------ header / composer / side

	render_header() {
		const chat = this.chat();
		if (!chat) return;
		const R = erpnext.chat_render;
		const s = this.source;
		const actions = (s.header_actions ? s.header_actions(chat) : []) || [];
		this.$header.html(`${R.avatar_html(chat.avatar || { name: chat.title, key: chat.id }, 38)}
			<div class="cv-header-main" title="${__("Chat info")}">
				<div class="cv-header-title"></div>
				<div class="cv-header-sub"></div>
			</div>
			${s.header_badges_html ? s.header_badges_html(chat) : ""}
			${actions
				.map(
					(a, i) =>
						`<button class="cv-ico cv-hact${
							a.disabled ? " cv-disabled" : ""
						}" data-i="${i}" title="${frappe.utils.escape_html(a.title || "")}"><i class="${
							a.icon
						}"></i></button>`
				)
				.join("")}
			${erpnext.chat_sound.button_html(chat.muted)}
			${
				s.show_info
					? `<button class="cv-ico cv-info-btn" title="${__(
							"Chat info"
					  )}"><i class="fa fa-info-circle"></i></button>`
					: ""
			}`);
		this.$header
			.find(".cv-header-title")
			.html(`${chat.title_prefix_html || ""}${frappe.utils.escape_html(chat.title)}`);
		this.$sub = this.$header.find(".cv-header-sub");
		this.$sub.html(chat.header_sub || "");
		this.$header.find(".cv-hact").on("click", (e) => {
			const a = actions[$(e.currentTarget).data("i")];
			if (a && !a.disabled) a.on_click();
		});
		if (s.show_info)
			this.$header.find(".cv-header-main, .cv-info-btn").on("click", () => s.show_info(chat, this));
		if (s.open_profile)
			this.$header
				.children(".cv-avatar")
				.first()
				.css("cursor", "pointer")
				.attr("title", __("Open profile"))
				.on("click", () => s.open_profile(chat, this));
		this.$header.find(".chat-mute-btn").on("click", () => this.toggle_mute());
	}

	render_composer() {
		const chat = this.chat();
		if (!chat) return;
		if (chat.read_only) {
			this.$compose.hide();
			this.$readonly.text(chat.read_only_reason || __("This chat is read only")).show();
			return;
		}
		this.$readonly.hide();
		this.$compose.show();
		const buttons = (this.source.compose_buttons ? this.source.compose_buttons(chat) : []) || [];
		this.$tools.html(
			buttons
				.map(
					(b, i) =>
						`<button class="cv-ico" data-i="${i}" title="${frappe.utils.escape_html(
							b.title
						)}"><i class="${b.icon}"></i></button>`
				)
				.join("")
		);
		this.$tools.find(".cv-ico").on("click", (e) => buttons[$(e.currentTarget).data("i")].on_click(this));
	}

	render_side() {
		if (!this.source.side_panel || !this.$side.length) return;
		const chat = this.chat();
		if (!chat) return;
		this.source.render_side(chat, this.$side, this);
	}

	async toggle_mute() {
		const chat = this.chat();
		if (!chat) return;
		const muted = chat.muted ? 0 : 1;
		chat.muted = muted;
		this.render_header();
		this.render_list();
		try {
			await this.source.set_muted(chat, muted);
		} catch (e) {
			chat.muted = muted ? 0 : 1;
			this.render_header();
			return;
		}
		frappe.show_alert({ message: muted ? __("Chat muted") : __("Chat unmuted"), indicator: "blue" });
	}

	// ------------------------------------------------------------------ messages

	async fetch(opts) {
		return this.source.fetch(this.chat(), opts || {});
	}

	rebuild() {
		this.messages = this.source.build(this.raw, this.chat());
		this.msg_by_id = {};
		for (const m of this.messages) this.msg_by_id[m.id] = m;
	}

	async load_page() {
		const id = this.active;
		const rows = await this.fetch({ limit: CV_PAGE_SIZE });
		if (this.active !== id) return;
		this.raw = rows;
		this.all_loaded = rows.length < CV_PAGE_SIZE;
		this.rebuild();
		// Anchor the "New messages" divider once per open; it stays put while reading.
		this.new_divider_before = this.first_unread_id();
		this.render_thread(true);
		this.scroll_to_start();
	}

	async load_older() {
		if (
			!this.active ||
			this.loading_older ||
			this.all_loaded ||
			!this.raw.length ||
			this.placeholder_active
		)
			return false;
		this.loading_older = true;
		const id = this.active;
		try {
			const older = await this.fetch({ before: this.raw[0].creation, limit: CV_PAGE_SIZE });
			if (this.active !== id) return false;
			if (older.length < CV_PAGE_SIZE) this.all_loaded = true;
			if (!older.length) return false;
			const prev_h = this.$thread[0].scrollHeight;
			const prev_top = this.$thread.scrollTop();
			this.raw = older.concat(this.raw);
			this.rebuild();
			this.render_thread(true);
			this.$thread.scrollTop(this.$thread[0].scrollHeight - prev_h + prev_top);
			return true;
		} finally {
			this.loading_older = false;
		}
	}

	// Whatever arrived since the newest loaded message, plus a re-read of the recent tail:
	// outgoing messages change status (sent → delivered → read / failed) after loading.
	async load_new(force_scroll) {
		if (!this.active || this.placeholder_active) return;
		if (!this.raw.length) return this.load_page();
		const id = this.active;
		const el = this.$thread[0];
		const at_bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
		const tail = this.raw.slice(-CV_STATUS_TAIL);
		const fresh = await this.fetch({ after: tail[0].creation, limit: 200 });
		if (this.active !== id) return;
		this.merge(fresh);
		const grew = this.render_thread(false);
		if (force_scroll || (grew && at_bottom)) this.$thread.scrollTop(el.scrollHeight);
		if (grew) {
			if (force_scroll || at_bottom) this.update_read_progress();
			else this.recount_unread();
		}
		this.update_fab();
	}

	// Fold rows into the loaded history (replace same name, append new, keep order).
	merge(rows) {
		const index = {};
		this.raw.forEach((r, i) => (index[r.name] = i));
		let appended = false;
		for (const r of rows || []) {
			if (index[r.name] === undefined) {
				this.raw.push(r);
				index[r.name] = this.raw.length - 1;
				appended = true;
			} else {
				this.raw[index[r.name]] = r;
			}
		}
		if (appended) this.raw.sort((a, b) => (a.creation || "").localeCompare(b.creation || ""));
		this.rebuild();
	}

	// A row pushed by realtime (own echo or someone else's message).
	push(row) {
		if (!row || !row.name || !this.active) return;
		this.merge([row]);
		const el = this.$thread[0];
		const at_bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
		const mine = this.msg_by_id[row.name] && this.msg_by_id[row.name].out;
		this.render_thread(false);
		if (at_bottom || mine) {
			this.$thread.scrollTop(el.scrollHeight);
			this.update_read_progress();
		} else {
			this.recount_unread();
		}
		this.update_fab();
	}

	// Redraw one message after its row changed in place (reaction, status).
	patch(row) {
		if (!row || !row.name || !this.raw.some((r) => r.name === row.name)) return;
		this.merge([row]);
		this.render_thread(false);
	}

	author_mode() {
		return this.source.show_authors ? this.source.show_authors(this.chat()) : false;
	}

	bubble(m) {
		const mode = this.author_mode();
		const author = mode === "all" || (mode === "in" && !m.out) || (mode === "out" && m.out);
		return erpnext.chat_render.bubble_html(m, { author, actions: true });
	}

	day_of(m) {
		return m && m.time ? erpnext.chat_render.local(m.time).format("YYYY-MM-DD") : "";
	}

	day_html(m) {
		return `<div class="cv-day">${frappe.utils.escape_html(
			erpnext.chat_render.day_label(erpnext.chat_render.local(m.time))
		)}</div>`;
	}

	// Full render when the history changed shape (opened, older page, removal);
	// otherwise only changed bubbles are swapped and new ones appended — no flicker,
	// and whatever text the reader has selected stays selected. Returns true when
	// new messages were appended.
	render_thread(full) {
		this.close_popovers();
		const msgs = this.messages;
		const ids = msgs.map((m) => m.id);
		const prev = this.rendered;
		const append_only =
			!full && prev.length > 0 && prev.length <= ids.length && prev.every((id, i) => ids[i] === id);

		if (!append_only) {
			const chat = this.chat();
			const parts = [this.source.prelude_html ? this.source.prelude_html(chat) : ""];
			this.sig = {};
			let last_day = null;
			for (const m of msgs) {
				const day = this.day_of(m);
				if (day !== last_day) {
					last_day = day;
					parts.push(this.day_html(m));
				}
				if (this.new_divider_before && m.id === this.new_divider_before) {
					parts.push(`<div class="cv-new-divider">${__("New messages")}</div>`);
				}
				const html = this.bubble(m);
				this.sig[m.id] = html;
				parts.push(html);
			}
			if (!msgs.length) {
				parts.push(
					`<div class="cv-empty"><i class="fa fa-comments-o"></i><div>${__(
						"No messages yet"
					)}</div></div>`
				);
			}
			this.$thread.html(parts.join(""));
			this.rendered = ids;
			erpnext.chat_render.bind(this.$thread, this.source.media_source);
			return false;
		}

		const fresh = [];
		for (let i = 0; i < prev.length; i++) {
			const m = msgs[i];
			const html = this.bubble(m);
			if (this.sig[m.id] === html) continue;
			this.sig[m.id] = html;
			const $old = this.$bubble(m.id);
			if (!$old) continue;
			const $new = $(html);
			$old.replaceWith($new);
			fresh.push($new[0]);
		}
		this.$thread.find(".cv-empty").remove();
		for (let i = prev.length; i < msgs.length; i++) {
			const m = msgs[i];
			if (this.day_of(m) !== this.day_of(msgs[i - 1])) this.$thread.append(this.day_html(m));
			const html = this.bubble(m);
			this.sig[m.id] = html;
			const $new = $(html).appendTo(this.$thread);
			fresh.push($new[0]);
		}
		this.rendered = ids;
		if (fresh.length) erpnext.chat_render.bind($(fresh), this.source.media_source);
		return msgs.length > prev.length;
	}

	$bubble(id) {
		const el = this.$thread[0].querySelector(`.cv-bubble[data-id="${CSS.escape(id)}"]`);
		return el ? $(el) : null;
	}

	msg_of(el) {
		return this.msg_by_id[$(el).closest(".cv-bubble").attr("data-id")];
	}

	bind_thread_events() {
		const $t = this.$thread;
		$t.on("click", ".cv-do-reply", (e) => this.reply_to_msg(this.msg_of(e.currentTarget)));
		$t.on("click", ".cv-do-react", (e) => this.react_popover(e));
		$t.on("click", ".cv-do-menu", (e) => {
			e.stopPropagation();
			this.message_menu(e.currentTarget);
		});
		$t.on("keydown", ".cv-do-menu", (e) => {
			if (e.key === "Enter" || e.key === " ") {
				e.preventDefault();
				this.message_menu(e.currentTarget);
			}
		});
		$t.on("click", ".cv-react-badge", (e) => {
			const m = this.msg_of(e.currentTarget);
			if (m && this.source.react && !this.chat().read_only)
				this.react(m, $(e.currentTarget).attr("data-emoji"));
		});
		$t.on("click", ".cv-resend", (e) => this.resend(this.msg_of(e.currentTarget)));
		$t.on("click", ".cv-quote[data-target]", (e) =>
			this.jump_to_message($(e.currentTarget).attr("data-target"))
		);
		$t.on("click", ".cv-ref-banner[data-dt]", (e) =>
			frappe.set_route("Form", $(e.currentTarget).attr("data-dt"), $(e.currentTarget).attr("data-name"))
		);
	}

	// ------------------------------------------------------------------ reading

	first_unread_id() {
		const cursor = this.read_cursor;
		const m = this.messages.find((x) => x.incoming && (!cursor || x.time > cursor));
		return m ? m.id : null;
	}

	// On open: land on the first unread message (divider just above) if any, else the bottom.
	scroll_to_start() {
		const divider = this.$thread.find(".cv-new-divider")[0];
		if (divider) this.$thread.scrollTop(Math.max(0, divider.offsetTop - 60));
		else this.$thread.scrollTop(this.$thread[0].scrollHeight);
		this.update_read_progress();
		this.update_fab();
	}

	// Progressive read-on-scroll: an unread incoming message whose top scrolled into view
	// counts as seen. The cursor only moves forward; one server call per scroll gesture.
	update_read_progress() {
		if (!this.active || this.placeholder_active) return;
		const el = this.$thread[0];
		const bottom_edge = el.scrollTop + el.clientHeight;
		let newest = this.read_cursor || "";
		for (const b of el.querySelectorAll(".cv-bubble.cv-in")) {
			const m = this.msg_by_id[b.getAttribute("data-id")];
			if (!m || !m.incoming) continue;
			if (b.offsetTop < bottom_edge && m.time > newest) newest = m.time;
		}
		if (newest && newest > (this.read_cursor || "")) {
			this.read_cursor = newest;
			this.recount_unread();
			clearTimeout(this._read_timer);
			const upto = newest;
			const chat = this.chat();
			this._read_timer = setTimeout(() => this.mark_read(chat, upto), 350);
		}
	}

	async mark_read(chat, upto) {
		if (!chat) return;
		try {
			const res = await this.source.mark_read(chat, upto || null);
			const cursor = (res && res.last_read_on) || upto || frappe.datetime.now_datetime();
			chat.my_last_read = cursor;
			if (chat.id === this.active && (!this.read_cursor || cursor > this.read_cursor))
				this.read_cursor = cursor;
			this.recount_unread();
		} catch (e) {
			// non-fatal — the badge reappears on the next poll
		}
	}

	recount_unread() {
		const chat = this.chat();
		if (!chat) return;
		const cursor = this.read_cursor;
		chat.unread = this.messages.filter((m) => m.incoming && (!cursor || m.time > cursor)).length;
		this.render_list();
		this.update_fab();
	}

	update_fab() {
		const el = this.$thread[0];
		if (!el || !this.active) return this.$fab.removeClass("show");
		const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
		this.$fab.toggleClass("show", dist > 120);
		const n = (this.chat() && this.chat().unread) || 0;
		this.$fab
			.find(".cv-fab-badge")
			.toggle(n > 0)
			.text(n > 99 ? "99+" : n);
	}

	jump_to_latest() {
		this.$thread.scrollTop(this.$thread[0].scrollHeight);
		this.mark_read(this.chat());
		this.update_fab();
	}

	// Scroll a message into view (paging older history in if needed) and flash it.
	async jump_to_message(id) {
		if (!id) return;
		let $b = this.$bubble(id);
		let guard = 0;
		while (!$b && guard++ < 30) {
			if (!(await this.load_older())) break;
			$b = this.$bubble(id);
		}
		if (!$b) {
			frappe.show_alert({ message: __("Message not found"), indicator: "orange" });
			return;
		}
		$b[0].scrollIntoView({ behavior: "smooth", block: "center" });
		$b.addClass("cv-highlight");
		setTimeout(() => $b.removeClass("cv-highlight"), 1700);
	}

	// ------------------------------------------------------------------ typing

	show_typing(text) {
		this.$typing.text(text).show();
		if (this.$sub) this.$sub.html(`<span class="cv-typing-sub">${frappe.utils.escape_html(text)}</span>`);
		clearTimeout(this.typing_timer);
		this.typing_timer = setTimeout(() => this.hide_typing(), 4000);
	}

	hide_typing() {
		clearTimeout(this.typing_timer);
		this.$typing.hide().text("");
		const chat = this.chat();
		if (this.$sub && chat) this.$sub.html(chat.header_sub || "");
	}

	notify_typing() {
		const chat = this.chat();
		if (!chat || chat.read_only || !this.source.notify_typing || !(this.$input.val() || "").trim())
			return;
		const now = Date.now();
		if (now - this.typing_sent_at < 2500) return;
		this.typing_sent_at = now;
		this.source.notify_typing(chat);
	}

	// ------------------------------------------------------------------ compose

	autosize() {
		const el = this.$input[0];
		el.style.height = "auto";
		el.style.height = el.scrollHeight + "px";
		const has_text = !!(this.$input.val() || "").trim();
		this.page.main.find(".cv-send").toggle(has_text);
		this.page.main.find(".cv-mic").toggle(!has_text);
	}

	set_reply(reply) {
		this.reply_to = reply;
		if (reply) {
			this.$replyBar
				.find(".cv-reply-text")
				.text(`${__("Replying to")}: ${(reply.text || "").slice(0, 80)}`);
			this.$replyBar.show();
			this.$input.focus();
		} else {
			this.$replyBar.hide();
		}
	}

	reply_to_msg(m) {
		if (!m || this.chat().read_only) return;
		this.set_reply({ id: m.reply_key || m.id, text: erpnext.chat_render.preview_text(m) });
	}

	take_reply() {
		const r = this.reply_to;
		this.set_reply(null);
		return r;
	}

	// Run a send and refresh; `restore` puts the text back on failure.
	async run_send(fn, fail_msg, restore) {
		try {
			const row = await fn();
			if (row && row.name) this.push(row);
			await this.load_new(true);
			this.refresh_list_soon();
		} catch (e) {
			if (restore !== undefined) {
				this.$input.val(restore);
				this.autosize();
			}
			if (!(e && e._server_messages)) frappe.msgprint(fail_msg || __("Failed to send message"));
		}
	}

	send() {
		const chat = this.chat();
		const text = (this.$input.val() || "").trim();
		if (!chat || !text || chat.read_only) return;
		this.$input.val("");
		this.autosize();
		const reply = this.take_reply();
		return this.run_send(
			() => this.source.send_text(chat, text, reply),
			__("Failed to send message"),
			text
		);
	}

	attach(e) {
		const chat = this.chat();
		if (!chat || chat.read_only) return;
		const caption = (this.$input.val() || "").trim();
		const reply = this.reply_to;
		this.source.attach(chat, {
			caption,
			reply,
			event: e,
			view: this,
			done: (row) => {
				this.$input.val("");
				this.autosize();
				this.set_reply(null);
				if (row && row.name) this.push(row);
				this.load_new(true);
				this.refresh_list_soon();
			},
		});
	}

	async record_voice() {
		const chat = this.chat();
		if (!chat || chat.read_only) return;
		const rec = await erpnext.chat_media.record_audio();
		if (!rec) return;
		const reply = this.take_reply();
		frappe.dom.freeze(__("Sending…"));
		try {
			await this.run_send(
				() => this.source.send_voice(chat, rec, reply),
				__("Failed to send voice message")
			);
		} finally {
			frappe.dom.unfreeze();
		}
	}

	async react(m, emoji) {
		try {
			const row = await this.source.react(this.chat(), m, emoji);
			if (row && row.name) this.patch(row);
			else await this.load_new(false);
		} catch (e) {
			frappe.msgprint(__("Failed to react"));
		}
	}

	async resend(m) {
		if (!m || !this.source.resend) return;
		frappe.dom.freeze(__("Resending..."));
		try {
			await this.run_send(() => this.source.resend(this.chat(), m), __("Failed to resend"));
		} finally {
			frappe.dom.unfreeze();
		}
	}

	refresh_list_soon() {
		clearTimeout(this._list_timer);
		this._list_timer = setTimeout(() => this.refresh(true), 400);
	}

	// ------------------------------------------------------------------ popovers

	close_popovers() {
		$(".cv-pop").remove();
		this.$thread.find(".cv-menu-open").removeClass("cv-menu-open");
		$(document).off("click.cvpop keydown.cvpop");
	}

	popover(html, anchor, place) {
		this.close_popovers();
		const $pop = $(html).addClass("cv-pop").appendTo("body");
		const off = $(anchor).offset();
		const top =
			place === "above" ? off.top - $pop.outerHeight() - 8 : off.top + $(anchor).outerHeight() + 4;
		let left = off.left;
		const overflow = left + $pop.outerWidth() - $(window).width() + 8;
		if (overflow > 0) left -= overflow;
		$pop.css({ top: Math.max(4, top), left: Math.max(4, left) });
		setTimeout(() => {
			$(document).on("click.cvpop", (e) => {
				if (!$(e.target).closest(".cv-pop").length) this.close_popovers();
			});
			$(document).on("keydown.cvpop", (e) => {
				if (e.key === "Escape") this.close_popovers();
			});
		}, 0);
		return $pop;
	}

	react_popover(e) {
		e.stopPropagation();
		const m = this.msg_of(e.currentTarget);
		if (!m) return;
		const $pop = this.popover(
			`<div class="cv-react-pop">${erpnext.chat_render.QUICK_REACTIONS.map(
				(x) => `<span data-e="${x}">${x}</span>`
			).join("")}</div>`,
			e.currentTarget,
			"above"
		);
		$pop.find("span").on("click", (ev) => {
			const emoji = $(ev.currentTarget).attr("data-e");
			this.close_popovers();
			this.react(m, emoji);
		});
	}

	emoji_picker(e) {
		e.stopPropagation();
		const $pop = this.popover(
			`<div class="cv-emoji-pop">${erpnext.chat_render.EMOJI_SET.map((x) => `<span>${x}</span>`).join(
				""
			)}</div>`,
			e.currentTarget,
			"above"
		);
		$pop.find("span").on("click", (ev) => {
			const el = this.$input[0];
			const emoji = $(ev.currentTarget).text();
			const start = el.selectionStart || 0;
			const val = this.$input.val();
			this.$input.val(val.slice(0, start) + emoji + val.slice(el.selectionEnd || start));
			this.autosize();
			this.close_popovers();
			el.focus();
			el.selectionStart = el.selectionEnd = start + emoji.length;
		});
	}

	message_menu(trigger) {
		const m = this.msg_of(trigger);
		if (!m) return;
		const chat = this.chat();
		const items = [
			{
				icon: "fa fa-files-o",
				label: __("Copy message"),
				action: () => {
					const text = erpnext.chat_render.copy_text(m);
					if (!text)
						return frappe.show_alert({ message: __("Nothing to copy"), indicator: "orange" });
					frappe.utils.copy_to_clipboard(text);
				},
			},
		];
		if (m.can_reply && !chat.read_only) {
			items.push({
				icon: "fa fa-reply",
				label: __("Reply to message"),
				action: () => this.reply_to_msg(m),
			});
		}
		if (m.quote && m.reply_target) {
			items.push({
				icon: "fa fa-level-up",
				label: __("Go to replied message"),
				action: () => this.jump_to_message(m.reply_target),
			});
		}
		if (this.source.menu_items) items.push(...(this.source.menu_items(m, chat, this) || []));
		const $pop = this.popover(
			`<div class="cv-menu">${items
				.map(
					(it, i) =>
						`<div class="cv-menu-item" data-i="${i}"><i class="${
							it.icon
						}"></i>${frappe.utils.escape_html(it.label)}</div>`
				)
				.join("")}</div>`,
			trigger
		);
		$(trigger).closest(".cv-bubble").addClass("cv-menu-open");
		$pop.find(".cv-menu-item").on("click", (e) => {
			const it = items[$(e.currentTarget).data("i")];
			this.close_popovers();
			it.action();
		});
	}
};

// What "copy" puts on the clipboard: the words of the message; for an attachment without
// a caption its address, the only useful thing to paste.
erpnext.chat_render.copy_text = function (m) {
	if (m.is_encrypted) {
		if (!m.dec) return "";
		return (m.dec.text || (m.dec.link && m.dec.link.url) || "").trim();
	}
	const text = (m.text || "").replace(/<[^>]*>/g, "").trim();
	if (text) return text;
	if (m.content_type === "link" && m.link_data) return m.link_data.url || "";
	if (m.attach) return frappe.urllib.get_full_url(m.attach);
	return "";
};
