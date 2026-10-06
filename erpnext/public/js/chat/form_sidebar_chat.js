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
	"send",
	"chat",
];

class FormSidebarChat {
	constructor(frm, source, $pane) {
		this.frm = frm;
		this.source = source;
		this.$pane = $pane;
		this.active = null;
		this.ref = null;
		this.expanded = false;
		this.make_dom();
	}

	make_dom() {
		this.$root = $(`
			<div class="fsc-root">
				<div class="fsc-head">
					<span class="fsc-title">${__("Chat about this document")}</span>
					<span class="fsc-act fsc-toggle" title="${__("Expand")}"><i class="fa fa-expand"></i></span>
				</div>
				<div class="cb-body"></div>
				<div class="cb-readonly" style="display:none;">${__(
					"This chat is archived — new messages are not allowed"
				)}</div>
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
		this.$toggle = this.$root.find(".fsc-toggle");

		this.$root.find(".cb-send").on("click", () => this.send());
		this.$root.find(".cb-attach").on("click", () => this.attach_media());
		this.$root.find(".cb-mic").on("click", () => this.record_voice());
		this.$toggle.on("click", () => this.set_expanded(!this.expanded));
		this.$input.on("keydown", (e) => {
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
		this.$toggle
			.attr("title", state ? __("Minimise") : __("Expand"))
			.html(`<i class="fa fa-${state ? "compress" : "expand"}"></i>`);
		this.autosize();
		this.$body.scrollTop(this.$body[0].scrollHeight);
	}

	// Bubble hooks used by the borrowed methods.
	render_mute_toggle() {}
	render_badges() {
		erpnext.form_sidebar_chat.update_badge(this.frm);
	}

	async refresh() {
		try {
			await this.source.load_list();
		} catch (e) {
			return;
		}
		erpnext.form_sidebar_chat.update_badge(this.frm);
		if (!this.active) return;
		if (!(this.source.chats || []).some((c) => c.id === this.active)) {
			this.active = null;
			this.$body.html(`<div class="cb-empty">${__("Failed to open chat")}</div>`);
			return;
		}
		this.render_composer(this.chat());
		this.load_thread(this.active);
	}

	// Open (creating on first use) the Document thread of the form's record.
	async open() {
		const ref = this.frm.docname;
		if (this.ref === ref && this.active) return this.refresh();
		this.ref = ref;
		this.active = null;
		this.auto_unpacked = null;
		this.$readonly.hide();
		this.$compose.hide();
		this.$body.html(`<div class="cb-empty">${__("Loading")}...</div>`);
		let name;
		try {
			const res = await frappe.xcall(`${FSC_API}.open_document_thread`, {
				reference_doctype: this.frm.doctype,
				reference_name: ref,
			});
			name = res.name;
			await this.source.load_list();
		} catch (e) {
			if (this.ref === ref) this.$body.html(`<div class="cb-empty">${__("Failed to open chat")}</div>`);
			return;
		}
		if (this.ref !== ref) return;
		this.active = name;
		erpnext.form_sidebar_chat.update_badge(this.frm);
		this.render_composer(this.chat());
		this.autosize();
		this.load_thread(name);
	}

	reset() {
		this.ref = null;
		this.active = null;
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
		.fsc-root{display:flex;flex-direction:column;height:calc(100vh - 230px);min-height:320px;
			background:var(--card-bg);}
		.fsc-head{display:flex;align-items:center;gap:6px;padding:6px 10px;border-bottom:1px solid var(--border-color);}
		.fsc-title{flex:1;font-weight:600;font-size:var(--text-sm);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
		.fsc-act{cursor:pointer;color:var(--text-muted);padding:2px 4px;}
		.fsc-act:hover{color:var(--text-color);}
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

	FS.select_tab = function (frm, tab) {
		const st = frm.__fsc;
		if (!st) return;
		st.tab = tab;
		st.$tabs.find(".fsc-tab").removeClass("active");
		st.$tabs.find(`.fsc-tab[data-tab="${tab}"]`).addClass("active");
		st.$info.toggle(tab === "info");
		st.$pane.toggle(tab === "chat");
		if (tab === "chat") st.chat.open();
		FS.update_badge(frm);
	};

	// Called by the bubble after every list refresh (realtime, poll): keep badge and open thread live.
	FS.sync = function () {
		const frm = window.cur_frm;
		if (!frm || !frm.__fsc) return;
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
				if (st.tab === "chat") st.chat.open();
			}
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
		FS.update_badge(frm);
	}

	$(document).on("form-refresh", (e, frm) => {
		if (frm) setup(frm);
	});
})();
