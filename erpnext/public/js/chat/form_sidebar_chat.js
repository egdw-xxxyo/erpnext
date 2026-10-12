// Form sidebar tabs: "Sidebar" (stock) | "Chat" (the single Document thread of the open record).
// The thread view is the bubble's own (ChatBubble methods), mounted into the sidebar instead of the
// floating popup. The chat can be expanded into a large popup and minimised back.

frappe.provide("erpnext.form_sidebar_chat");

const FSC_API = "erpnext.crm.page.employee_chat.employee_chat";

// Thread-view methods borrowed from the bubble: they only need source/active/$body/$compose/
// $readonly/$input and a few hooks stubbed below.
const FSC_BORROWED = [
	"load_thread",
	"render_deep_archive",
	"unpack",
	"watch_archive",
	"apply_archive_state",
	"render_composer",
	"autosize",
	"record_voice",
	"attach_media",
	"chat",
	"toggle_mute",
	"view_adapter",
	"jump_to_message",
];

class FormSidebarChat {
	constructor(frm, source, $pane) {
		this.frm = frm;
		this.source = source;
		this.$pane = $pane;
		this.active = null;
		this.ref = null;
		// The thread as the server described it on open: the only copy while the user reads a
		// chat they are not a participant of (it is not in their list then).
		this.local_chat = null;
		// Nothing is marked read just because the form was opened: the user has to click into
		// the chat (`engaged`), and from then on the read cursor follows what they scrolled to.
		this.manual_read = true;
		this.engaged = false;
		this.msgs = [];
		this.positioned = null;
		this.at_bottom = true;
		this.expanded = false;
		this.no_banner = true;
		this.make_dom();
	}

	make_dom() {
		this.$root = $(`
			<div class="fsc-root">
				<div class="fsc-head"></div>
				<div class="cb-body"></div>
				<div class="cb-readonly" style="display:none;">${__(
					"This chat is archived — new messages are not allowed"
				)}</div>
				<div class="fsc-unread-veil" style="display:none;"><span></span></div>
				<div class="cb-compose" style="display:none;">
					<button class="cb-ico cb-attach" title="${__("Attach file")}"><i class="fa fa-paperclip"></i></button>
					<button class="cb-ico cb-mic" title="${__("Record voice message")}"><i class="fa fa-microphone"></i></button>
					<textarea class="form-control" rows="1" placeholder="${__("Type a message")}"></textarea>
					<button class="cb-ico cb-send" title="${__("Send")}"><i class="fa fa-paper-plane"></i></button>
				</div>
			</div>
		`).appendTo(this.$pane);
		this.$body = this.$root.find(".cb-body");
		this.$compose = this.$root.find(".cb-compose");
		this.$readonly = this.$root.find(".cb-readonly");
		this.$input = this.$compose.find("textarea");
		this.$head = this.$root.find(".fsc-head");
		this.$veil = this.$root.find(".fsc-unread-veil");
		this.render_chat_head();
		this.$veil.on("click", () => this.engage());
		// Any click inside the chat (the composer included) counts as taking it up.
		this.$root.on("mousedown", () => this.engage());
		this.$body.on(
			"scroll",
			frappe.utils.throttle(() => {
				const el = this.$body[0];
				this.at_bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
				this.update_read_progress();
			}, 150)
		);

		this.$root.find(".cb-send").on("click", () => this.send());
		this.$root.find(".cb-attach").on("click", () => this.attach_media());
		this.$root.find(".cb-mic").on("click", () => this.record_voice());
		this.mention = erpnext.chat_mention.attach(this.$input, {
			enabled: () => erpnext.chat_mention.allowed(this.source, this.chat()),
			thread: () => this.active,
		});
		this.$input.on("keydown", (e) => {
			if (this.mention.handle_key(e)) return;
			if (e.key === "Enter" && !e.shiftKey) {
				e.preventDefault();
				this.send();
			}
		});
		this.$input.on("input", () => this.autosize());
	}

	set_expanded(state) {
		this.expanded = state;
		if (state) {
			this.$backdrop = $('<div class="fsc-backdrop"></div>')
				.on("click", () => this.set_expanded(false))
				.appendTo(document.body);
			this.$root.addClass("fsc-expanded").appendTo(document.body);
		} else {
			if (this.$backdrop) this.$backdrop.remove();
			this.$root.removeClass("fsc-expanded").appendTo(this.$pane);
		}
		this.render_chat_head();
		this.autosize();
		this.$body.scrollTop(this.$body[0].scrollHeight);
	}

