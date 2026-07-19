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

// Map a browser MIME type to the WhatsApp content_type we send.
function mime_to_content_type(mime) {
	if (!mime) return "document";
	if (mime.startsWith("image/")) return "image";
	if (mime.startsWith("video/")) return "video";
	if (mime.startsWith("audio/")) return "audio";
	return "document";
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
		this.allowed_phones = null; // null = all; Set = filtered by manager
		this.context = null; // context of the open chat
		this.reply_to = null; // {message_id, preview} when composing a reply
		this.make_layout();
		this.load_managers();
		this.load_account().then(() => this.refresh());
		// realtime push from server on new/updated WhatsApp Message
		this.on_rt = () => this.refresh(true);
		frappe.realtime.on("whatsapp_message", this.on_rt);
		// slow poll as a safety net if the socket drops
		this.poll = setInterval(() => this.refresh(true), 30000);
		$(this.page.wrapper).on("remove", () => {
			clearInterval(this.poll);
			frappe.realtime.off("whatsapp_message", this.on_rt);
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
	}

	inject_styles() {
		if (document.getElementById("wa-chat-styles-v4")) return;
		const css = `
		.wa-chat{display:flex;height:calc(100vh - 160px);border:1px solid var(--border-color);border-radius:var(--border-radius-md);overflow:hidden;background:var(--card-bg);}
		.wa-sidebar{width:280px;border-right:1px solid var(--border-color);display:flex;flex-direction:column;}
		.wa-search{padding:8px;border-bottom:1px solid var(--border-color);}
		.wa-conv-list{overflow-y:auto;flex:1;}
		.wa-conv{padding:10px 12px;cursor:pointer;border-bottom:1px solid var(--border-color);}
		.wa-conv:hover{background:var(--bg-light-gray);}
		.wa-conv.active{background:var(--bg-blue);}
		.wa-conv .wa-name{font-weight:600;font-size:var(--text-md);}
		.wa-conv .wa-last{color:var(--text-muted);font-size:var(--text-sm);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
		.wa-thread-wrap{flex:1;display:flex;flex-direction:column;min-width:0;}
		.wa-thread-header{padding:12px;border-bottom:1px solid var(--border-color);font-weight:600;}
		.wa-thread{flex:1;overflow-y:auto;padding:12px 16px;background:var(--bg-gray);display:flex;flex-direction:column;gap:3px;}
		.wa-bubble{position:relative;width:fit-content;max-width:65%;padding:5px 9px 3px;border-radius:8px;font-size:13px;line-height:1.35;text-align:left;word-break:break-word;}
		.wa-body{white-space:pre-wrap;}
		.wa-in{align-self:flex-start;background:var(--card-bg);border:1px solid var(--border-color);}
		.wa-out{align-self:flex-end;background:#d9fdd3;color:#111;}
		.wa-meta{font-size:10px;color:var(--text-muted);margin-top:1px;text-align:right;opacity:.7;}
		.wa-media img{max-width:220px;max-height:260px;border-radius:6px;cursor:pointer;display:block;}
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
		`;
		$(`<style id="wa-chat-styles-v3">${css}</style>`).appendTo(document.head);
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
		if (!this.manager) {
			this.allowed_phones = null;
		} else {
			const chats = await frappe.xcall(
				"erpnext.crm.page.whatsapp_chat.whatsapp_chat.get_chats",
				{ manager: this.manager }
			);
			this.allowed_phones = new Set(chats.map((c) => c.phone));
		}
		this.render_list();
	}

	async refresh(silent) {
		const msgs = await frappe.db.get_list("WhatsApp Message", {
			fields: [
				"name", "type", "from", "to", "message", "profile_name", "creation",
				"status", "status_error", "content_type", "attach", "message_id",
				"reply_to_message_id", "is_reply",
			],
			order_by: "creation asc",
			limit: 1000,
		});
		this.conversations = {};
		for (const m of msgs) {
			const num = m.type === "Incoming" ? m.from : m.to;
			if (!num) continue;
			if (!this.conversations[num]) {
				this.conversations[num] = { number: num, name: num, messages: [] };
			}
			const c = this.conversations[num];
			if (m.type === "Incoming" && m.profile_name) c.name = m.profile_name;
			c.messages.push(m);
			c.last = m;
		}
		// Keep an open but empty conversation (new chat / deep-link to a number with no
		// messages yet) alive across the rebuild above so it doesn't vanish on poll.
		if (this.active && !this.conversations[this.active]) {
			this.conversations[this.active] = { number: this.active, name: this.active, messages: [] };
		}
		this.render_list();
		if (this.active && this.conversations[this.active]) this.render_thread(!silent);
		if (this.pending_open) {
			const p = this.ensure_conv(this.pending_open);
			this.pending_open = null;
			if (p) this.open(p);
		}
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
		if (this.allowed_phones) convs = convs.filter((c) => this.allowed_phones.has(c.number));
		convs = convs
			.filter((c) => !q || c.number.toLowerCase().includes(q) || (c.name || "").toLowerCase().includes(q))
			.sort((a, b) => (b.last?.creation || "").localeCompare(a.last?.creation || ""));

		this.$list.empty();
		if (!convs.length) {
			this.$list.html(`<div class="text-muted" style="padding:12px;">${__("No conversations yet")}</div>`);
			return;
		}
		for (const c of convs) {
			const preview = frappe.utils.escape_html(this.preview_text(c.last)).slice(0, 40);
			const $el = $(`
				<div class="wa-conv ${c.number === this.active ? "active" : ""}">
					<div class="wa-name">${frappe.utils.escape_html(c.name)}</div>
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
		this.render_list();
		this.render_thread(true);
		this.$compose.show();
		const c = this.conversations[number];
		this.$header.text(c.name === number ? number : `${c.name} · ${number}`);
		this.load_context(number);
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
				return `<div class="${cls}"><img src="${url}" data-full="${url}"></div>${ct === "sticker" ? "" : cap_html}`;
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

		this.$thread.find("img[data-full]").on("click", (e) => {
			window.open($(e.currentTarget).data("full"), "_blank");
		});
		this.$thread.find(".wa-do-reply").on("click", (e) => {
			const m = $(e.currentTarget).closest(".wa-bubble").data("msg");
			this.set_reply({ message_id: m.message_id, preview: this.preview_text(m) });
		});
		this.$thread.find(".wa-do-react").on("click", (e) => this.react_popover(e));
		this.$thread.find(".wa-resend").on("click", (e) => {
			const m = $(e.currentTarget).closest(".wa-bubble").data("msg");
			this.resend(m);
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
				const content_type = mime_to_content_type(file.file_type || file.type);
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
