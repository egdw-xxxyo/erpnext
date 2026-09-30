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

// Short label for a non-text message (list preview + reply quote). Plain text — it is
// escaped by its callers; the matching icon comes from media_icon.
function media_label(content_type) {
	return {
		image: __("Photo"),
		video: __("Video"),
		audio: __("Audio"),
		document: __("Document"),
		sticker: __("Sticker"),
	}[content_type];
}

function media_icon(content_type) {
	const icon = {
		image: "camera",
		video: "video-camera",
		audio: "microphone",
		document: "file-o",
		sticker: "smile-o",
	}[content_type];
	return icon ? `<i class="fa fa-${icon}"></i> ` : "";
}

// Delivery ticks for an outgoing message, Telegram/WhatsApp style.
function status_icon(status) {
	const st = (status || "").toLowerCase();
	const label = frappe.utils.escape_html(__(status || ""));
	if (st === "failed") return `<i class="fa fa-exclamation-circle wa-st-failed" title="${label}"></i>`;
	if (st === "read")
		return `<span class="wa-ticks wa-st-read" title="${label}"><i class="fa fa-check"></i><i class="fa fa-check"></i></span>`;
	if (st === "delivered")
		return `<span class="wa-ticks" title="${label}"><i class="fa fa-check"></i><i class="fa fa-check"></i></span>`;
	if (st === "sent" || st === "success") return `<i class="fa fa-check" title="${label}"></i>`;
	return `<i class="fa fa-clock-o" title="${label}"></i>`;
}

function initials(name) {
	const parts = String(name || "?")
		.replace(/[^\p{L}\p{N} ]/gu, "")
		.trim()
		.split(/\s+/)
		.filter(Boolean);
	if (!parts.length) return "#";
	return ((parts[0][0] || "") + (parts.length > 1 ? parts[1][0] : "")).toUpperCase();
}

// Stable pastel per conversation, so the same chat keeps its avatar colour.
function avatar_color(key) {
	const palette = ["#e17076", "#7bc862", "#e5ca77", "#65aadd", "#a695e7", "#ee7aae", "#6ec9cb", "#faa774"];
	let h = 0;
	for (const ch of String(key || "")) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
	return palette[h % palette.length];
}

function avatar_html(name, key, size) {
	return `<div class="wa-avatar" style="background:${avatar_color(key)};${
		size ? `width:${size}px;height:${size}px;line-height:${size}px;` : ""
	}">${frappe.utils.escape_html(initials(name))}</div>`;
}

// List timestamp: time for today, weekday within a week, date otherwise.
function list_time(dt) {
	if (!dt) return "";
	const m = moment.tz(dt, frappe.sys_defaults.time_zone || "UTC").local();
	const now = moment();
	if (m.isSame(now, "day")) return m.format("HH:mm");
	if (now.diff(m, "days") < 7) return m.format("ddd");
	return m.format("DD.MM.YY");
}

function day_label(m) {
	const now = moment();
	if (m.isSame(now, "day")) return __("Today");
	if (m.isSame(now.clone().subtract(1, "day"), "day")) return __("Yesterday");
	return m.format(m.isSame(now, "year") ? "D MMMM" : "D MMMM YYYY");
}