	// The same thread header as on the chat pages, plus the expand / minimise toggle.
	render_chat_head() {
		const toggle = {
			icon: `fa fa-${this.expanded ? "compress" : "expand"}`,
			title: this.expanded ? __("Minimise") : __("Expand"),
			on_click: () => this.set_expanded(!this.expanded),
		};
		const chat = this.active ? this.chat() : null;
		if (chat) {
			erpnext.chat_render.render_header(this.$head, chat, this.source, this.view_adapter(), {
				size: 30,
				compact: true,
				trailing: [toggle],
			});
			if (chat.unread) {
				$('<span class="fsc-unread"></span>')
					.text(chat.unread > 99 ? "99+" : chat.unread)
					.attr("title", __("Unread messages"))
					.insertAfter(this.$head.find(".cv-header-main"));
			}
			return;
		}
		this.$head
			.addClass("cv-header cv-header-compact")
			.html(
				`<div class="cv-header-main" style="cursor:default;"><div class="cv-header-title">${__(
					"Chat about this document"
				)}</div></div>
				<button class="cv-ico" title="${toggle.title}"><i class="${toggle.icon}"></i></button>`
			)
			.find(".cv-ico")
			.on("click", toggle.on_click);
	}

	// --- reading ------------------------------------------------------------------

	// Enough history to reach the first unread message.
	thread_limit(chat) {
		return Math.min(200, Math.max(20, ((chat && chat.unread) || 0) + 10));
	}

	is_unread(m, chat) {
		return !m.out && (!chat.my_last_read || m.time > chat.my_last_read);
	}

	bubble_of(id) {
		return this.$body.find(".cv-bubble[data-id]").filter((_i, n) => $(n).attr("data-id") === id)[0];
	}

	// Bubble hook, after every (re)render of the thread: mark where the unread part starts,
	// put the view there the first time, and veil the chat until the user takes it up.
	after_thread_render(chat, msgs) {
		this.msgs = msgs || [];
		const first = chat && chat.unread ? this.msgs.find((m) => this.is_unread(m, chat)) : null;
		const el = first && this.bubble_of(first.id);
		if (el) $(`<div class="cv-new-divider">${__("New messages")}</div>`).insertBefore(el);

		const body = this.$body[0];
		if (this.positioned !== this.active) {
			this.positioned = this.active;
			if (el) body.scrollTop += el.getBoundingClientRect().top - body.getBoundingClientRect().top - 40;
			else body.scrollTop = body.scrollHeight;
			this.at_bottom = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
		} else if (this.at_bottom && (this.engaged || !el)) {
			body.scrollTop = body.scrollHeight;
		}
		this.render_unread();
		this.update_read_progress();
	}

	render_unread() {
		const chat = this.active ? this.chat() : null;
		const count = (chat && chat.unread) || 0;
		this.$veil
			.toggle(count > 0 && !this.engaged)
			.find("span")
			.text(
				count === 1
					? __("1 new message — click to read")
					: __("{0} new messages — click to read", [count > 99 ? "99+" : count])
			);
		this.render_chat_head();
	}

	engage() {
		if (this.engaged) return;
		this.engaged = true;
		this.$veil.hide();
		this.update_read_progress();
	}

	// Move the read cursor to the newest incoming message that has been fully on screen.
	async update_read_progress() {
		const chat = this.active ? this.chat() : null;
		if (!this.engaged || !chat || !chat.unread || this.marking) return;
		const bottom = this.$body[0].getBoundingClientRect().bottom + 4;
		let seen = null;
		for (const m of this.msgs) {
			if (!this.is_unread(m, chat)) continue;
			const el = this.bubble_of(m.id);
			if (!el || el.getBoundingClientRect().bottom > bottom) break;
			seen = m;
		}
		if (!seen) return;
		this.marking = true;
		try {
			await this.source.mark_read(chat, seen.time);
		} catch (e) {
			return;
		} finally {
			this.marking = false;
		}
		chat.my_last_read = seen.time;
		chat.unread = this.msgs.filter((m) => this.is_unread(m, chat)).length;
		this.render_unread();
		// The launcher badge counts the same chats; the sync it triggers must not re-render us.
		const bubble = erpnext.whatsapp.bubble;
		if (bubble) {
			erpnext.form_sidebar_chat.quiet = true;
			bubble.render_badges();
			erpnext.form_sidebar_chat.quiet = false;
		}
	}

	// Bubble hooks used by the borrowed methods.
	render_mute_toggle() {
		this.render_chat_head();
	}
	render_badges() {
		erpnext.form_sidebar_chat.update_badge(this.frm);
	}

	// Writing in a chat you were only reading joins it: pick up the membership straight away.
	async send() {
		const chat = this.chat();
		// Your own message is always shown, wherever the thread was scrolled to.
		this.at_bottom = true;
		await erpnext.ChatBubble.prototype.send.call(this);
		if (chat && chat.is_member === false) this.refresh();
	}

