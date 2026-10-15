// Form sidebar tabs: "Sidebar" (stock) | "Chat" (the single Document thread of the open record).
// The thread is the chat pages' own view (erpnext.chat_view.ChatView in embedded mode), so it has
// everything a chat has there. It can be expanded into a large popup and minimised back.

frappe.provide("erpnext.form_sidebar_chat");

const FSC_API = "erpnext.crm.page.employee_chat.employee_chat";

class FormSidebarChat {
	constructor(frm, $pane) {
		this.frm = frm;
		this.$pane = $pane;
		this.ref = null;
		this.expanded = false;
		this.drawn_unread = 0;
		// Its own source: the view keeps its own list and realtime, apart from the bubble's.
		this.source = new erpnext.chat_sources.Employee();
		this.make_dom();
	}

	make_dom() {
		this.$root = $(`
			<div class="fsc-root">
				<div class="fsc-view"></div>
				<div class="fsc-unread-veil" style="display:none;"><span></span></div>
			</div>
		`).appendTo(this.$pane);
		this.$veil = this.$root.find(".fsc-unread-veil");
		// The chat pages' own thread view — reply, reactions, emoji, message menu and all —
		// without the conversation list. Nothing is marked read just because the form was
		// opened: the user has to click into the chat first (`engage`).
		this.view = new erpnext.chat_view.ChatView({ main: this.$root.find(".fsc-view") }, this.source, {
			embedded: true,
			manual_read: true,
			header: (chat) => ({
				size: 30,
				compact: true,
				trailing: [this.toggle_action()],
				after_title_html: chat.unread
					? `<span class="fsc-unread" title="${__("Unread messages")}">${
							chat.unread > 99 ? "99+" : chat.unread
					  }</span>`
					: "",
			}),
			on_change: () => this.render_unread(),
			on_forget: () => this.reopen(),
		});
		// Any click inside the chat (the composer included) counts as taking it up.
		this.$root.on("mousedown", () => this.engage());
		this.render_idle("");
	}

	toggle_action() {
		return {
			icon: `fa fa-${this.expanded ? "compress" : "expand"}`,
			title: this.expanded ? __("Minimise") : __("Expand"),
			on_click: () => this.set_expanded(!this.expanded),
		};
	}

	// No thread on screen (loading, failed): a plain title bar and a line of text.
	render_idle(text) {
		this.idle_text = text;
		this.view.clear();
		this.$veil.hide();
		const toggle = this.toggle_action();
		this.view.$header
			.addClass("cv-header-compact")
			.html(
				`<div class="cv-header-main" style="cursor:default;"><div class="cv-header-title">${__(
					"Chat about this document"
				)}</div></div>
				<button class="cv-ico" title="${toggle.title}"><i class="${toggle.icon}"></i></button>`
			)
			.find(".cv-ico")
			.on("click", toggle.on_click);
		this.view.$thread.html(`<div class="cv-empty">${frappe.utils.escape_html(text || "")}</div>`);
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
		if (this.view.active) this.view.render_header();
		else this.render_idle(this.idle_text);
	}

	// --- reading ------------------------------------------------------------------

	// Until the user takes the chat up, new messages stay unread behind a veil that says how
	// many there are; the header badge keeps counting down as they are scrolled into view.
	render_unread() {
		const chat = this.view.active ? this.view.chat() : null;
		const count = (chat && chat.unread) || 0;
		this.$veil
			.toggle(count > 0 && !this.view.engaged)
			.find("span")
			.text(
				count === 1
					? __("1 new message — click to read")
					: __("{0} new messages — click to read", [count > 99 ? "99+" : count])
			);
		if (count === this.drawn_unread) return;
		this.drawn_unread = count;
		if (chat) this.view.render_header();
		// The launcher and the tab badge count the same chat from the bubble's own list.
		if (erpnext.whatsapp.bubble) erpnext.whatsapp.bubble.refresh_soon();
	}

	engage() {
		if (this.view.engaged) return;
		this.view.engaged = true;
		this.$veil.hide();
		this.view.update_read_progress();
	}

	// Put the chat down: new messages wait for a click again.
	disengage() {
		this.view.engaged = false;
		this.render_unread();
	}

	// --- opening ------------------------------------------------------------------