class WhatsAppChat {
	constructor(page) {
		this.page = page;
		this.active = null; // active conversation (WhatsApp Chat name)
		// The business numbers this user sees: [{name, label, access, read_only}].
		this.numbers = frappe.boot.whatsapp_accounts || [];
		this.conversations = {}; // chat name -> {id, number, name, account, messages:[]}
		this.account_filter = null; // business number filter
		this.context = null; // context of the open chat
		this.reply_to = null; // {message_id, preview} when composing a reply
		this.make_layout();
		this.refresh();
		// realtime push from server on new/updated WhatsApp Message
		// Incoming messages ring (unless the conversation is muted); everything else just
		// refreshes.
		this.on_rt = (d) => {
			console.log("[chat] page realtime event", d);
			if (d && d.type === "Incoming" && d.chat) {
				const c = this.conversations[d.chat];
				console.log("[chat] page incoming ring", {
					number: d.number,
					conv_found: !!c,
					muted: c && c.muted,
				});
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
		// deep-links: /app/whatsapp-chat-center?chat=<chat> or ?phone=380...
		const chat = frappe.route_options?.chat || frappe.utils.get_url_arg("chat");
		const phone = frappe.route_options?.phone || frappe.utils.get_url_arg("phone");
		frappe.route_options = null;
		if (chat) this.pending_chat = chat;
		else if (phone) this.pending_phone = phone;
	}

	make_layout() {
		this.page.main.html(`
			<div class="wa-chat">
				<div class="wa-sidebar">
					<div class="wa-search">
						<div class="wa-search-row">
							<div class="wa-search-box">
								<i class="fa fa-search"></i>
								<input type="text" class="wa-search-input" placeholder="${__("Search number or name")}">
							</div>
							<button class="wa-ico wa-new-chat" title="${__("New chat")}"><i class="fa fa-pencil-square-o"></i></button>
						</div>
						<select class="form-control input-xs wa-number-filter" style="display:none;">
							<option value="">${__("All numbers")}</option>
						</select>
					</div>
					<div class="wa-conv-list"></div>
				</div>
				<div class="wa-thread-wrap">
					<div class="wa-thread-header text-muted">${__("Select a conversation")}</div>
					<div class="wa-thread">
						<div class="wa-thread-empty"><i class="fa fa-whatsapp"></i><div>${__("Select a conversation")}</div></div>
					</div>
					<div class="wa-scroll-fab" title="${__(
						"Scroll to latest"
					)}"><i class="fa fa-chevron-down"></i><span class="wa-fab-badge" style="display:none;"></span></div>
					<div class="wa-readonly-bar" style="display:none;">
						<i class="fa fa-eye"></i> ${__("Read only — you are a spectator of this number")}
					</div>
					<div class="wa-compose-wrap" style="display:none;">
						<div class="wa-reply-bar" style="display:none;">
							<i class="fa fa-reply wa-reply-icon"></i>
							<div class="wa-reply-bar-text"></div>
							<span class="wa-reply-cancel" title="${__("Cancel reply")}"><i class="fa fa-times"></i></span>
						</div>
						<div class="wa-compose">
							<button class="wa-ico wa-attach" title="${__("Attach file")}"><i class="fa fa-paperclip"></i></button>
							<button class="wa-ico wa-template" title="${__("Send template")}"><i class="fa fa-file-text-o"></i></button>
							<textarea rows="1" placeholder="${__("Type a message")}"></textarea>
							<button class="wa-ico wa-emoji" title="${__("Add emoji")}"><i class="fa fa-smile-o"></i></button>
							<button class="wa-ico wa-mic" title="${__("Record voice message")}"><i class="fa fa-microphone"></i></button>
							<button class="wa-ico wa-send" title="${__(
								"Send"
							)}" style="display:none;"><i class="fa fa-paper-plane"></i></button>
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
		this.$numberFilter = this.page.main.find(".wa-number-filter");
		this.$readonly = this.page.main.find(".wa-readonly-bar");
		this.fill_number_filter();
		this.$context = this.page.main.find(".wa-context");
		this.$fab = this.page.main.find(".wa-scroll-fab");
		this.$fab.on("click", () => this.jump_to_latest());

		this.page.main.find(".wa-new-chat").on("click", () => this.new_chat_prompt());
		this.page.main.find(".wa-send").on("click", () => this.send());
		this.page.main.find(".wa-attach").on("click", () => this.attach_media());
		this.page.main.find(".wa-mic").on("click", () => this.record_voice());
		this.page.main.find(".wa-emoji").on("click", (e) => this.emoji_picker(e));
		this.page.main.find(".wa-template").on("click", () => this.template_dialog());
		this.$replyBar.find(".wa-reply-cancel").on("click", () => this.set_reply(null));
		this.$input.on("keydown", (e) => {
			if (e.key === "Enter" && !e.shiftKey) {
				e.preventDefault();
				this.send();
			}
		});
		this.$input.on("input", () => this.autosize());
		this.$search.on("input", () => this.render_list());
		this.$numberFilter.on("change", () => this.apply_number_filter());
		this.$thread.on("scroll", () => {
			if (this.$thread.scrollTop() < 40) this.load_older();
			this.update_read_progress();
			this.update_fab();
		});
	}

	inject_styles() {
		erpnext.chat_media.inject_styles();
		erpnext.chat_sound.inject_styles();
		if (document.getElementById("wa-chat-styles-v8")) return;
		const css = `
		.wa-chat{--wa-out:#effdde;--wa-out-text:#111;--wa-in:var(--card-bg);--wa-thread-bg:#e6ebee;--wa-accent:#3390ec;
			--wa-tick:#4fae4e;display:flex;height:calc(100vh - 160px);border:1px solid var(--border-color);
			border-radius:var(--border-radius-lg,12px);overflow:hidden;background:var(--card-bg);}
		[data-theme="dark"] .wa-chat{--wa-out:#2b5278;--wa-out-text:#fff;--wa-in:#182533;--wa-thread-bg:#0e1621;
			--wa-accent:#5eb5f7;--wa-tick:#5eb5f7;}
		.wa-ico{flex:none;width:36px;height:36px;padding:0;border:none;background:none;border-radius:50%;
			color:var(--text-muted);font-size:19px;line-height:36px;text-align:center;cursor:pointer;
			transition:background .15s,color .15s;}
		.wa-ico:hover{background:var(--bg-light-gray);color:var(--text-color);}
		.wa-ico:focus{outline:none;}
		.wa-send,.wa-send:hover{color:var(--wa-accent);}
		.wa-avatar{flex:none;width:44px;height:44px;border-radius:50%;color:#fff;font-weight:600;font-size:15px;
			line-height:44px;text-align:center;user-select:none;}
		.wa-sidebar{width:300px;border-right:1px solid var(--border-color);display:flex;flex-direction:column;}
		.wa-search{padding:10px;display:flex;flex-direction:column;gap:6px;}
		.wa-search-row{display:flex;align-items:center;gap:4px;}
		.wa-search-box{flex:1;display:flex;align-items:center;gap:8px;padding:0 12px;height:36px;border-radius:18px;
			background:var(--control-bg);color:var(--text-muted);}
		.wa-search-box input{flex:1;min-width:0;border:none;background:none;outline:none;color:var(--text-color);font-size:var(--text-md);}
		.wa-number-filter{border-radius:18px;}
		.wa-conv .wa-via{flex:none;font-size:10px;color:var(--text-muted);border:1px solid var(--border-color);border-radius:8px;padding:0 5px;white-space:nowrap;}
		.wa-conv.active .wa-via{color:#fff;border-color:rgba(255,255,255,.6);}
		.wa-thread-header .wa-header-via{display:inline-flex;align-items:center;gap:4px;margin-left:6px;padding:0 6px;border-radius:8px;
			background:var(--bg-light-gray);color:var(--text-color);font-size:11px;}
		.wa-thread-header .wa-header-via .fa-whatsapp{color:#25d366;}
		.wa-readonly-bar{background:var(--card-bg);border-top:1px solid var(--border-color);padding:12px 16px;color:var(--text-muted);text-align:center;font-size:13px;}
		.wa-conv-list{overflow-y:auto;flex:1;padding:0 6px 6px;}
		.wa-conv{display:flex;gap:10px;align-items:center;padding:8px;border-radius:10px;cursor:pointer;}
		.wa-conv:hover{background:var(--bg-light-gray);}
		.wa-conv.active{background:var(--wa-accent);color:#fff;}
		.wa-conv.active .wa-last,.wa-conv.active .wa-time{color:rgba(255,255,255,.85);}
		.wa-conv.active .wa-badge{background:#fff;color:var(--wa-accent);}
		.wa-conv-main{flex:1;min-width:0;}
		.wa-conv .wa-name{font-weight:600;font-size:var(--text-md);display:flex;align-items:baseline;gap:6px;}
		.wa-conv .wa-name .wa-title{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
		.wa-conv .wa-name .fa-bell-slash-o{font-size:11px;opacity:.6;}
		.wa-time{flex:none;font-weight:400;font-size:11px;color:var(--text-muted);}
		.wa-conv-sub{display:flex;align-items:center;gap:6px;margin-top:2px;}
		.wa-conv .wa-last{flex:1;color:var(--text-muted);font-size:var(--text-sm);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
		.wa-badge{flex:none;background:var(--wa-accent);color:#fff;border-radius:11px;min-width:22px;height:22px;line-height:22px;
			text-align:center;font-size:12px;font-weight:600;padding:0 6px;}
		.wa-badge.wa-muted{background:var(--gray-500,#a0a8b0);}
		.wa-thread-wrap{flex:1;display:flex;flex-direction:column;min-width:0;position:relative;background:var(--wa-thread-bg);}
		.wa-thread-header{display:flex;align-items:center;gap:10px;padding:8px 14px;min-height:56px;
			border-bottom:1px solid var(--border-color);background:var(--card-bg);}
		.wa-thread-header .wa-header-main{flex:1;min-width:0;cursor:pointer;}
		.wa-thread-header .wa-header-title{font-weight:600;font-size:var(--text-md);color:var(--text-color);
			overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
		.wa-thread-header .wa-header-sub{font-size:var(--text-sm);color:var(--text-muted);}
		.wa-thread-header .wa-header-main:hover .wa-header-title{color:var(--wa-accent);}
		.wa-thread{flex:1;overflow-y:auto;padding:12px 8%;display:flex;flex-direction:column;gap:4px;position:relative;}
		.wa-thread-empty{margin:auto;text-align:center;color:var(--text-muted);}
		.wa-thread-empty .fa{font-size:48px;opacity:.35;margin-bottom:8px;}
		.wa-day{align-self:center;margin:10px 0 6px;padding:3px 12px;border-radius:14px;font-size:12px;font-weight:600;
			background:rgba(0,0,0,.18);color:#fff;position:sticky;top:4px;z-index:2;}
		.wa-new-divider{align-self:stretch;display:flex;align-items:center;gap:8px;margin:8px 0;color:var(--wa-accent);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;}
		.wa-new-divider::before,.wa-new-divider::after{content:"";flex:1;height:1px;background:var(--wa-accent);opacity:.5;}
		.wa-scroll-fab{position:absolute;right:20px;bottom:84px;z-index:5;width:44px;height:44px;border-radius:50%;background:var(--card-bg);
			box-shadow:0 2px 8px rgba(0,0,0,.2);cursor:pointer;display:none;align-items:center;justify-content:center;font-size:16px;color:var(--text-muted);}
		.wa-scroll-fab:hover{color:var(--text-color);}
		.wa-scroll-fab.show{display:flex;}
		.wa-scroll-fab .wa-fab-badge{position:absolute;top:-6px;right:-4px;min-width:20px;height:20px;padding:0 6px;border-radius:10px;background:var(--wa-accent);color:#fff;font-size:11px;line-height:20px;text-align:center;font-weight:600;}
		.wa-bubble{position:relative;width:fit-content;max-width:min(70%,560px);padding:6px 10px 6px 11px;border-radius:14px;font-size:14px;
			line-height:1.4;text-align:left;word-break:break-word;box-shadow:0 1px 1px rgba(0,0,0,.12);}
		.wa-body{white-space:pre-wrap;}
		.wa-bubble::after{content:"";display:table;clear:both;}
		.wa-body a{color:var(--wa-accent);text-decoration:underline;}
		.wa-in{align-self:flex-start;background:var(--wa-in);color:var(--text-color);border-bottom-left-radius:4px;}
		.wa-out{align-self:flex-end;background:var(--wa-out);color:var(--wa-out-text);border-bottom-right-radius:4px;}
		.wa-meta{float:right;display:inline-flex;align-items:center;gap:4px;margin:6px 0 -4px 10px;font-size:11px;line-height:1;
			color:var(--text-muted);white-space:nowrap;user-select:none;}
		.wa-out .wa-meta{color:var(--wa-tick);}
		.wa-out .wa-meta .wa-time-txt{color:var(--text-muted);}
		[data-theme="dark"] .wa-out .wa-meta .wa-time-txt{color:rgba(255,255,255,.6);}
		.wa-ticks{display:inline-flex;}
		.wa-ticks .fa + .fa{margin-left:-6px;}
		.wa-st-failed{color:var(--red-500,#e24c4c);}
		.wa-media{margin:-2px -6px 2px -7px;}
		.wa-media .chat-img,.wa-media .chat-img img{max-width:320px;border-radius:10px;}
		.wa-media video{max-width:320px;border-radius:10px;display:block;}
		.wa-media audio{width:260px;max-width:100%;display:block;}
		.wa-media.wa-sticker img{max-width:140px;}
		.wa-bubble:has(.wa-sticker){background:none;box-shadow:none;}
		.wa-doc{display:inline-flex;align-items:center;gap:10px;color:inherit;text-decoration:none;}
		.wa-doc .wa-doc-icon{flex:none;width:40px;height:40px;border-radius:50%;background:var(--wa-accent);color:#fff;
			display:flex;align-items:center;justify-content:center;font-size:17px;}
		.wa-doc .wa-doc-name{font-weight:600;word-break:break-all;}
		.wa-doc:hover .wa-doc-name{text-decoration:underline;}
		.wa-caption{white-space:pre-wrap;margin-top:4px;}
		.wa-quote{border-left:3px solid var(--wa-accent);padding:3px 8px;margin-bottom:4px;background:rgba(51,144,236,.1);border-radius:4px 8px 8px 4px;font-size:12px;}
		.wa-quote .wa-quote-author{font-weight:600;color:var(--wa-accent);}
		.wa-bubble-failed{box-shadow:0 0 0 1px var(--red-500,#e24c4c);}
		.wa-fail{clear:both;margin-top:6px;font-size:12px;color:var(--red-600,#c0392b);background:rgba(226,76,76,.08);border-radius:6px;padding:4px 8px;white-space:pre-wrap;}
		.wa-resend{display:inline-block;margin-left:6px;cursor:pointer;font-weight:600;white-space:nowrap;}
		.wa-resend:hover{text-decoration:underline;}
		.wa-reactions{position:absolute;bottom:-12px;right:8px;display:flex;gap:2px;}
		.wa-bubble:has(.wa-reactions){margin-bottom:14px;}
		.wa-react-badge{background:var(--card-bg);border-radius:10px;padding:0 5px;font-size:12px;line-height:18px;box-shadow:0 1px 3px rgba(0,0,0,.2);}
		.wa-bubble-actions{position:absolute;top:50%;transform:translateY(-50%);display:none;gap:4px;}
		.wa-in .wa-bubble-actions{left:100%;padding-left:6px;}
		.wa-out .wa-bubble-actions{right:100%;padding-right:6px;}
		.wa-bubble:hover .wa-bubble-actions{display:flex;}
		.wa-act{cursor:pointer;background:var(--card-bg);border-radius:50%;width:28px;height:28px;line-height:28px;text-align:center;
			font-size:13px;color:var(--text-muted);box-shadow:0 1px 3px rgba(0,0,0,.2);}
		.wa-act:hover{color:var(--wa-accent);}
		.wa-react-pop{position:absolute;z-index:1050;background:var(--card-bg);border-radius:20px;padding:4px 8px;display:flex;gap:6px;box-shadow:0 4px 16px rgba(0,0,0,.2);}
		.wa-react-pop span{cursor:pointer;font-size:20px;transition:transform .1s;}
		.wa-react-pop span:hover{transform:scale(1.3);}
		.wa-emoji-pop{position:absolute;z-index:1050;background:var(--card-bg);border-radius:12px;padding:8px;display:grid;grid-template-columns:repeat(6,1fr);gap:2px;box-shadow:0 4px 16px rgba(0,0,0,.2);}
		.wa-emoji-pop span{cursor:pointer;font-size:20px;padding:4px;text-align:center;border-radius:6px;}
		.wa-emoji-pop span:hover{background:var(--bg-light-gray);}
		.wa-compose-wrap{background:var(--card-bg);border-top:1px solid var(--border-color);}
		.wa-reply-bar{display:flex;align-items:center;gap:10px;padding:6px 14px 0;font-size:13px;}
		.wa-reply-icon{color:var(--wa-accent);font-size:16px;}
		.wa-reply-bar-text{border-left:2px solid var(--wa-accent);padding-left:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;}
		.wa-reply-cancel{cursor:pointer;color:var(--text-muted);font-size:15px;padding:4px;}
		.wa-reply-cancel:hover{color:var(--text-color);}
		.wa-compose{display:flex;gap:2px;padding:8px 10px;align-items:flex-end;}
		.wa-compose textarea{flex:1;min-width:0;resize:none;border:none;outline:none;box-shadow:none;background:none;
			color:var(--text-color);font-size:14px;line-height:20px;padding:8px 6px;max-height:180px;overflow-y:auto;}
		.wa-context{width:280px;border-left:1px solid var(--border-color);overflow-y:auto;padding:14px;}
		.wa-context h6{margin:16px 0 6px;font-size:var(--text-xs,11px);text-transform:uppercase;color:var(--text-muted);letter-spacing:.06em;}
		.wa-ent{display:flex;align-items:center;justify-content:space-between;padding:7px 10px;border-radius:8px;margin-bottom:4px;
			font-size:var(--text-sm);background:var(--bg-light-gray);}
		.wa-ent .wa-ent-main{cursor:pointer;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
		.wa-ent .wa-ent-main:hover{color:var(--wa-accent);}
		.wa-ent .wa-ent-dt{color:var(--text-muted);font-size:10px;}
		.wa-ent .wa-unlink{cursor:pointer;color:var(--text-muted);margin-left:6px;}
		.wa-ent .wa-unlink:hover{color:var(--red-500);}
		.wa-context-actions{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;}
		.wa-context-actions .btn .fa{margin-right:4px;color:var(--text-muted);}
		@media (max-width:1200px){.wa-context{display:none;}}
		@media (max-width:768px){.wa-sidebar{width:220px;}.wa-thread{padding:10px;}}
		`;
		$(`<style id="wa-chat-styles-v8">${css}</style>`).appendTo(document.head);
	}

	// One row while the text fits, then grow; the mic turns into Send once there is text.
	autosize() {
		const el = this.$input[0];
		if (!el) return;
		el.style.height = "auto";
		el.style.height = el.scrollHeight + "px";
		const has_text = !!(this.$input.val() || "").trim();
		this.page.main.find(".wa-send").toggle(has_text);
		this.page.main.find(".wa-mic").toggle(!has_text);
	}

	fill_number_filter() {
		if (this.numbers.length < 2) return;
		for (const n of this.numbers) {
			this.$numberFilter.append(
				`<option value="${frappe.utils.escape_html(n.name)}">${frappe.utils.escape_html(
					n.label
				)}</option>`
			);
		}
		this.$numberFilter.show();
	}

	async apply_number_filter() {
		this.account_filter = this.$numberFilter.val() || null;
		await this.refresh(true);
	}

	number_label(account) {
		const n = this.numbers.find((x) => x.name === account);
		return (n && n.label) || account || "";
	}

	// Reload the conversation list (cheap — one row per dialog) and top up the open
	// thread with whatever arrived since its newest loaded message. Message history
	// itself is never bulk-loaded; see load_page / load_older.
	async refresh(silent) {
		const chats = await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.get_chats", {
			account: this.account_filter || null,
		});

		const next = {};
		for (const c of chats) {
			const prev = this.conversations[c.name] || {};
			next[c.name] = {
				id: c.name,
				number: c.phone,
				account: c.whatsapp_account,
				number_label: c.number_label,
				read_only: !!c.read_only,
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
		if (this.active && !next[this.active] && this.conversations[this.active]) {
			next[this.active] = this.conversations[this.active];
		}
		this.conversations = next;
		this.render_list();

		if (this.active) await this.load_new(!silent);

		if (this.pending_chat) {
			const chat = this.pending_chat;
			this.pending_chat = null;
			if (this.conversations[chat]) this.open(chat);
		} else if (this.pending_phone) {
			const phone = this.pending_phone;
			this.pending_phone = null;
			this.open_phone(phone);
		}
	}

	// Newest page of history for the open conversation.
	async load_page() {
		const c = this.conversations[this.active];
		if (!c) return;
		const msgs = await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.get_messages", {
			chat: this.active,
			limit: PAGE_SIZE,
		});
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
			(x) => x.type === "Incoming" && x.content_type !== "reaction" && (!cursor || x.creation > cursor)
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
			const older = await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.get_messages", {
				chat: this.active,
				before: c.messages[0].creation,
				limit: PAGE_SIZE,
			});
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
		const fresh = await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.get_messages", {
			chat: this.active,
			after: tail[0].creation,
			limit: 200,
		});
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
			const res = await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.mark_read", {
				chat: number,
				upto: upto || null,
			});
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
					m.type === "Incoming" && m.content_type !== "reaction" && (!cursor || m.creation > cursor)
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
		this.$fab
			.find(".wa-fab-badge")
			.toggle(n > 0)
			.text(n > 99 ? "99+" : n);
	}

	// FAB / "mark all read": jump to the newest message and clear the conversation's unread.
	jump_to_latest() {
		this.$thread.scrollTop(this.$thread[0].scrollHeight);
		this.mark_read(this.active);
		this.update_fab();
	}

	// Deep-link / phone icon: open the newest chat with this customer among my numbers,
	// or start one (asking which number to write from when there is a choice).
	async open_phone(raw) {
		const phone = String(raw || "").replace(/\D/g, "");
		if (!phone) return;
		const existing = await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.find_chats", {
			phone,
		});
		const known = existing.find((c) => this.conversations[c.name]);
		if (known) return this.open(known.name);
		this.start_chat(phone);
	}

	writable_numbers() {
		return this.numbers.filter((n) => !n.read_only);
	}

	// Ask for the business number when the user answers more than one.
	pick_number(title, callback, extra_fields) {
		const writable = this.writable_numbers();
		if (!writable.length) {
			frappe.msgprint(
				__("You can only read chats — no WhatsApp number is assigned to you as responsible.")
			);
			return;
		}
		const fields = [...(extra_fields || [])];
		// Plain-string options: frappe.prompt does not bind {value, label} Select options.
		const by_label = {};
		writable.forEach((n) => (by_label[n.label] = n.name));
		if (writable.length > 1) {
			const current = writable.find((n) => n.name === this.account_filter) || writable[0];
			fields.push({
				fieldname: "number",
				fieldtype: "Select",
				label: __("Write from number"),
				reqd: 1,
				options: writable.map((n) => n.label).join("\n"),
				default: current.label,
			});
		}
		if (!fields.length) return callback({ account: writable[0].name });
		frappe.prompt(
			fields,
			(v) => callback({ ...v, account: by_label[v.number] || writable[0].name }),
			title,
			__("Start")
		);
	}

	start_chat(phone) {
		this.pick_number(__("New chat with +{0}", [phone]), async ({ account }) => {
			const chat = await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.start_chat", {
				phone,
				account,
			});
			this.pending_chat = chat;
			await this.refresh(true);
		});
	}

	new_chat_prompt() {
		this.pick_number(
			__("New chat"),
			async ({ phone, account }) => {
				const chat = await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.start_chat", {
					phone,
					account,
				});
				this.pending_chat = chat;
				await this.refresh(true);
			},
			[
				{
					fieldname: "phone",
					fieldtype: "Data",
					label: __("Phone number"),
					reqd: 1,
					description: __("Include country code, e.g. 380XXXXXXXXX"),
				},
			]
		);
	}

	render_list() {
		const q = (this.$search.val() || "").toLowerCase();
		let convs = Object.values(this.conversations);
		convs = convs
			.filter(
				(c) =>
					!q ||
					c.number.toLowerCase().includes(q) ||
					(c.name || "").toLowerCase().includes(q) ||
					(c.number_label || "").toLowerCase().includes(q)
			)
			.sort((a, b) => (b.last_message_on || "").localeCompare(a.last_message_on || ""));

		this.$list.empty();
		if (!convs.length) {
			this.$list.html(
				`<div class="text-muted" style="padding:12px;">${__("No conversations yet")}</div>`
			);
			return;
		}
		for (const c of convs) {
			const preview = frappe.utils
				.escape_html(this.preview_text({ content_type: c.preview_content_type, message: c.preview }))
				.slice(0, 40);
			const badge = c.unread
				? `<span class="wa-badge ${c.muted ? "wa-muted" : ""}">${
						c.unread > 99 ? "99+" : c.unread
				  }</span>`
				: "";
			const muted = c.muted ? `<i class="fa fa-bell-slash-o"></i>` : "";
			// With several numbers, tag each row with the number it runs on.
			const via =
				this.numbers.length > 1 && !this.account_filter
					? `<span class="wa-via" title="${__("WhatsApp number")}">${frappe.utils.escape_html(
							c.number_label || ""
					  )}</span>`
					: "";
			const $el = $(`
				<div class="wa-conv ${c.id === this.active ? "active" : ""} ${c.unread ? "wa-unread" : ""}">
					${avatar_html(c.name, c.number)}
					<div class="wa-conv-main">
						<div class="wa-name"><span class="wa-title">${frappe.utils.escape_html(
							c.name
						)}</span>${muted}<span class="wa-time">${list_time(c.last_message_on)}</span></div>
						<div class="wa-conv-sub"><span class="wa-last">${media_icon(
							c.preview_content_type
						)}${preview}</span>${via}${badge}</div>
					</div>
				</div>
			`);
			$el.on("click", () => this.open(c.id));
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
		const read_only = !!(c && c.read_only);
		this.$compose.toggle(!read_only);
		this.$readonly.toggle(read_only);
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
			if (ct === "video")
				return `<div class="wa-media"><video controls src="${url}"></video></div>${cap_html}`;
			if (ct === "audio")
				return `<div class="wa-media"><audio controls src="${url}"></audio></div>${cap_html}`;
			if (ct === "document") {
				const fname = frappe.utils.escape_html(
					decodeURIComponent(m.attach.split("/").pop() || __("Document"))
				);
				return `<a class="wa-doc" href="${url}" target="_blank" download><span class="wa-doc-icon"><i class="fa fa-file-o"></i></span><span class="wa-doc-name">${fname}</span></a>${cap_html}`;
			}
		}
		// Unresolved media (attach missing) or text.
		if (MEDIA_TYPES.includes(ct))
			return `<i>${media_icon(ct)}${frappe.utils.escape_html(
				media_label(ct) || __("Media")
			)}</i>${cap_html}`;
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
		let last_day = null;
		for (const m of c.messages) {
			if (m.content_type === "reaction") continue; // rendered as badges, not bubbles
			const local = moment.tz(m.creation, sys_tz).local();
			const day = local.format("YYYY-MM-DD");
			if (day !== last_day) {
				last_day = day;
				this.$thread.append(
					`<div class="wa-day">${frappe.utils.escape_html(day_label(local))}</div>`
				);
			}
			// "New messages" divider, anchored at the first message that was unread on open.
			if (this.new_divider_before && m.name === this.new_divider_before) {
				this.$thread.append(`<div class="wa-new-divider">${__("New messages")}</div>`);
			}
			const out = m.type === "Outgoing";
			const time = local.format("HH:mm");
			const failed = out && (m.status || "").toLowerCase() === "failed";
			const status = out ? status_icon(m.status) : "";

			// Failure notice + Resend for outgoing messages Meta rejected.
			let fail_html = "";
			if (failed && m.content_type !== "reaction") {
				const reason = frappe.utils.escape_html(m.status_error || __("Message failed to send"));
				const resend = c.read_only
					? ""
					: `<span class="wa-resend" title="${__("Resend")}"><i class="fa fa-repeat"></i> ${__(
							"Resend"
					  )}</span>`;
				fail_html = `<div class="wa-fail"><i class="fa fa-exclamation-triangle"></i> ${reason}
					${resend}</div>`;
			}

			// Reply quote.
			let quote = "";
			if (m.is_reply && m.reply_to_message_id && this.msg_by_id[m.reply_to_message_id]) {
				const tgt = this.msg_by_id[m.reply_to_message_id];
				const author = tgt.type === "Outgoing" ? __("You") : c.name || tgt.from || "";
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
			const react_btn = m.message_id
				? `<span class="wa-act wa-do-react" title="${__(
						"React"
				  )}"><i class="fa fa-smile-o"></i></span>`
				: "";
			// Spectators read only: no reply / react / resend on their side.
			const actions = c.read_only
				? ""
				: `<div class="wa-bubble-actions">${react_btn}<span class="wa-act wa-do-reply" title="${__(
						"Reply"
				  )}"><i class="fa fa-reply"></i></span></div>`;

			const $b = $(
				`<div class="wa-bubble ${out ? "wa-out" : "wa-in"} ${
					failed ? "wa-bubble-failed" : ""
				}" data-mid="${frappe.utils.escape_html(
					m.message_id || ""
				)}">${actions}${quote}${this.render_body(
					m
				)}<span class="wa-meta"><span class="wa-time-txt">${time}</span>${status}</span>${fail_html}${react_html}</div>`
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
					chat: this.active,
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
					chat: this.active,
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
			this.$replyBar
				.find(".wa-reply-bar-text")
				.text(`${__("Replying to")}: ${reply.preview.slice(0, 60)}`);
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
			`<div class="wa-react-pop">${QUICK_REACTIONS.map((x) => `<span data-e="${x}">${x}</span>`).join(
				""
			)}</div>`
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
				chat: this.active,
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
						chat: this.active,
						attach: file.file_url,
						content_type,
						caption: (this.$input.val() || "").trim(),
						reply_to_message_id: this.reply_to ? this.reply_to.message_id : null,
					});
					this.$input.val("");
					this.autosize();
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

	// Record a voice message and send it as audio. The server transcodes to an
	// ogg/opus file when the browser could only produce webm (Chrome), so Meta accepts it.
	async record_voice() {
		if (!this.active) return;
		const rec = await erpnext.chat_media.record_audio();
		if (!rec) return;
		frappe.dom.freeze(__("Sending..."));
		try {
			const url = await erpnext.chat_media.upload_audio(rec.blob, rec.ext);
			await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.send_media", {
				chat: this.active,
				attach: url,
				content_type: "audio",
				caption: "",
				reply_to_message_id: this.reply_to ? this.reply_to.message_id : null,
			});
			this.set_reply(null);
			await this.refresh();
			this.render_thread(true);
		} catch (err) {
			frappe.msgprint(__("Failed to send voice message"));
		} finally {
			frappe.dom.unfreeze();
		}
	}

	emoji_picker(e) {
		e.stopPropagation();
		$(".wa-emoji-pop").remove();
		const $pop = $(
			`<div class="wa-emoji-pop">${EMOJI_SET.map((x) => `<span>${x}</span>`).join("")}</div>`
		);
		$("body").append($pop);
		const off = $(e.currentTarget).offset();
		$pop.css({ top: off.top - $pop.outerHeight() - 8, left: off.left + 36 - $pop.outerWidth() });
		$pop.find("span").on("click", (ev) => {
			const el = this.$input[0];
			const emoji = $(ev.currentTarget).text();
			const start = el.selectionStart || 0;
			const val = this.$input.val();
			this.$input.val(val.slice(0, start) + emoji + val.slice(el.selectionEnd || start));
			this.autosize();
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
			templates = await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.list_templates");
		} catch (e) {
			frappe.msgprint(__("Could not load templates"));
			return;
		}
		if (!templates || !templates.length) {
			frappe.msgprint(__("No approved templates found. Create and sync a WhatsApp Template first."));
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
				chat: this.active,
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
		this.$header.html(`${avatar_html(c.name, c.number, 38)}
			<div class="wa-header-main" title="${__("Chat info")}">
				<div class="wa-header-title"></div>
				<div class="wa-header-sub"></div>
			</div>
			${erpnext.chat_sound.button_html(c.muted)}
			<span class="chat-mute-btn wa-info-btn" title="${__("Chat info")}"><i class="fa fa-info-circle"></i></span>`);
		this.$header.find(".wa-header-title").text(c.name);
		// Which business number this conversation runs on — the one replies go out from.
		this.$header
			.find(".wa-header-sub")
			.text(c.name === c.number ? __("WhatsApp") : `+${c.number}`)
			.append(
				$(`<span class="wa-header-via" title="${__("You write from this number")}">
					<i class="fa fa-whatsapp"></i><span></span></span>`)
			);
		this.$header
			.find(".wa-header-via span")
			.text(__("via {0}", [c.number_label || this.number_label(c.account)]));
		this.$header.find(".wa-header-main, .wa-info-btn").on("click", () => this.show_info());
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
				chat: number,
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
		const info = await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.get_chat_overview", {
			chat: this.active,
		});

		const media = info.media.map((m) => ({
			sender_name: m.sender_name,
			creation: m.creation,
			caption: m.caption,
			html:
				m.content_type === "image" || m.content_type === "sticker"
					? erpnext.chat_media.image_html(m.attach)
					: null,
			icon: `<i class="fa fa-${m.content_type === "video" ? "video-camera" : "music"}"></i>`,
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
				subtitle: `+${info.phone}`,
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
			people.push({ name: m.full_name || m.user, subtitle: __("Responsible") });
		}

		const to_items = (rows) =>
			(rows || []).map((e) => ({
				title: e.label || e.name,
				subtitle: e.doctype,
				on_click: () => frappe.set_route("Form", e.doctype, e.name),
			}));

		const dialog = erpnext.chat_info.show({
			title: info.title,
			subtitle: `+${info.phone} · ${__("via {0}", [info.number_label])}`,
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
				{ chat: number }
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
				? `<span class="wa-unlink" title="${__("Unlink")}"><i class="fa fa-times"></i></span>`
				: "";
			return `<div class="wa-ent" data-dt="${frappe.utils.escape_html(
				e.doctype
			)}" data-nm="${frappe.utils.escape_html(e.name)}">
				<span class="wa-ent-main">${frappe.utils.escape_html(
					e.label
				)}<div class="wa-ent-dt">${frappe.utils.escape_html(e.doctype)}</div></span>${unlink}
			</div>`;
		};

		const read_only = !!ctx.read_only;
		const linked =
			(ctx.linked || []).map((e) => ent(e, !read_only)).join("") ||
			`<div class="text-muted" style="font-size:var(--text-sm);">${__("None")}</div>`;
		const derived = (ctx.derived || []).map((e) => ent(e, false)).join("");
		const managerNames = (ctx.managers || [])
			.map((m) => frappe.utils.escape_html(m.full_name || m.user))
			.join(", ");
		const actions = read_only
			? ""
			: `<div class="wa-context-actions">
				<button class="btn btn-xs btn-default wa-link-btn"><i class="fa fa-link"></i>${__("Link Document")}</button>
			</div>
			<h6>${__("Create from Chat")}</h6>
			<div class="wa-context-actions">
				<button class="btn btn-xs btn-default wa-new-opp"><i class="fa fa-handshake-o"></i>${__(
					"Opportunity"
				)}</button>
				<button class="btn btn-xs btn-default wa-new-todo"><i class="fa fa-check-square-o"></i>${__("Task")}</button>
				<button class="btn btn-xs btn-default wa-new-note"><i class="fa fa-sticky-note-o"></i>${__("Note")}</button>
				<button class="btn btn-xs btn-default wa-new-event"><i class="fa fa-calendar"></i>${__("Event")}</button>
			</div>`;

		this.$context.html(`
			<h6>${__("WhatsApp number")}</h6>
			<div class="wa-ent"><span class="wa-ent-plain"><i class="fa fa-whatsapp" style="color:#25d366"></i> ${frappe.utils.escape_html(
				ctx.number_label || ""
			)}<div class="wa-ent-dt">${frappe.utils.escape_html(ctx.account_name || "")}${
			read_only ? " · " + __("read only") : ""
		}</div></span></div>
			${actions}
			<h6>${__("Linked Documents")}</h6>
			<div class="wa-linked">${linked}</div>
			${derived ? `<h6>${__("Related (by contact)")}</h6><div class="wa-derived">${derived}</div>` : ""}
			<h6>${__("Responsible")}</h6>
			<div class="text-muted" style="font-size:var(--text-sm);">${managerNames || __("None")}</div>
		`);

		this.$context.find(".wa-ent-main").on("click", (e) => {
			const $c = $(e.currentTarget).closest(".wa-ent");
			frappe.set_route("Form", $c.data("dt"), $c.data("nm"));
		});
		this.$context.find(".wa-unlink").on("click", async (e) => {
			const $c = $(e.currentTarget).closest(".wa-ent");
			this.context = await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.unlink_entity", {
				chat: number,
				link_doctype: $c.data("dt"),
				link_name: $c.data("nm"),
			});
			this.render_context(number);
		});
		this.$context.find(".wa-link-btn").on("click", () => this.link_dialog(number));
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
				{ chat: number }
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
				const res = await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.create_todo", {
					chat: number,
					description: v.description,
				});
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
				const res = await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.create_note", {
					chat: number,
					title: v.title,
					content: v.content,
				});
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
				const res = await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.create_event", {
					chat: number,
					subject: v.subject,
					starts_on: v.starts_on,
				});
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
				{
					fieldname: "link_name",
					fieldtype: "Dynamic Link",
					label: __("Document"),
					options: "link_doctype",
					reqd: 1,
				},
			],
			primary_action_label: __("Link"),
			primary_action: async (v) => {
				this.context = await frappe.xcall(
					"erpnext.crm.page.whatsapp_chat.whatsapp_chat.link_entity",
					{ chat: number, link_doctype: v.link_doctype, link_name: v.link_name }
				);
				d.hide();
				this.render_context(number);
			},
		});
		d.show();
	}

	async send() {
		const text = (this.$input.val() || "").trim();
		if (!text || !this.active) return;
		this.$input.val("");
		this.autosize();
		const reply_id = this.reply_to ? this.reply_to.message_id : null;
		this.set_reply(null);
		try {
			await frappe.xcall("erpnext.crm.page.whatsapp_chat.whatsapp_chat.send_text", {
				chat: this.active,
				message: text,
				reply_to_message_id: reply_id,
			});
			await this.refresh();
			this.render_thread(true);
		} catch (e) {
			frappe.msgprint(__("Failed to send message"));
			this.$input.val(text);
			this.autosize();
		}
	}
}