	// The user's own list first; a chat they only read lives in `local_chat`.
	chat_by_id(id) {
		const listed = (this.source.chats || []).find((c) => c.id === id);
		if (listed) return listed;
		return this.local_chat && this.local_chat.id === id ? this.local_chat : undefined;
	}

	// The chat left this user's list (they left it) or is gone (removed): open it afresh.
	forget_chat() {
		const ref = this.ref;
		this.reset();
		if (ref === this.frm.docname) this.open();
	}

	// Ask the server for the record's thread, creating it on first use. Opening does not join.
	async fetch_thread() {
		const res = await frappe.xcall(`${FSC_API}.open_document_thread`, {
			reference_doctype: this.frm.doctype,
			reference_name: this.frm.docname,
		});
		this.local_chat = this.source.shape(res.thread, this.local_chat);
		return res.name;
	}

	async refresh() {
		try {
			await this.source.load_list();
			// Not a participant: nothing in the list to refresh from, re-read the thread itself.
			if (this.active && !(this.source.chats || []).some((c) => c.id === this.active)) {
				const ref = this.ref;
				const name = await this.fetch_thread();
				if (this.ref !== ref) return;
				this.active = name;
			}
		} catch (e) {
			return;
		}
		erpnext.form_sidebar_chat.update_badge(this.frm);
		if (!this.active) return;
		this.render_chat_head();
		this.render_composer(this.chat());
		this.load_thread(this.active);
	}

	// Open (creating on first use) the Document thread of the form's record.
	async open() {
		const ref = this.frm.docname;
		if (this.ref === ref && this.active) return this.refresh();
		this.ref = ref;
		this.active = null;
		this.engaged = false;
		this.positioned = null;
		this.auto_unpacked = null;
		this.$readonly.hide();
		this.$compose.hide();
		this.$body.html(`<div class="cb-empty">${__("Loading")}...</div>`);
		let name;
		try {
			name = await this.fetch_thread();
			await this.source.load_list();
		} catch (e) {
			if (this.ref === ref) this.$body.html(`<div class="cb-empty">${__("Failed to open chat")}</div>`);
			return;
		}
		if (this.ref !== ref) return;
		this.active = name;
		erpnext.form_sidebar_chat.update_badge(this.frm);
		this.render_chat_head();
		this.render_composer(this.chat());
		this.autosize();
		this.load_thread(name);
	}

	reset() {
		this.ref = null;
		this.active = null;
		this.local_chat = null;
		this.engaged = false;
		this.positioned = null;
		this.msgs = [];
		this.$veil.hide();
		this.render_chat_head();
		clearInterval(this.archive_poll);
		if (this.expanded) this.set_expanded(false);
		this.$body.empty();
	}
}

FSC_BORROWED.forEach((m) => {
	FormSidebarChat.prototype[m] = function (...args) {
		return erpnext.ChatBubble.prototype[m].apply(this, args);
	};
});

