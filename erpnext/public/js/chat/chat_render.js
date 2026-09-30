// Shared rendering for every chat surface: the WhatsApp and Employee Chat pages and the
// floating chat bubble. One look (the Telegram-style design) and one set of rules for
// what a message looks like — a change here shows up everywhere at once.
//
// Everything renders a *normalized* message built by a chat source
// (erpnext/public/js/chat/sources/*.js):
//   {id, out, time, author, content_type, text, attach, link_data,
//    is_encrypted, dec, dec_failed, status, error, quote, reply_target,
//    reactions: [{emoji, count, mine}], can_react, can_reply, can_resend}

frappe.provide("erpnext.chat_render");

(function (R) {
	const esc = (v) => frappe.utils.escape_html(v === null || v === undefined ? "" : String(v));

	R.EMOJI_SET = [
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
	R.QUICK_REACTIONS = R.EMOJI_SET.slice(0, 6);
	R.MEDIA_TYPES = ["image", "video", "audio", "document", "sticker", "file"];
	R.URL_RE = /https?:\/\/[^\s<>"']+/g;

	// --- small pieces -----------------------------------------------------------

	R.media_label = function (content_type) {
		return {
			image: __("Photo"),
			video: __("Video"),
			audio: __("Audio"),
			document: __("Document"),
			file: __("File"),
			sticker: __("Sticker"),
			link: __("Link"),
		}[content_type];
	};

	R.media_icon = function (content_type) {
		const icon = {
			image: "camera",
			video: "video-camera",
			audio: "microphone",
			document: "file-o",
			file: "paperclip",
			sticker: "smile-o",
			link: "link",
		}[content_type];
		return icon ? `<i class="fa fa-${icon}"></i> ` : "";
	};

	// One line describing a message — chat list preview, reply quote, notifications.
	R.preview_text = function (m) {
		if (!m) return "";
		if (m.is_encrypted) {
			if (!m.dec) return __("Encrypted");
			if (m.dec.link) return m.dec.link.title || __("Link");
			if (m.dec.file) return m.dec.text || m.dec.file.name || R.media_label(m.content_type) || "";
			return m.dec.text || "";
		}
		if (m.content_type === "reaction") return `${m.text || ""} ${__("reacted")}`.trim();
		if (m.content_type === "link") return (m.link_data || {}).title || m.text || __("Link");
		const text = (m.text || "").replace(/<[^>]*>/g, "").trim();
		if (R.MEDIA_TYPES.includes(m.content_type)) {
			const label = R.media_label(m.content_type) || "";
			return text ? `${label}: ${text}` : label;
		}
		return text;
	};

	R.initials = function (name) {
		const parts = String(name || "?")
			.replace(/[^\p{L}\p{N} ]/gu, "")
			.trim()
			.split(/\s+/)
			.filter(Boolean);
		if (!parts.length) return "#";
		return ((parts[0][0] || "") + (parts.length > 1 ? parts[1][0] : "")).toUpperCase();
	};

	// Stable colour per conversation, so the same chat keeps its avatar colour.
	R.avatar_color = function (key) {
		const palette = [
			"#e17076",
			"#7bc862",
			"#e5ca77",
			"#65aadd",
			"#a695e7",
			"#ee7aae",
			"#6ec9cb",
			"#faa774",
		];
		let h = 0;
		for (const ch of String(key || "")) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
		return palette[h % palette.length];
	};

	// {name, key, image, icon}: a photo, an icon (group / document chat) or initials.
	R.avatar_html = function (a, size) {
		a = a || {};
		const dim = size
			? `width:${size}px;height:${size}px;line-height:${size}px;font-size:${Math.round(size / 2.9)}px;`
			: "";
		if (a.image) {
			return `<div class="cv-avatar" style="${dim}"><img src="${esc(a.image)}" alt=""></div>`;
		}
		const inner = a.icon ? `<i class="${esc(a.icon)}"></i>` : esc(R.initials(a.name));
		return `<div class="cv-avatar" style="background:${R.avatar_color(
			a.key || a.name
		)};${dim}">${inner}</div>`;
	};

	R.local = function (dt) {
		return moment.tz(dt, frappe.sys_defaults.time_zone || "UTC").local();
	};

	// Month and weekday names in the user's language — moment ships without most locales,
	// the browser has them all.
	R.format_date = function (m, options) {
		try {
			return new Intl.DateTimeFormat(frappe.boot.lang || undefined, options).format(m.toDate());
		} catch (e) {
			return m.format("DD.MM.YYYY");
		}
	};

	// List timestamp: time for today, weekday within a week, date otherwise.
	R.list_time = function (dt) {
		if (!dt) return "";
		const m = R.local(dt);
		const now = moment();
		if (m.isSame(now, "day")) return m.format("HH:mm");
		if (now.diff(m, "days") < 7) return R.format_date(m, { weekday: "short" });
		return m.format("DD.MM.YY");
	};

	R.day_label = function (m) {
		const now = moment();
		if (m.isSame(now, "day")) return __("Today");
		if (m.isSame(now.clone().subtract(1, "day"), "day")) return __("Yesterday");
		return R.format_date(
			m,
			m.isSame(now, "year")
				? { day: "numeric", month: "long" }
				: { day: "numeric", month: "long", year: "numeric" }
		);
	};

	// Delivery state of an outgoing message: pending → sent → delivered → read, or failed.
	R.status_icon = function (status) {
		const st = (status || "").toLowerCase();
		if (!st) return "";
		const label = esc(__(status));
		if (st === "failed") return `<i class="fa fa-exclamation-circle cv-st-failed" title="${label}"></i>`;
		if (st === "read" || st === "seen")
			return `<span class="cv-ticks cv-st-read" title="${label}"><i class="fa fa-check"></i><i class="fa fa-check"></i></span>`;
		if (st === "delivered")
			return `<span class="cv-ticks" title="${label}"><i class="fa fa-check"></i><i class="fa fa-check"></i></span>`;
		if (st === "sent" || st === "success") return `<i class="fa fa-check" title="${label}"></i>`;
		return `<i class="fa fa-clock-o" title="${label}"></i>`;
	};

	// --- text ---------------------------------------------------------------------

	// Escaped text with clickable links.
	R.linkify = function (text) {
		const src = String(text || "");
		let out = "";
		let last = 0;
		for (const m of src.matchAll(R.URL_RE)) {
			out += esc(src.slice(last, m.index));
			out += `<a href="${esc(m[0])}" target="_blank" rel="noopener">${esc(m[0])}</a>`;
			last = m.index + m[0].length;
		}
		return out + esc(src.slice(last));
	};

	R.is_long = function (text) {
		const t = text || "";
		return t.length > 600 || t.split("\n").length > 12;
	};

	// A wall of text would push every other message off the screen. Long bodies are
	// clipped to a preview with a toggle; the full text stays in the DOM so Ctrl+F and
	// copying still see all of it.
	R.text_html = function (text, cls) {
		const html = R.linkify(text);
		if (!R.is_long(text)) return `<span class="${cls}">${html}</span>`;
		return `<div class="${cls} cv-clampable cv-clamp">${html}</div><span class="cv-more">${__(
			"Show more"
		)}</span>`;
	};

	// --- cards ----------------------------------------------------------------------

	// A shared ERPNext object (document, report, list) as a card.
	R.link_card_html = function (card) {
		if (!card || !card.url) return `<i>(${__("link")})</i>`;
		const icon = card.image
			? `<img src="${esc(card.image)}" alt="">`
			: `<i class="fa fa-${
					{ document: "file-text-o", report: "bar-chart", list: "list-ul" }[card.kind] || "link"
			  }"></i>`;
		const removed = !!card.removed;
		const badge = removed ? `<span class="cv-tag cv-tag-red">${__("Removed")}</span>` : "";
		// A deleted target has nowhere to go: drop the href so the card is inert but legible.
		const attrs = removed ? "" : ` href="${esc(card.url)}" target="_blank" rel="noopener"`;
		const sub = card.subtitle || card.doctype || "";
		return `<a class="cv-card${removed ? " cv-card-removed" : ""}"${attrs}>
			<div class="cv-card-icon">${icon}</div>
			<div class="cv-card-main">
				<div class="cv-card-title">${esc(card.title || card.url)}${badge}</div>
				${sub ? `<div class="cv-card-sub">${esc(sub)}</div>` : ""}
			</div>
		</a>`;
	};

	// The record a document chat is about, pinned above its messages.
	R.reference_banner_html = function (chat) {
		const dt = chat.reference_doctype;
		const name = chat.reference_name;
		const removed = !!chat.reference_removed;
		const badge = removed ? `<span class="cv-tag cv-tag-red">${__("Removed")}</span>` : "";
		const arch =
			chat.is_archived && !removed ? `<span class="cv-tag cv-tag-gray">${__("Archived")}</span>` : "";
		const data = removed ? "" : ` data-dt="${esc(dt)}" data-name="${esc(name)}"`;
		return `<div class="cv-ref-banner${removed ? " cv-card-removed" : ""}"${data}>
			<div class="cv-card-icon"><i class="fa fa-file-text-o"></i></div>
			<div class="cv-card-main">
				<div class="cv-card-title">${esc(chat.reference_label || name || __("Document"))}${badge}${arch}</div>
				${dt ? `<div class="cv-card-sub">${esc(`${__(dt)} · ${name}`)}</div>` : ""}
			</div>
		</div>`;
	};

	// --- message body -----------------------------------------------------------------

	function file_name_of(url) {
		try {
			return decodeURIComponent((url || "").split("/").pop() || "");
		} catch (e) {
			return (url || "").split("/").pop() || "";
		}
	}

	function doc_html(url, name, extra_cls, extra_attrs) {
		return `<a class="cv-doc ${extra_cls || ""}" ${
			url ? `href="${esc(url)}" target="_blank" download` : `href="#"`
		} ${
			extra_attrs || ""
		}><span class="cv-doc-icon"><i class="fa fa-file-o"></i></span><span class="cv-doc-name">${esc(
			name || __("File")
		)}</span></a>`;
	}

	function encrypted_body(m) {
		if (m.dec_failed)
			return `<span class="cv-locked"><i class="fa fa-lock"></i> ${__(
				"Cannot decrypt this message"
			)}</span>`;
		if (!m.dec) return `<span class="cv-locked"><i class="fa fa-lock"></i> ${__("Encrypted")}</span>`;
		if (m.dec.link) return R.link_card_html(m.dec.link);
		const text = m.dec.text || "";
		const cap = text ? R.text_html(text, "cv-caption") : "";
		const file = m.dec.file;
		const spec = file && {
			url: file.url,
			key: file.key,
			iv: file.iv,
			mime: file.mime,
			file_name: file.name,
		};
		if (file && m.content_type === "audio") {
			return `<div class="cv-media">${erpnext.chat_media.encrypted_audio_html(spec)}</div>${cap}`;
		}
		if (file && m.content_type === "image") {
			const thumb = m.dec.thumb || {};
			return `<div class="cv-media">${erpnext.chat_media.encrypted_image_html({
				...spec,
				thumb_url: thumb.url,
				thumb_key: thumb.key,
				thumb_iv: thumb.iv,
			})}</div>${cap}`;
		}
		if (file) {
			return doc_html(null, file.name, "cv-enc-doc", `data-file="${esc(JSON.stringify(file))}"`) + cap;
		}
		return text ? R.text_html(text, "cv-body") : `<i>(${__("no text")})</i>`;
	}

	R.body_html = function (m) {
		if (m.is_encrypted) return encrypted_body(m);
		const ct = m.content_type;
		const caption = (m.text || "").replace(/<[^>]*>/g, "");
		const cap = caption ? R.text_html(caption, "cv-caption") : "";

		if (ct === "link" && m.link_data) return R.link_card_html(m.link_data);
		if (m.attach) {
			if (ct === "image" || ct === "sticker") {
				const img = erpnext.chat_media.image_html(
					m.attach,
					ct === "sticker" ? "chat-img-sticker" : ""
				);
				return `<div class="cv-media${ct === "sticker" ? " cv-sticker" : ""}">${img}</div>${
					ct === "sticker" ? "" : cap
				}`;
			}
			if (ct === "video") {
				return `<div class="cv-media"><video controls preload="metadata" src="${esc(
					m.attach
				)}"></video></div>${cap}`;
			}
			if (ct === "audio")
				return `<div class="cv-media">${erpnext.chat_media.audio_html(m.attach)}</div>${cap}`;
			return doc_html(m.attach, file_name_of(m.attach)) + cap;
		}
		if (R.MEDIA_TYPES.includes(ct)) {
			return `<i>${R.media_icon(ct)}${esc(R.media_label(ct) || __("Media"))}</i>${cap}`;
		}
		return caption ? R.text_html(caption, "cv-body") : `<i>(${__("no text")})</i>`;
	};

	R.reactions_html = function (m) {
		const list = (m.reactions || []).filter((r) => r.count > 0);
		if (!list.length) return "";
		return `<div class="cv-reactions">${list
			.map(
				(r) =>
					`<span class="cv-react-badge${r.mine ? " cv-mine" : ""}" data-emoji="${esc(
						r.emoji
					)}">${esc(r.emoji)}${
						r.count > 1 ? `<span class="cv-react-count">${r.count}</span>` : ""
					}</span>`
			)
			.join("")}</div>`;
	};

	R.quote_html = function (m) {
		if (!m.quote) return "";
		return `<div class="cv-quote"${m.reply_target ? ` data-target="${esc(m.reply_target)}"` : ""}>
			<div class="cv-quote-author">${esc(m.quote.author || "")}</div>
			<div class="cv-quote-text">${esc((m.quote.text || "").slice(0, 100))}</div>
		</div>`;
	};

	// The whole bubble. `opts.author` shows the sender line (groups, colleagues),
	// `opts.actions` adds the hover bar and the message menu.
	R.bubble_html = function (m, opts) {
		opts = opts || {};
		const out = !!m.out;
		const failed = out && (m.status || "").toLowerCase() === "failed";
		const time = m.time ? R.local(m.time).format("HH:mm") : "";

		let fail = "";
		if (failed) {
			fail = `<div class="cv-fail"><i class="fa fa-exclamation-triangle"></i> ${esc(
				m.error || __("Message failed to send")
			)}${
				m.can_resend
					? ` <span class="cv-resend"><i class="fa fa-repeat"></i> ${__("Resend")}</span>`
					: ""
			}</div>`;
		}

		let actions = "";
		if (opts.actions) {
			const react = m.can_react
				? `<span class="cv-act cv-do-react" title="${__(
						"React"
				  )}"><i class="fa fa-smile-o"></i></span>`
				: "";
			const reply = m.can_reply
				? `<span class="cv-act cv-do-reply" title="${__("Reply")}"><i class="fa fa-reply"></i></span>`
				: "";
			const menu = `<span class="cv-act cv-do-menu" tabindex="0" role="button" title="${__(
				"Message actions"
			)}"><i class="fa fa-ellipsis-v"></i></span>`;
			actions = `<div class="cv-bubble-actions">${react}${reply}${menu}</div>`;
		}

		const author =
			opts.author && m.author
				? `<div class="cv-author" style="color:${R.avatar_color(m.author_key || m.author)}">${esc(
						m.author
				  )}</div>`
				: "";

		return `<div class="cv-bubble ${out ? "cv-out" : "cv-in"}${
			failed ? " cv-bubble-failed" : ""
		}" data-id="${esc(m.id)}">${actions}${author}${R.quote_html(m)}${R.body_html(
			m
		)}<span class="cv-meta"><span class="cv-time">${time}</span>${
			out ? R.status_icon(m.status) : ""
		}</span>${fail}${R.reactions_html(m)}</div>`;
	};

	// Wire the parts of rendered bubbles that work on their own: lazy media, show-more
	// toggles and encrypted downloads. Interactive actions are bound by the chat view.
	R.bind = function ($root, media_source) {
		if (media_source) erpnext.chat_media.bind($root, media_source);
		$root.off("click.cvmore").on("click.cvmore", ".cv-more", (e) => {
			const $more = $(e.currentTarget);
			const $text = $more.prev(".cv-clampable");
			const open = $text.hasClass("cv-clamp");
			$text.toggleClass("cv-clamp", !open);
			$more.text(open ? __("Show less") : __("Show more"));
		});
		$root.off("click.cvenc").on("click.cvenc", ".cv-enc-doc", (e) => {
			e.preventDefault();
			R.download_encrypted(JSON.parse($(e.currentTarget).attr("data-file")));
		});
	};

	// Encrypted documents have no usable URL — decrypt, then hand the blob to the browser.
	R.download_encrypted = async function (file) {
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
	};

	// --- styles -------------------------------------------------------------------------

	R.inject_styles = function () {
		erpnext.chat_media.inject_styles();
		erpnext.chat_sound.inject_styles();
		if (document.getElementById("cv-styles-v1")) return;
		const css = `
		.cv-root{--cv-out:#effdde;--cv-out-text:#111;--cv-in:var(--card-bg);--cv-thread-bg:#e6ebee;--cv-accent:#3390ec;
			--cv-tick:#4fae4e;}
		[data-theme="dark"] .cv-root{--cv-out:#2b5278;--cv-out-text:#fff;--cv-in:#182533;--cv-thread-bg:#0e1621;
			--cv-accent:#5eb5f7;--cv-tick:#5eb5f7;}
		.cv-avatar{flex:none;width:44px;height:44px;border-radius:50%;color:#fff;font-weight:600;font-size:15px;
			line-height:44px;text-align:center;user-select:none;overflow:hidden;}
		.cv-avatar img{width:100%;height:100%;object-fit:cover;}
		.cv-ico{flex:none;width:36px;height:36px;padding:0;border:none;background:none;border-radius:50%;
			color:var(--text-muted);font-size:19px;line-height:36px;text-align:center;cursor:pointer;
			transition:background .15s,color .15s;}
		.cv-ico:hover{background:var(--bg-light-gray);color:var(--text-color);}
		.cv-ico:focus{outline:none;}
		.cv-ico.cv-disabled{opacity:.35;cursor:default;}
		.cv-send,.cv-send:hover{color:var(--cv-accent);}
		.cv-tag{display:inline-block;margin-left:6px;padding:0 6px;border-radius:8px;color:#fff;font-size:10px;font-weight:600;
			line-height:16px;vertical-align:middle;}
		.cv-tag-red{background:var(--red-500,#e24c4c);}
		.cv-tag-gray{background:var(--gray-500,#8d99a6);}
		.cv-tag-muted{background:var(--bg-light-gray);color:var(--text-muted);}
		/* thread */
		.cv-thread{background:var(--cv-thread-bg);display:flex;flex-direction:column;gap:4px;}
		.cv-day{align-self:center;margin:10px 0 6px;padding:3px 12px;border-radius:14px;font-size:12px;font-weight:600;
			background:rgba(0,0,0,.18);color:#fff;position:sticky;top:4px;z-index:2;}
		.cv-new-divider{align-self:stretch;display:flex;align-items:center;gap:8px;margin:8px 0;color:var(--cv-accent);
			font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;}
		.cv-new-divider::before,.cv-new-divider::after{content:"";flex:1;height:1px;background:var(--cv-accent);opacity:.5;}
		.cv-bubble{position:relative;width:fit-content;max-width:min(70%,560px);padding:6px 10px 6px 11px;border-radius:14px;
			font-size:14px;line-height:1.4;text-align:left;word-break:break-word;box-shadow:0 1px 1px rgba(0,0,0,.12);}
		.cv-bubble::after{content:"";display:table;clear:both;}
		.cv-in{align-self:flex-start;background:var(--cv-in);color:var(--text-color);border-bottom-left-radius:4px;}
		.cv-out{align-self:flex-end;background:var(--cv-out);color:var(--cv-out-text);border-bottom-right-radius:4px;}
		.cv-body,.cv-caption{white-space:pre-wrap;}
		.cv-caption{display:block;margin-top:4px;}
		.cv-bubble a{color:var(--cv-accent);}
		.cv-body a,.cv-caption a{text-decoration:underline;}
		.cv-author{font-size:12px;font-weight:600;margin-bottom:2px;}
		.cv-meta{float:right;display:inline-flex;align-items:center;gap:4px;margin:6px 0 -4px 10px;font-size:11px;line-height:1;
			color:var(--text-muted);white-space:nowrap;user-select:none;}
		.cv-out .cv-meta{color:var(--cv-tick);}
		.cv-out .cv-meta .cv-time{color:var(--text-muted);}
		[data-theme="dark"] .cv-out .cv-meta .cv-time{color:rgba(255,255,255,.6);}
		.cv-ticks{display:inline-flex;}
		.cv-ticks .fa + .fa{margin-left:-6px;}
		.cv-st-failed{color:var(--red-500,#e24c4c);}
		.cv-media{margin:-2px -6px 2px -7px;}
		.cv-media .chat-img,.cv-media .chat-img img{max-width:320px;border-radius:10px;}
		.cv-media video{max-width:320px;border-radius:10px;display:block;}
		.cv-media audio{width:260px;max-width:100%;display:block;}
		.cv-media.cv-sticker img{max-width:140px;}
		.cv-bubble:has(.cv-sticker){background:none;box-shadow:none;}
		.cv-doc{display:inline-flex;align-items:center;gap:10px;color:inherit !important;text-decoration:none;}
		.cv-doc-icon{flex:none;width:40px;height:40px;border-radius:50%;background:var(--cv-accent);color:#fff;
			display:flex;align-items:center;justify-content:center;font-size:17px;}
		.cv-doc-name{font-weight:600;word-break:break-all;}
		.cv-doc:hover .cv-doc-name{text-decoration:underline;}
		.cv-locked{color:var(--text-muted);font-style:italic;}
		.cv-clamp{max-height:230px;overflow:hidden;position:relative;display:block;}
		.cv-clamp::after{content:"";position:absolute;left:0;right:0;bottom:0;height:34px;
			background:linear-gradient(to bottom,transparent,var(--cv-in));pointer-events:none;}
		.cv-out .cv-clamp::after{background:linear-gradient(to bottom,transparent,var(--cv-out));}
		.cv-more{cursor:pointer;color:var(--cv-accent);font-size:12px;font-weight:600;margin-top:2px;display:inline-block;user-select:none;}
		.cv-more:hover{text-decoration:underline;}
		.cv-quote{border-left:3px solid var(--cv-accent);padding:3px 8px;margin-bottom:4px;background:rgba(51,144,236,.1);
			border-radius:4px 8px 8px 4px;font-size:12px;}
		.cv-quote[data-target]{cursor:pointer;}
		.cv-quote-author{font-weight:600;color:var(--cv-accent);}
		.cv-quote-text{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
		.cv-bubble-failed{box-shadow:0 0 0 1px var(--red-500,#e24c4c);}
		.cv-fail{clear:both;margin-top:6px;font-size:12px;color:var(--red-600,#c0392b);background:rgba(226,76,76,.08);
			border-radius:6px;padding:4px 8px;white-space:pre-wrap;}
		.cv-resend{display:inline-block;margin-left:6px;cursor:pointer;font-weight:600;white-space:nowrap;}
		.cv-resend:hover{text-decoration:underline;}
		.cv-reactions{position:absolute;bottom:-12px;right:8px;display:flex;gap:2px;}
		.cv-bubble:has(.cv-reactions){margin-bottom:14px;}
		.cv-react-badge{cursor:pointer;background:var(--card-bg);border-radius:10px;padding:0 5px;font-size:12px;line-height:18px;
			box-shadow:0 1px 3px rgba(0,0,0,.2);}
		.cv-react-badge.cv-mine{box-shadow:0 0 0 1px var(--cv-accent),0 1px 3px rgba(0,0,0,.2);}
		.cv-react-count{margin-left:2px;font-size:11px;color:var(--text-muted);}
		.cv-bubble-actions{position:absolute;top:50%;transform:translateY(-50%);display:none;gap:4px;}
		.cv-in .cv-bubble-actions{left:100%;padding-left:6px;}
		.cv-out .cv-bubble-actions{right:100%;padding-right:6px;}
		.cv-bubble:hover .cv-bubble-actions,.cv-bubble.cv-menu-open .cv-bubble-actions{display:flex;}
		.cv-act{cursor:pointer;background:var(--card-bg);border-radius:50%;width:28px;height:28px;line-height:28px;text-align:center;
			font-size:13px;color:var(--text-muted);box-shadow:0 1px 3px rgba(0,0,0,.2);}
		.cv-act:hover,.cv-act:focus{color:var(--cv-accent);outline:none;}
		.cv-bubble.cv-highlight{animation:cv-flash 1.6s ease-out;}
		@keyframes cv-flash{0%,40%{box-shadow:0 0 0 3px var(--cv-accent);}100%{}}
		/* cards */
		.cv-card,.cv-ref-banner{display:flex;gap:8px;align-items:center;text-decoration:none !important;color:inherit !important;
			padding:6px 8px;border:1px solid var(--border-color);border-radius:10px;background:rgba(0,0,0,.03);max-width:300px;}
		.cv-card:hover{background:rgba(0,0,0,.06);}
		.cv-ref-banner{position:sticky;top:0;z-index:6;max-width:none;align-self:stretch;margin-bottom:8px;background:var(--card-bg);
			cursor:pointer;box-shadow:0 1px 4px rgba(0,0,0,.08);}
		.cv-card-removed{opacity:.6;cursor:default;pointer-events:none;}
		.cv-card-icon{flex:none;width:34px;height:34px;border-radius:8px;background:var(--bg-light-gray);display:flex;
			align-items:center;justify-content:center;font-size:17px;overflow:hidden;color:var(--text-muted);}
		.cv-card-icon img{width:100%;height:100%;object-fit:cover;}
		.cv-card-main{min-width:0;}
		.cv-card-title{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
		.cv-card-sub{color:var(--text-muted);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
		/* popovers */
		.cv-pop{position:absolute;z-index:1050;background:var(--card-bg);box-shadow:0 4px 16px rgba(0,0,0,.2);}
		.cv-react-pop{border-radius:20px;padding:4px 8px;display:flex;gap:6px;}
		.cv-react-pop span{cursor:pointer;font-size:20px;transition:transform .1s;}
		.cv-react-pop span:hover{transform:scale(1.3);}
		.cv-emoji-pop{border-radius:12px;padding:8px;display:grid;grid-template-columns:repeat(6,1fr);gap:2px;}
		.cv-emoji-pop span{cursor:pointer;font-size:20px;padding:4px;text-align:center;border-radius:6px;}
		.cv-emoji-pop span:hover{background:var(--bg-light-gray);}
		.cv-menu{border-radius:10px;padding:4px 0;min-width:180px;font-size:13px;}
		.cv-menu-item{padding:7px 14px;cursor:pointer;display:flex;align-items:center;gap:10px;white-space:nowrap;color:var(--text-color);}
		.cv-menu-item:hover{background:var(--bg-light-gray);}
		.cv-menu-item .fa{width:14px;text-align:center;color:var(--text-muted);}
		/* deep archive card */
		.cv-deep-card{margin:auto;max-width:360px;text-align:center;padding:24px 20px;background:var(--card-bg);
			border:1px solid var(--border-color);border-radius:12px;}
		.cv-deep-icon{font-size:28px;color:var(--text-muted);margin-bottom:8px;}
		.cv-deep-title{font-weight:600;margin-bottom:4px;}
		.cv-deep-body{margin-top:14px;}
		.cv-progress{height:6px;border-radius:3px;background:var(--bg-light-gray);overflow:hidden;}
		.cv-progress-bar{height:100%;background:var(--cv-accent);width:0;transition:width .3s ease;}
		.cv-progress-label{margin-top:6px;font-size:var(--text-sm);color:var(--text-muted);}
		/* compact (chat bubble widget) */
		.cv-compact .cv-bubble{max-width:84%;font-size:12.5px;padding:4px 8px 4px 9px;border-radius:12px;}
		.cv-compact .cv-meta{font-size:10px;margin-top:4px;}
		.cv-compact .cv-author{font-size:11px;}
		.cv-compact .cv-media .chat-img,.cv-compact .cv-media .chat-img img,.cv-compact .cv-media video{max-width:190px;}
		.cv-compact .cv-media audio{width:200px;}
		.cv-compact .cv-doc-icon{width:30px;height:30px;font-size:13px;}
		.cv-compact .cv-card{max-width:230px;}
		.cv-compact .cv-day{font-size:11px;margin:6px 0 4px;}
		`;
		$(`<style id="cv-styles-v1">${css}</style>`).appendTo(document.head);
	};
})(erpnext.chat_render);