	// Open (creating on first use) the Document thread of the form's record. Opening does not
	// join: a chat the user only reads is not in their list, so its row comes from the server
	// here and is handed to the view.
	async open() {
		const ref = this.frm.docname;
		if (this.ref === ref && this.view.active) return this.view.refresh(true);
		this.ref = ref;
		this.view.engaged = false;
		this.render_idle(__("Loading") + "...");
		let res;
		try {
			res = await frappe.xcall(`${FSC_API}.open_document_thread`, {
				reference_doctype: this.frm.doctype,
				reference_name: ref,
			});
			await this.view.refresh(true);
		} catch (e) {
			if (this.ref === ref) this.render_idle(__("Failed to open chat"));
			return;
		}
		if (this.ref !== ref) return;
		if (!this.view.chats[res.name]) this.view.chats[res.name] = this.source.shape(res.thread);
		await this.view.open(res.name);
		this.render_unread();
	}

	// The chat left this user's list (they left it) or is gone (removed): open it afresh.
	reopen() {
		const same = this.ref === this.frm.docname;
		this.reset();
		if (same) this.open();
	}

	reset() {
		this.ref = null;
		this.drawn_unread = 0;
		this.view.engaged = false;
		if (this.expanded) this.set_expanded(false);
		this.render_idle("");
	}

	destroy() {
		if (this.expanded) this.set_expanded(false);
		this.view.destroy();
		this.$root.remove();
	}
}

(function () {
	const FS = erpnext.form_sidebar_chat;

	function employee_source() {
		const b = erpnext.whatsapp.bubble;
		return b && b.sources.find((s) => s.key === "employee");
	}

	function inject_styles() {
		if (document.getElementById("fsc-styles-v2")) return;
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
		.form-sidebar.fsc-chat-mode{display:flex;flex-direction:column;height:100%;}
		.fsc-chat-mode > .fsc-tabs{flex:none;}
		.fsc-chat-mode > .fsc-pane-chat{flex:1;min-height:0;flex-direction:column;}
		.fsc-chat-mode > .fsc-pane-chat > .fsc-root:not(.fsc-expanded){flex:1;height:auto;}
		.fsc-unread{flex:none;min-width:20px;height:20px;padding:0 6px;border-radius:10px;
			background:var(--red-500,#e24c4c);color:#fff;font-size:11px;line-height:20px;font-weight:600;text-align:center;}
		.fsc-unread-veil{position:absolute;inset:0;z-index:6;display:flex;align-items:center;justify-content:center;
			padding:16px;cursor:pointer;background:rgba(255,255,255,.55);}
		[data-theme="dark"] .fsc-unread-veil{background:rgba(0,0,0,.45);}
		.fsc-unread-veil span{padding:8px 16px;border-radius:18px;background:var(--primary,#2490ef);color:#fff;
			font-size:var(--text-sm);font-weight:600;text-align:center;box-shadow:0 4px 14px rgba(0,0,0,.25);}
		.fsc-view{flex:1;min-height:0;}
		.fsc-backdrop{position:fixed;inset:0;z-index:1034;background:rgba(0,0,0,.35);}
		.fsc-root.fsc-expanded{position:fixed;z-index:1035;right:50%;bottom:50%;transform:translate(50%,50%);
			width:min(760px,94vw);height:min(86vh,900px);border:1px solid var(--border-color);
			border-radius:var(--border-radius-md);box-shadow:0 8px 28px rgba(0,0,0,.3);overflow:hidden;}
		`;
		$(`<style id="fsc-styles-v2">${css}</style>`).appendTo(document.head);
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
		if (tab !== "chat") st.chat.disengage();
		st.$info.toggle(tab === "info");
		st.$pane.css("display", tab === "chat" ? "flex" : "none");
		st.$sidebar.toggleClass("fsc-chat-mode", tab === "chat");
		if (tab === "chat") st.chat.open();
		FS.update_badge(frm);
	};

	// Called by the bubble after every list refresh (realtime, poll): keep the tab badge live.
	// The open thread looks after itself — it is a ChatView with its own realtime.
	FS.sync = function () {
		const frm = window.cur_frm;
		if (!frm || !frm.__fsc) return;
		FS.update_badge(frm);
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
			else if (st.tab === "chat" && !st.chat.view.active) st.chat.open();
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
		if (st && st.chat) st.chat.destroy();
		st = frm.__fsc = {
			tab: "info",
			$sidebar: sidebar,
			$tabs,
			$info,
			$pane,
			$badge: $tabs.find(".fsc-badge"),
			chat: new FormSidebarChat(frm, $pane),
		};
		$tabs.on("click", ".fsc-tab", (e) => FS.select_tab(frm, $(e.currentTarget).attr("data-tab")));
		if (saved_tab() === "chat") FS.select_tab(frm, "chat");
		FS.update_badge(frm);
	}

	$(document).on("form-refresh", (e, frm) => {
		if (frm) setup(frm);
	});
})();