(function () {
	const FS = erpnext.form_sidebar_chat;

	function employee_source() {
		const b = erpnext.whatsapp.bubble;
		return b && b.sources.find((s) => s.key === "employee");
	}

	function inject_styles() {
		if (document.getElementById("fsc-styles")) return;
		const css = `
		.fsc-tabs{display:flex;border-bottom:1px solid var(--border-color);position:sticky;top:0;z-index:2;
			background:var(--card-bg);}
		.fsc-tab{flex:1;display:flex;align-items:center;justify-content:center;gap:5px;padding:9px 8px;cursor:pointer;
			font-size:var(--text-sm);font-weight:600;color:var(--text-muted);border-bottom:2px solid transparent;}
		.fsc-tab:hover{background:var(--bg-light-gray);}
		.fsc-tab.active{color:var(--text-color);border-bottom-color:var(--primary,#2490ef);}
		.fsc-badge{min-width:17px;height:17px;padding:0 5px;border-radius:9px;background:var(--red-500,#e24c4c);
			color:#fff;font-size:10px;line-height:17px;font-weight:600;text-align:center;display:none;}
		.fsc-pane-chat{display:none;}
		.fsc-root{position:relative;display:flex;flex-direction:column;height:calc(100vh - 230px);min-height:320px;
			background:var(--card-bg);}
		.fsc-unread{flex:none;min-width:20px;height:20px;padding:0 6px;border-radius:10px;
			background:var(--red-500,#e24c4c);color:#fff;font-size:11px;line-height:20px;font-weight:600;text-align:center;}
		.fsc-unread-veil{position:absolute;inset:0;z-index:3;display:flex;align-items:center;justify-content:center;
			padding:16px;cursor:pointer;background:rgba(255,255,255,.55);}
		[data-theme="dark"] .fsc-unread-veil{background:rgba(0,0,0,.45);}
		.fsc-unread-veil span{padding:8px 16px;border-radius:18px;background:var(--primary,#2490ef);color:#fff;
			font-size:var(--text-sm);font-weight:600;text-align:center;box-shadow:0 4px 14px rgba(0,0,0,.25);}
		.fsc-head{flex:none;}
		.fsc-root .cb-body{flex:1;overflow-y:auto;}
		.fsc-backdrop{position:fixed;inset:0;z-index:1034;background:rgba(0,0,0,.35);}
		.fsc-root.fsc-expanded{position:fixed;z-index:1035;right:50%;bottom:50%;transform:translate(50%,50%);
			width:min(760px,94vw);height:min(86vh,900px);border:1px solid var(--border-color);
			border-radius:var(--border-radius-md);box-shadow:0 8px 28px rgba(0,0,0,.3);overflow:hidden;}
		`;
		$(`<style id="fsc-styles">${css}</style>`).appendTo(document.head);
	}

	function is_active(frm) {
		return frm.__fsc && frm.__fsc.tab === "chat";
	}

	FS.doc_thread = function (frm) {
		const emp = employee_source();
		return (
			emp &&
			(emp.chats || []).find(
				(c) => c.reference_doctype === frm.doctype && c.reference_name === frm.docname
			)
		);
	};

	FS.update_badge = function (frm) {
		const st = frm && frm.__fsc;
		if (!st) return;
		const t = FS.doc_thread(frm);
		const count = is_active(frm) ? 0 : (t && t.unread) || 0;
		st.$badge.text(count > 99 ? "99+" : count).toggle(count > 0);
	};

	const TAB_KEY = "fsc_tab";

	function saved_tab() {
		try {
			return localStorage.getItem(TAB_KEY) === "chat" ? "chat" : "info";
		} catch (e) {
			return "info";
		}
	}

	FS.select_tab = function (frm, tab) {
		const st = frm.__fsc;
		if (!st) return;
		try {
			localStorage.setItem(TAB_KEY, tab);
		} catch (e) {
			// storage unavailable: tab simply is not remembered
		}
		st.tab = tab;
		st.$tabs.find(".fsc-tab").removeClass("active");
		st.$tabs.find(`.fsc-tab[data-tab="${tab}"]`).addClass("active");
		// Leaving the chat tab puts it down: coming back, new messages wait for a click again.
		if (tab !== "chat") st.chat.engaged = false;
		st.$info.toggle(tab === "info");
		st.$pane.toggle(tab === "chat");
		if (tab === "chat") st.chat.open();
		FS.update_badge(frm);
	};

	// Called by the bubble after every list refresh (realtime, poll): keep badge and open thread live.
	FS.sync = function () {
		const frm = window.cur_frm;
		if (!frm || !frm.__fsc || FS.quiet) return;
		if (is_active(frm) && frm.__fsc.chat.active) frm.__fsc.chat.refresh();
		else FS.update_badge(frm);
	};

	function setup(frm) {
		const sidebar = frm.sidebar && frm.sidebar.sidebar;
		const source = employee_source();
		if (!sidebar || !source || frm.is_new()) return;
		inject_styles();

		let st = frm.__fsc;
		if (st && sidebar.find(".fsc-tabs").length) {
			if (st.chat.ref && st.chat.ref !== frm.docname) {
				st.chat.reset();
			}
			if (st.tab !== saved_tab()) FS.select_tab(frm, saved_tab());
			else if (st.tab === "chat" && !st.chat.active) st.chat.open();
			FS.update_badge(frm);
			return;
		}

		// The sidebar markup was (re)built by Sidebar.make(): wrap it and add the tabs.
		const $info = $('<div class="fsc-pane-info"></div>');
		$info.append(sidebar.children().detach());
		const $tabs = $(`
			<div class="fsc-tabs">
				<div class="fsc-tab active" data-tab="info">${__("Sidebar")}</div>
				<div class="fsc-tab" data-tab="chat"><span>${__("Chat")}</span><span class="fsc-badge"></span></div>
			</div>
		`);
		const $pane = $('<div class="fsc-pane-chat"></div>');
		sidebar.append($tabs, $info, $pane);
		if (st && st.chat) st.chat.reset();
		st = frm.__fsc = {
			tab: "info",
			$tabs,
			$info,
			$pane,
			$badge: $tabs.find(".fsc-badge"),
			chat: new FormSidebarChat(frm, source, $pane),
		};
		$tabs.on("click", ".fsc-tab", (e) => FS.select_tab(frm, $(e.currentTarget).attr("data-tab")));
		if (saved_tab() === "chat") FS.select_tab(frm, "chat");
		FS.update_badge(frm);
	}

	$(document).on("form-refresh", (e, frm) => {
		if (frm) setup(frm);
	});
})();
