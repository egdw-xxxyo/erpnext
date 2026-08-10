// Floating chat bubble shown on every desk page (bottom right).
// One launcher per category: WhatsApp (customer threads) and Employee Chat (internal,
// itself split into Employees / Entities tabs).
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
	return (frappe.boot?.user?.can_read || []).includes("Chat Thread") && cb_page_allowed("employee-chat");
};

function cb_media_label(content_type) {
	return {
		image: "📷 " + __("Photo"),
		video: "🎬 " + __("Video"),
		audio: "🎤 " + __("Audio"),
		document: "📎 " + __("Document"),
		file: "📎 " + __("File"),
		sticker: "🩷 " + __("Sticker"),
		link: "🔗 " + __("Link"),
	}[content_type];
}

// Compact link card for a shared ERPNext object (mirrors the full chat page).
function cb_link_card(card) {
	if (!card || !card.url) return `<i>(${__("link")})</i>`;
	const icon = card.image
		? `<img src="${frappe.utils.escape_html(
				card.image
		  )}" style="width:100%;height:100%;object-fit:cover;">`
		: { document: "📄", report: "📊", list: "🗂️" }[card.kind] || "🔗";
	const title = frappe.utils.escape_html(card.title || card.url);
	const sub = frappe.utils.escape_html(card.subtitle || card.doctype || "");
	const removed = !!card.removed;
	const badge = removed
		? ` <span style="display:inline-block;margin-left:4px;padding:0 5px;border-radius:8px;background:var(--red-500,#e24c4c);color:#fff;font-size:9px;font-weight:600;line-height:15px;">${frappe.utils.escape_html(
				__("Removed")
		  )}</span>`
		: "";
	// A deleted target has nowhere to go: drop the href so the card is inert but still legible.
	const attrs = removed
		? ""
		: ` href="${frappe.utils.escape_html(card.url)}" target="_blank" rel="noopener"`;
	return `<a class="cb-link-card"${attrs} style="display:flex;gap:6px;align-items:center;text-decoration:none;color:inherit;padding:5px 7px;border:1px solid var(--border-color);border-radius:7px;background:rgba(0,0,0,.03);max-width:240px;${
		removed ? "opacity:.6;pointer-events:none;" : ""
	}">
		<div style="flex:none;width:30px;height:30px;border-radius:5px;background:var(--bg-light-gray);display:flex;align-items:center;justify-content:center;font-size:16px;overflow:hidden;">${icon}</div>
		<div style="min-width:0;">
			<div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${title}${badge}</div>
			${
				sub
					? `<div style="color:var(--text-muted);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${sub}</div>`
					: ""
			}
		</div>
	</a>`;
}

// Pinned card atop a Document thread in the bubble: the record the chat is about.
// Clickable (routes to the form) unless the record was deleted.
function cb_reference_banner(chat) {
	const dt = chat.reference_doctype;
	const name = chat.reference_name;
	const removed = !!chat.reference_removed;
	const title = frappe.utils.escape_html(chat.reference_label || name || __("Document"));
	const sub = frappe.utils.escape_html(dt ? `${__(dt)} · ${name}` : "");
	const badge = removed
		? ` <span style="display:inline-block;margin-left:4px;padding:0 5px;border-radius:8px;background:var(--red-500,#e24c4c);color:#fff;font-size:9px;font-weight:600;line-height:15px;">${frappe.utils.escape_html(
				__("Removed")
		  )}</span>`
		: "";
	const arch =
		chat.is_archived && !removed
			? ` <span style="display:inline-block;margin-left:4px;padding:0 5px;border-radius:8px;background:var(--gray-500,#8d99a6);color:#fff;font-size:9px;font-weight:600;line-height:15px;">${frappe.utils.escape_html(
					__("Archived")
			  )}</span>`
			: "";
	const data = removed
		? ""
		: ` data-dt="${frappe.utils.escape_html(dt)}" data-name="${frappe.utils.escape_html(name)}"`;
	return `<div class="cb-ref-banner"${data} style="display:flex;gap:6px;align-items:center;padding:7px 9px;margin-bottom:6px;border:1px solid var(--border-color);border-radius:7px;background:var(--card-bg);${
		removed ? "opacity:.6;" : "cursor:pointer;"
	}">
		<div style="flex:none;font-size:16px;">📄</div>
		<div style="min-width:0;">
			<div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${title}${badge}${arch}</div>
			${
				sub
					? `<div style="color:var(--text-muted);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${sub}</div>`
					: ""
			}
		</div>
	</div>`;
}

function cb_fmt_time(dt) {
	if (!dt) return "";
	const tz = frappe.sys_defaults.time_zone || "UTC";
	return moment.tz(dt, tz).local().format("DD.MM HH:mm");
}

// Body of a bubble message: inline image (with lazy preview + lightbox via chat_media),
// a download link for other files, or plain/labelled text. `m` is the normalized message
// object built by the sources' load_messages.
function cb_render_body(m) {
	if (m.is_encrypted) {
		if (!m.dec) return `🔒 ${__("Encrypted")}`;
		if (m.dec.link) return cb_link_card(m.dec.link);
		const text = m.dec.text || "";
		const cap = text ? `<div class="cb-caption">${frappe.utils.escape_html(text)}</div>` : "";
		const file = m.dec.file;
		if (file && m.content_type === "audio") {
			return `<div class="cb-media">${erpnext.chat_media.encrypted_audio_html({
				url: file.url,
				key: file.key,
				iv: file.iv,
				mime: file.mime,
				file_name: file.name,
			})}</div>${cap}`;
		}
		if (file && m.content_type === "image") {
			return `<div class="cb-media">${erpnext.chat_media.encrypted_image_html({
				url: file.url,
				key: file.key,
				iv: file.iv,
				mime: file.mime,
				file_name: file.name,
				thumb_url: (m.dec.thumb || {}).url,
				thumb_key: (m.dec.thumb || {}).key,
				thumb_iv: (m.dec.thumb || {}).iv,
			})}</div>${cap}`;
		}
		if (file) {
			return `<span class="cb-doc">📎 ${frappe.utils.escape_html(
				file.name || __("File")
			)}</span>${cap}`;
		}
		return text ? `<span>${frappe.utils.escape_html(text)}</span>` : `<i>(${__("no text")})</i>`;
	}

	if (m.content_type === "link" && m.link_data) {
		return cb_link_card(m.link_data);
	}
	const caption = m.text || "";
	const cap = caption ? `<div class="cb-caption">${frappe.utils.escape_html(caption)}</div>` : "";
	if ((m.content_type === "image" || m.content_type === "sticker") && m.attach) {
		return `<div class="cb-media">${erpnext.chat_media.image_html(m.attach)}</div>${cap}`;
	}
	if (m.content_type === "audio" && m.attach) {
		return `<div class="cb-media">${erpnext.chat_media.audio_html(m.attach)}</div>${cap}`;
	}
	if (m.attach) {
		const url = frappe.utils.escape_html(m.attach);
		const fname = frappe.utils.escape_html(decodeURIComponent(m.attach.split("/").pop() || __("File")));
		return `<a class="cb-doc" href="${url}" target="_blank" download>📎 ${fname}</a>${cap}`;
	}
	const label = cb_media_label(m.content_type);
	if (label) return caption ? `${label}${cap}` : label;
	return caption ? `<span>${frappe.utils.escape_html(caption)}</span>` : `<i>(${__("no text")})</i>`;
}

// --- WhatsApp source -------------------------------------------------------

class WhatsAppSource {
	constructor() {
		this.key = "whatsapp";
		this.label = __("WhatsApp");
		this.page_route = "/app/whatsapp-chat-center";
		this.realtime_events = ["whatsapp_message", "whatsapp_read"];
		this.media_source = "whatsapp"; // get_thumbnails source key
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
			time: m.creation,
			author: null,
			content_type: m.content_type,
			attach: m.attach,
			text: (m.message || "").replace(/<[^>]*>/g, ""),
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

	// Pick a file, upload it, and send it as a media message — same content-type
	// detection the full Chat Center uses.
	attach(id, caption) {
		return new Promise((resolve, reject) => {
			new frappe.ui.FileUploader({
				folder: "Home/Attachments",
				on_success: async (file) => {
					let ct = erpnext.chat_media.detect_type(
						file.file_type || file.type,
						file.file_name || file.file_url
					);
					if (!["image", "video", "audio"].includes(ct)) ct = "document";
					try {
						await frappe.xcall(`${WA_API}.send_media`, {
							phone: id,
							attach: file.file_url,
							content_type: ct,
							caption: caption || null,
						});
						resolve();
					} catch (e) {
						reject(e);
					}
				},
			});
		});
	}

	// Send an already-recorded voice note (blob). The server transcodes webm to
	// ogg/opus so Meta accepts Chrome recordings.
	async send_voice(id, rec) {
		const url = await erpnext.chat_media.upload_audio(rec.blob, rec.ext);
		await frappe.xcall(`${WA_API}.send_media`, {
			phone: id,
			attach: url,
			content_type: "audio",
			caption: null,
		});
	}

	route_for(id) {
		return id ? `${this.page_route}?phone=${encodeURIComponent(id)}` : this.page_route;
	}
}

// --- Employee Chat source --------------------------------------------------

class EmployeeChatSource {
	constructor() {
		this.key = "employee";
		this.label = __("Employee Chat");
		this.page_route = "/app/employee-chat";
		this.realtime_events = ["chat_message", "chat_seen", "chat_thread_archived", "chat_thread_purged"];
		this.media_source = "chat"; // get_thumbnails source key
		this.chats = [];
		// Two lists behind one launcher: person-to-person threads first, threads
		// attached to a record (Document threads) second.
		this.tabs = [
			{ key: "employee", label: __("Employees") },
			{ key: "entity", label: __("Entities") },
		];
	}

	// A thread belongs to the entity tab when it is about a record.
	static is_entity(chat) {
		return !!chat.reference_doctype;
	}

	chats_for_tab(tab) {
		return (this.chats || []).filter((c) =>
			tab === "entity" ? EmployeeChatSource.is_entity(c) : !EmployeeChatSource.is_entity(c)
		);
	}

	tab_of(id) {
		const chat = (this.chats || []).find((c) => c.id === id);
		return chat && EmployeeChatSource.is_entity(chat) ? "entity" : "employee";
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
			reference_doctype: t.reference_doctype,
			reference_name: t.reference_name,
			reference_label: t.reference_label,
			reference_removed: t.reference_removed,
			is_archived: t.is_archived,
			read_only: t.read_only,
			can_purge: t.can_purge,
		}));
		return this.chats;
	}

	set_archived(id, archived) {
		return frappe.xcall(`${EC_API}.set_archived`, { thread: id, archived: archived ? 1 : 0 });
	}

	purge(id) {
		return frappe.xcall(`${EC_API}.purge_thread`, { thread: id });
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
			const item = {
				out: m.sender === me,
				time: m.creation,
				author: m.sender === me ? null : m.sender_name,
				content_type: m.content_type,
			};
			if (m.is_encrypted) {
				item.is_encrypted = true;
				item.dec = null; // stays locked unless the key is already in memory
				if (unlocked) {
					try {
						item.dec = await erpnext.chat_crypto.decrypt(id, m.message, m.enc_iv);
					} catch (e) {
						// leave the lock
					}
				}
			} else {
				item.attach = m.attach;
				item.text = m.message || "";
				item.link_data = m.link_data;
			}
			out.push(item);
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
		// Autoparse a lone desk URL into a link card (same as the full chat page).
		let card = null;
		if (/^https?:\/\/\S+$/.test((text || "").trim())) {
			try {
				const c = await frappe.xcall(`${EC_API}.resolve_link`, { url: text.trim() });
				if (c && c.kind && c.kind !== "external") card = c;
			} catch (e) {
				// fall back to plain text
			}
		}

		if (!this.is_secret(id)) {
			if (card) {
				return frappe.xcall(`${EC_API}.send_message`, {
					thread: id,
					content_type: "link",
					link_data: JSON.stringify(card),
				});
			}
			return frappe.xcall(`${EC_API}.send_message`, { thread: id, message: text });
		}
		if (!(await erpnext.chat_crypto.ensure_unlocked())) return;
		const payload = card ? { link: card } : { text };
		const { ciphertext, iv } = await erpnext.chat_crypto.encrypt(id, payload);
		return frappe.xcall(`${EC_API}.send_message`, {
			thread: id,
			content_type: card ? "link" : "text",
			message: ciphertext,
			is_encrypted: 1,
			enc_iv: iv,
		});
	}

	attach(id, caption) {
		if (this.is_secret(id)) return this.attach_secret(id, caption);
		return new Promise((resolve, reject) => {
			new frappe.ui.FileUploader({
				folder: "Home/Attachments",
				on_success: async (file) => {
					const content_type =
						erpnext.chat_media.detect_type(
							file.file_type || file.type,
							file.file_name || file.file_url
						) === "image"
							? "image"
							: "file";
					try {
						await frappe.xcall(`${EC_API}.send_message`, {
							thread: id,
							content_type,
							attach: file.file_url,
							message: caption || "",
						});
						resolve();
					} catch (e) {
						reject(e);
					}
				},
			});
		});
	}

	// Secret attachments are encrypted in the browser and uploaded as opaque blobs,
	// together with a browser-built preview — mirrors the full chat page.
	async attach_secret(id, caption) {
		if (!(await erpnext.chat_crypto.ensure_unlocked())) return;
		const file = await new Promise((resolve) => {
			const input = $('<input type="file" style="display:none">').appendTo(document.body);
			input.on("change", () => {
				const f = input[0].files && input[0].files[0];
				input.remove();
				resolve(f || null);
			});
			input.trigger("click");
		});
		if (!file) return;

		const content_type =
			erpnext.chat_media.detect_type(file.type, file.name) === "image" ? "image" : "file";
		frappe.dom.freeze(__("Encrypting…"));
		try {
			const enc = await erpnext.chat_crypto.encrypt_blob(file);
			const url = await erpnext.chat_media.upload_encrypted(enc.blob, file.name);
			const payload = {
				text: caption || "",
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
					url: await erpnext.chat_media.upload_encrypted(enc_thumb.blob, "preview-" + file.name),
					key: enc_thumb.key,
					iv: enc_thumb.iv,
				};
			}

			const { ciphertext, iv } = await erpnext.chat_crypto.encrypt(id, payload);
			await frappe.xcall(`${EC_API}.send_message`, {
				thread: id,
				content_type,
				attach: url,
				// The encrypted preview's URL lives inside the ciphertext, so name it here too —
				// otherwise the server can never link (or purge) that blob.
				extra_files: payload.thumb ? JSON.stringify([payload.thumb.url]) : null,
				message: ciphertext,
				is_encrypted: 1,
				enc_iv: iv,
			});
		} finally {
			frappe.dom.unfreeze();
		}
	}

	async send_voice(id, rec) {
		if (this.is_secret(id)) {
			if (!(await erpnext.chat_crypto.ensure_unlocked())) return;
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
			const { ciphertext, iv } = await erpnext.chat_crypto.encrypt(id, payload);
			await frappe.xcall(`${EC_API}.send_message`, {
				thread: id,
				content_type: "audio",
				attach: url,
				message: ciphertext,
				is_encrypted: 1,
				enc_iv: iv,
			});
			return;
		}
		const url = await erpnext.chat_media.upload_audio(rec.blob, rec.ext);
		await frappe.xcall(`${EC_API}.send_message`, {
			thread: id,
			content_type: "audio",
			attach: url,
			message: "",
		});
	}

	route_for(id) {
		return id ? `${this.page_route}?thread=${encodeURIComponent(id)}` : this.page_route;
	}
}

// --- Bubble widget ---------------------------------------------------------

// Launcher buttons, left→right. `document` is virtual: it drives the employee
// source into the single Document thread of whatever form is open (see
// open_document_chat), and only shows while a saved form is on screen.
const CB_LAUNCH = {
	whatsapp: { icon: "fa fa-whatsapp", color: "#25d366", title: __("WhatsApp") },
	employee: { icon: "fa fa-users", color: "#2490ef", title: __("Employee Chat") },
	document: { icon: "fa fa-file-text-o", color: "#6c7680", title: __("Chat about this document") },
};

class ChatBubble {
	constructor(sources) {
		this.sources = sources;
		this.source = sources[0];
		this.active = null; // open conversation id
		this.tab = "employee"; // active tab of a tabbed source (employee chat)
		this.arch_open = localStorage.getItem("cb_arch_open") === "1";
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
		this.sources.forEach((s) => s.realtime_events.forEach((ev) => frappe.realtime.on(ev, this.on_rt)));
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
			console.log("[chat] ring: whatsapp incoming", {
				number: d.number,
				chat_found: !!chat,
				muted: chat && chat.muted,
			});
		} else if (d.sender && d.sender !== frappe.session.user && d.thread) {
			// Employee Chat: a full message payload
			chat = (this.sources.find((s) => s.key === "employee")?.chats || []).find(
				(c) => c.id === d.thread
			);
			console.log("[chat] ring: employee message", {
				thread: d.thread,
				sender: d.sender,
				chat_found: !!chat,
				muted: chat && chat.muted,
			});
		} else {
			console.log("[chat] ring: event ignored (not an incoming/foreign message)", d);
			return;
		}
		erpnext.chat_sound.play(chat && chat.muted);
	}

	render_sound_toggle() {
		const on = erpnext.chat_sound.enabled();
		this.$sound
			.text(on ? "🔊" : "🔇")
			.attr("title", on ? __("Notification sound is on") : __("Notification sound is off"));
	}

	// The per-conversation mute is only meaningful with a thread open.
	render_mute_toggle() {
		const chat = this.active ? (this.source.chats || []).find((c) => c.id === this.active) : null;
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

	// Archive / remove, shown only for a source that supports them and only in a thread.
	// Removing is destructive and role-gated (server: Chat Manager), so the button appears
	// only where the server would actually allow it: on an archived thread.
	render_thread_actions() {
		const chat = this.active ? (this.source.chats || []).find((c) => c.id === this.active) : null;
		if (!chat || !this.source.set_archived) {
			this.$archive.hide();
			this.$purge.hide();
			return;
		}
		this.$archive
			.show()
			.attr("title", chat.is_archived ? __("Unarchive chat") : __("Archive chat"))
			.html(`<i class="fa fa-${chat.is_archived ? "inbox" : "archive"}"></i>`);
		this.$purge.toggle(!!(chat.is_archived && chat.can_purge));
	}

	async toggle_archive() {
		const chat = (this.source.chats || []).find((c) => c.id === this.active);
		if (!chat || !this.source.set_archived) return;
		const archived = chat.is_archived ? 0 : 1;
		try {
			const res = await this.source.set_archived(this.active, archived);
			chat.is_archived = res.is_archived;
			chat.read_only = res.read_only;
		} catch (e) {
			return;
		}
		this.render_thread_actions();
		this.render_composer(chat);
		this.refresh();
	}

	async purge_thread() {
		const chat = (this.source.chats || []).find((c) => c.id === this.active);
		if (!chat || !this.source.purge) return;
		const id = this.active;
		frappe.confirm(
			__("Delete this chat with all its messages and files? This cannot be undone."),
			async () => {
				try {
					await this.source.purge(id);
				} catch (e) {
					return;
				}
				this.source.chats = (this.source.chats || []).filter((c) => c.id !== id);
				this.show_list();
				this.refresh();
			}
		);
	}

	// An archived chat about a record is read-only server-side — hide the composer instead of
	// letting the user type into a message that will be rejected.
	render_composer(chat) {
		if (chat && chat.read_only) {
			this.$compose.hide();
			this.$readonly.show();
		} else {
			this.$readonly.hide();
			this.$compose.show();
		}
	}

	inject_styles() {
		erpnext.chat_media.inject_styles();
		if (document.getElementById("cb-bubble-styles")) return;
		const css = `
		.cb-launcher{position:fixed;right:24px;bottom:24px;z-index:1035;display:flex;gap:10px;align-items:center;}
		.cb-fab{position:relative;width:52px;height:52px;border-radius:50%;color:#fff;border:none;
			box-shadow:0 4px 14px rgba(0,0,0,.28);font-size:24px;line-height:52px;text-align:center;cursor:pointer;
			transition:transform .15s ease;}
		.cb-fab:hover{transform:scale(1.08);}
		.cb-fab.cb-active{outline:3px solid rgba(255,255,255,.65);outline-offset:1px;}
		.cb-badge{position:absolute;top:-4px;right:-4px;min-width:20px;height:20px;padding:0 5px;border-radius:10px;
			background:var(--red-500,#e24c4c);color:#fff;font-size:11px;line-height:20px;font-weight:600;text-align:center;display:none;
			border:2px solid var(--card-bg);}
		.cb-panel{position:fixed;right:24px;bottom:92px;z-index:1035;width:360px;height:480px;display:none;
			flex-direction:column;background:var(--card-bg);border:1px solid var(--border-color);
			border-radius:var(--border-radius-md);box-shadow:0 8px 28px rgba(0,0,0,.25);overflow:hidden;}
		.cb-panel.open{display:flex;}
		.cb-head{display:flex;align-items:center;gap:6px;padding:8px 10px;border-bottom:1px solid var(--border-color);
			background:#075e54;color:#fff;}
		.cb-title{flex:1;font-weight:600;font-size:var(--text-md);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
		.cb-head .cb-act{cursor:pointer;opacity:.85;font-size:15px;line-height:1;padding:2px 4px;}
		.cb-head .cb-act:hover{opacity:1;}
		.cb-tabs{display:none;border-bottom:1px solid var(--border-color);background:var(--card-bg);}
		.cb-panel .cb-tabs.show{display:flex;}
		.cb-tab{flex:1;display:flex;align-items:center;justify-content:center;gap:5px;padding:7px 8px;cursor:pointer;
			font-size:var(--text-sm);font-weight:600;color:var(--text-muted);border-bottom:2px solid transparent;}
		.cb-tab:hover{background:var(--bg-light-gray);}
		.cb-tab.active{color:var(--text-color);border-bottom-color:var(--primary,#2490ef);}
		.cb-count{min-width:17px;height:17px;padding:0 5px;border-radius:9px;background:var(--red-500,#e24c4c);
			color:#fff;font-size:10px;line-height:17px;font-weight:600;text-align:center;display:none;}
		.cb-count.show{display:inline-block;}
		.cb-body{flex:1;overflow-y:auto;}
		.cb-conv{padding:9px 12px;border-bottom:1px solid var(--border-color);cursor:pointer;}
		.cb-conv:hover{background:var(--bg-light-gray);}
		.cb-conv .cb-name{font-weight:600;font-size:var(--text-sm);display:flex;justify-content:space-between;gap:6px;}
		.cb-conv .cb-time{font-weight:400;color:var(--text-muted);font-size:10px;white-space:nowrap;
			display:flex;align-items:center;gap:5px;flex:none;}
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
		.cb-msg .cb-media{margin-bottom:2px;}
		.cb-msg .chat-img{min-width:70px;min-height:54px;max-width:180px;}
		.cb-msg .chat-img img{max-width:180px;max-height:200px;}
		.cb-msg .cb-caption{white-space:pre-wrap;margin-top:2px;}
		.cb-msg .cb-doc{color:inherit;text-decoration:underline;word-break:break-all;display:inline-block;}
		.cb-arch-head{display:flex;align-items:center;gap:6px;padding:7px 12px;cursor:pointer;
			background:var(--bg-light-gray);border-top:1px solid var(--border-color);
			border-bottom:1px solid var(--border-color);font-size:var(--text-sm);font-weight:600;
			color:var(--text-muted);}
		.cb-arch-head:hover{color:var(--text-color);}
		.cb-arch-head .cb-count{margin-left:auto;}
		.cb-readonly{padding:8px;border-top:1px solid var(--border-color);text-align:center;
			color:var(--text-muted);font-size:var(--text-sm);}
		.cb-compose{display:flex;gap:6px;padding:8px;border-top:1px solid var(--border-color);align-items:flex-end;}
		.cb-compose textarea{resize:none;flex:1;font-size:12px;}
		.cb-compose .cb-attach{flex:none;}
		.cb-foot{padding:6px 8px;border-top:1px solid var(--border-color);}
		@media (max-width:600px){
			.cb-panel{right:12px;left:12px;width:auto;bottom:84px;height:70vh;}
			.cb-launcher{right:12px;bottom:16px;gap:8px;}
			.cb-fab{width:48px;height:48px;font-size:22px;line-height:48px;}
		}
		`;
		$(`<style id="cb-bubble-styles">${css}</style>`).appendTo(document.head);
	}

	make_dom() {
		// One round launcher per category, right→left: document (nearest = whatsapp).
		const keys = this.sources.map((s) => s.key);
		this.has_employee = keys.includes("employee");
		const btns = ["document", "employee", "whatsapp"]
			.filter((k) => (k === "document" ? this.has_employee : keys.includes(k)))
			.map((k) => {
				const m = CB_LAUNCH[k];
				// The document button rides the employee source but starts hidden;
				// update_document_button reveals it only on a saved form.
				const hide = k === "document" ? "display:none;" : "";
				return `<button class="cb-fab cb-fab-${k}" data-key="${k}" title="${frappe.utils.escape_html(
					m.title
				)}" style="background:${m.color};${hide}">
					<i class="${m.icon}"></i><span class="cb-badge"></span>
				</button>`;
			})
			.join("");
		this.$launcher = $(`<div class="cb-launcher">${btns}</div>`).appendTo(document.body);
		this.$fab = this.$launcher; // legacy alias used by toggle_bubble_visibility

		this.$panel = $(`
			<div class="cb-panel">
				<div class="cb-head">
					<span class="cb-act cb-back" title="${__("Back")}" style="display:none;">←</span>
					<span class="cb-title">${__("Chat")}</span>
					<span class="cb-act cb-mute" title="${__("Mute chat")}" style="display:none;"></span>
					<span class="cb-act cb-archive" style="display:none;"></span>
					<span class="cb-act cb-purge" title="${__(
						"Remove chat"
					)}" style="display:none;"><i class="fa fa-trash-o"></i></span>
					<span class="cb-act cb-sound" title="${__("Notification sound")}"></span>
					<span class="cb-act cb-open-page" title="${__("Open full page")}">⤢</span>
					<span class="cb-act cb-close" title="${__("Close")}">&times;</span>
				</div>
				<div class="cb-tabs"></div>
				<div class="cb-body"></div>
				<div class="cb-readonly" style="display:none;">${__(
					"This chat is archived — new messages are not allowed"
				)}</div>
				<div class="cb-compose" style="display:none;">
					<button class="btn btn-default btn-xs cb-attach" title="${__("Attach file")}">📎</button>
					<button class="btn btn-default btn-xs cb-mic" title="${__("Record voice message")}">🎤</button>
					<textarea class="form-control" rows="1" placeholder="${__("Type a message")}"></textarea>
					<button class="btn btn-primary btn-xs cb-send">${__("Send")}</button>
				</div>
				<div class="cb-foot">
					<button class="btn btn-default btn-xs cb-goto" style="width:100%;">${__("Open full page")}</button>
				</div>
			</div>
		`).appendTo(document.body);

		this.$body = this.$panel.find(".cb-body");
		this.$tabs = this.$panel.find(".cb-tabs");
		this.$title = this.$panel.find(".cb-title");
		this.$back = this.$panel.find(".cb-back");
		this.$mute = this.$panel.find(".cb-mute");
		this.$archive = this.$panel.find(".cb-archive");
		this.$purge = this.$panel.find(".cb-purge");
		this.$sound = this.$panel.find(".cb-sound");
		this.render_sound_toggle();
		this.$compose = this.$panel.find(".cb-compose");
		this.$readonly = this.$panel.find(".cb-readonly");
		this.$input = this.$compose.find("textarea");
		this.update_document_button();
	}

	// The launcher key currently driving the open panel ("whatsapp"/"employee"/"document").
	set_active_fab(key) {
		this.active_key = key;
		this.$launcher.find(".cb-fab").removeClass("cb-active");
		if (key) this.$launcher.find(`.cb-fab[data-key="${key}"]`).addClass("cb-active");
	}

	// {doctype, name} of the saved form on screen, else null.
	doc_ref() {
		const frm = window.cur_frm;
		if (!frm || !frm.doc || frm.is_new() || !frm.doc.name) return null;
		if ((frappe.get_route() || [])[0] !== "Form") return null;
		return { doctype: frm.doctype, name: frm.docname };
	}

	// Employee-chat thread already opened for the current form, if any.
	doc_thread() {
		const ref = this.doc_ref();
		if (!ref) return null;
		const emp = this.sources.find((s) => s.key === "employee");
		return (emp?.chats || []).find(
			(c) => c.reference_doctype === ref.doctype && c.reference_name === ref.name
		);
	}

	// Reveal the document launcher button only while a saved form is open.
	update_document_button() {
		const $btn = this.$launcher.find(`.cb-fab[data-key="document"]`);
		if (!$btn.length) return;
		$btn.toggle(!!this.doc_ref());
	}

	bind_events() {
		this.$launcher.on("click", ".cb-fab", (e) => {
			const key = $(e.currentTarget).attr("data-key");
			if (key === "document") this.open_document_chat();
			else this.open_source(key);
		});
		this.$panel.find(".cb-close").on("click", () => this.toggle(false));
		this.$back.on("click", () => this.show_list());
		this.$panel.find(".cb-goto, .cb-open-page").on("click", () => this.goto_page());
		this.$sound.on("click", () => {
			erpnext.chat_sound.set_enabled(!erpnext.chat_sound.enabled());
			this.render_sound_toggle();
		});
		this.$mute.on("click", () => this.toggle_mute());
		this.$archive.on("click", () => this.toggle_archive());
		this.$purge.on("click", () => this.purge_thread());
		this.$body.on("click", ".cb-arch-head", () => {
			this.arch_open = !this.arch_open;
			localStorage.setItem("cb_arch_open", this.arch_open ? "1" : "0");
			this.render_list();
		});
		this.$panel.find(".cb-send").on("click", () => this.send());
		this.$panel.find(".cb-attach").on("click", () => this.attach_media());
		this.$panel.find(".cb-mic").on("click", () => this.record_voice());
		this.$input.on("keydown", (e) => {
			if (e.key === "Enter" && !e.shiftKey) {
				e.preventDefault();
				this.send();
			}
		});
		this.$tabs.on("click", ".cb-tab", (e) => {
			const tab = $(e.currentTarget).attr("data-tab");
			if (tab === this.tab) return;
			this.tab = tab;
			this.show_list();
		});
		this.$body.on("click", ".cb-conv", (e) => {
			this.open_thread($(e.currentTarget).attr("data-id"));
		});
	}

	// Click a category button: open its conversation list. Clicking the same
	// button again (while showing its list) closes the panel.
	open_source(key) {
		const src = this.sources.find((s) => s.key === key);
		if (!src) return;
		if (this.open && this.source === src && this.active_key === key && !this.active) {
			this.toggle(false);
			return;
		}
		this.source = src;
		this.active = null;
		// Pressing the launcher always lands on the first tab (employee threads).
		this.tab = "employee";
		this.set_active_fab(key);
		this.open = true;
		this.$panel.addClass("open");
		this.show_list();
		this.refresh();
	}

	// Open (creating on first use) the single Document thread for the current form,
	// inside the employee source. Its unread badge lives on the document button.
	async open_document_chat() {
		const ref = this.doc_ref();
		const emp = this.sources.find((s) => s.key === "employee");
		if (!ref || !emp) return;
		this.source = emp;
		this.active = null;
		this.set_active_fab("document");
		this.open = true;
		this.$panel.addClass("open");
		this.$title.text(__("Chat about this document"));
		this.$tabs.removeClass("show").empty();
		this.$back.hide();
		this.$mute.hide();
		this.$archive.hide();
		this.$purge.hide();
		this.$readonly.hide();
		this.$compose.hide();
		this.$body.html(`<div class="cb-empty">${__("Loading")}...</div>`);
		let name;
		try {
			const res = await frappe.xcall(`${EC_API}.open_document_thread`, {
				reference_doctype: ref.doctype,
				reference_name: ref.name,
			});
			name = res.name;
		} catch (e) {
			this.$body.html(`<div class="cb-empty">${__("Failed to open chat")}</div>`);
			return;
		}
		await emp.load_list();
		this.render_badges();
		this.open_thread(name);
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
		} else {
			this.set_active_fab(null);
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
		// The open thread can disappear under us — someone with the Chat Manager role purged it.
		if (this.active && !(this.source.chats || []).some((c) => c.id === this.active)) {
			this.show_list();
			return;
		}
		if (this.active) {
			const chat = (this.source.chats || []).find((c) => c.id === this.active);
			this.render_thread_actions();
			this.render_composer(chat);
			this.load_thread(this.active);
		} else {
			this.render_list();
		}
	}

	render_badges() {
		const set = (key, count) => {
			this.$launcher
				.find(`.cb-fab[data-key="${key}"] .cb-badge`)
				.text(count > 99 ? "99+" : count)
				.toggle(count > 0);
		};
		// Each category button carries only its own unread — WhatsApp stays visible
		// even while the employee chat is ignored, and vice versa.
		this.sources.forEach((s) => {
			// Sum unread *messages* across conversations (each c.unread is already a message
			// count, secret threads included — the server counts rows, never plaintext), not
			// the number of conversations that have something unread.
			const count = (s.chats || []).reduce((n, c) => n + (c.unread || 0), 0);
			set(s.key, count);
		});
		// Document button reflects just the current form's thread.
		if (this.has_employee) {
			const dt = this.doc_thread();
			set("document", dt ? dt.unread || 0 : 0);
		}
		this.render_tab_counts();
	}

	show_list() {
		this.active = null;
		if (this.$mute) this.$mute.hide();
		if (this.$archive) this.$archive.hide();
		if (this.$purge) this.$purge.hide();
		this.$back.hide();
		this.$readonly.hide();
		this.$compose.hide();
		this.$title.text(this.source.label);
		this.render_tabs();
		this.render_list();
	}

	// Tab strip, only for sources that declare tabs and only on the list view.
	render_tabs() {
		const tabs = this.source.tabs;
		if (!tabs || this.active) {
			this.$tabs.removeClass("show").empty();
			return;
		}
		this.$tabs.addClass("show").html(
			tabs
				.map(
					(t) => `<div class="cb-tab ${t.key === this.tab ? "active" : ""}" data-tab="${t.key}">
					<span>${frappe.utils.escape_html(t.label)}</span><span class="cb-count"></span>
				</div>`
				)
				.join("")
		);
		this.render_tab_counts();
	}

	render_tab_counts() {
		if (!this.source.tabs || !this.$tabs.hasClass("show")) return;
		this.source.tabs.forEach((t) => {
			const count = this.visible_chats(t.key).reduce((n, c) => n + (c.unread || 0), 0);
			this.$tabs
				.find(`.cb-tab[data-tab="${t.key}"] .cb-count`)
				.text(count > 99 ? "99+" : count)
				.toggleClass("show", count > 0);
		});
	}

	// Conversations to list: those of the requested tab, minus the ones that carry no
	// message at all (an entity thread is created on first open, before anything is said).
	visible_chats(tab) {
		const chats = this.source.tabs ? this.source.chats_for_tab(tab || this.tab) : this.source.chats || [];
		return chats.filter((c) => c.time || c.preview || c.unread);
	}

	conv_html(c) {
		const name = frappe.utils.escape_html(c.title);
		const prev = frappe.utils.escape_html((c.preview || "").replace(/<[^>]*>/g, "").slice(0, 80));
		const unread = c.unread
			? `<span class="cb-count show">${c.unread > 99 ? "99+" : c.unread}</span>`
			: "";
		return `<div class="cb-conv ${c.unread ? "unread" : ""}" data-id="${frappe.utils.escape_html(c.id)}">
			<div class="cb-name"><span>${name}</span><span class="cb-time">${unread}${cb_fmt_time(c.time)}</span></div>
			<div class="cb-prev">${prev || __("(no text)")}</div>
		</div>`;
	}

	render_list() {
		const chats = this.visible_chats();
		const active = chats.filter((c) => !c.is_archived);
		const archived = chats.filter((c) => c.is_archived);
		if (!active.length && !archived.length) {
			this.$body.html(`<div class="cb-empty">${__("No conversations yet")}</div>`);
			return;
		}
		let html = active.map((c) => this.conv_html(c)).join("");
		if (archived.length) {
			// Archived chats keep receiving messages, so the collapsed header carries their
			// unread count — otherwise it would look like nothing happened down there.
			const unread = archived.reduce((n, c) => n + (c.unread || 0), 0);
			html += `<div class="cb-arch-head">
				<i class="fa fa-caret-${this.arch_open ? "down" : "right"}"></i>
				<span>${__("Archived")}</span>
				<span class="cb-count ${unread ? "show" : ""}">${unread > 99 ? "99+" : unread}</span>
			</div>`;
			if (this.arch_open) html += archived.map((c) => this.conv_html(c)).join("");
		}
		this.$body.html(html || `<div class="cb-empty">${__("No conversations yet")}</div>`);
	}

	open_thread(id) {
		console.log("[chat] open_thread (conversation clicked)", { source: this.source.key, id });
		this.active = id;
		// Coming back from this thread should land on the tab it belongs to.
		if (this.source.tab_of) this.tab = this.source.tab_of(id);
		this.render_tabs();
		const chat = (this.source.chats || []).find((c) => c.id === id);
		this.$title.text(chat ? chat.title : id);
		this.render_mute_toggle();
		this.render_thread_actions();
		this.$back.show();
		this.render_composer(chat);
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
					<div class="cb-msg-text">${cb_render_body(m)}</div>
					<div class="cb-meta">${cb_fmt_time(m.time)}</div>
				</div>`
			)
			.join("");

		const banner = chat && chat.reference_doctype ? cb_reference_banner(chat) : "";
		this.$body.html(
			`${banner}<div class="cb-thread">${
				bubbles || `<div class="cb-empty">${__("No messages yet")}</div>`
			}</div>`
		);
		this.$body.find(".cb-ref-banner[data-dt]").on("click", (e) => {
			frappe.set_route(
				"Form",
				$(e.currentTarget).attr("data-dt"),
				$(e.currentTarget).attr("data-name")
			);
		});
		// Lazy-load previews + wire the shared lightbox for any images in the thread.
		if (source.media_source) {
			erpnext.chat_media.bind(this.$body.find(".cb-thread"), source.media_source);
		}
		this.$body.scrollTop(this.$body[0].scrollHeight);
	}

	async record_voice() {
		if (!this.active || !this.source.send_voice) return;
		const rec = await erpnext.chat_media.record_audio();
		if (!rec) return;
		frappe.dom.freeze(__("Sending…"));
		try {
			await this.source.send_voice(this.active, rec);
		} catch (e) {
			frappe.msgprint(__("Failed to send voice message"));
			return;
		} finally {
			frappe.dom.unfreeze();
		}
		this.load_thread(this.active);
		this.refresh();
	}

	async attach_media() {
		if (!this.active || !this.source.attach) return;
		const caption = (this.$input.val() || "").trim();
		try {
			await this.source.attach(this.active, caption);
		} catch (e) {
			frappe.msgprint(__("Failed to send file"));
			return;
		}
		this.$input.val("");
		this.load_thread(this.active);
		this.refresh();
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
	// A form finishes loading after the route change; refresh the document button then.
	$(document).on("form-refresh", () => {
		const b = erpnext.whatsapp.bubble;
		if (!b) return;
		b.update_document_button();
		b.render_badges();
	});
};

// Hide the bubble on the full chat pages themselves.
erpnext.whatsapp.toggle_bubble_visibility = function () {
	const b = erpnext.whatsapp.bubble;
	if (!b) return;
	const route = (frappe.get_route() || []).join("/");
	const on_chat_page = route.includes("whatsapp-chat-center") || route.includes("employee-chat");
	b.$launcher.toggle(!on_chat_page);
	if (on_chat_page) b.toggle(false);
	b.update_document_button();
	b.render_badges();
};

$(document).on("app_ready", function () {
	erpnext.whatsapp.init_bubble();
});
