// Employee Chat as a chat source: the Employee Chat page and the chat bubble both talk to
// it through this class. Direct, group and document threads; secret (end-to-end
// encrypted) threads; the archive lifecycle (archive → deep archive → unpack).

frappe.provide("erpnext.chat_sources");

const EC_API = "erpnext.crm.page.employee_chat.employee_chat";

erpnext.chat_sources.Employee = class EmployeeChatSource {
	constructor() {
		this.key = "employee";
		this.label = __("Employee Chat");
		this.page_route = "/app/employee-chat";
		this.media_source = "chat";
		this.search_placeholder = __("Search chats");
		this.list_empty_text = __("No chats yet");
		this.realtime_events = [
			"chat_message",
			"chat_seen",
			"chat_thread_archived",
			"chat_thread_purged",
			// Deliberately without chat_restore_progress: the bubble refreshes every list on each
			// event, and progress arrives many times a second.
			"chat_deep_archived",
			"chat_restore_done",
			"chat_restore_expired",
			"chat_deep_archive_dropped",
		];
		this.me = frappe.session.user;
		this.chats = [];
		// Two lists behind one launcher: person-to-person threads, and threads about a record.
		this.tabs = [
			{ key: "employee", label: __("Employees") },
			{ key: "entity", label: __("Entities") },
		];
	}

	static available() {
		return erpnext.whatsapp.can_use_employee_chat();
	}

	static is_entity(chat) {
		return !!(chat && chat.reference_doctype);
	}

	// True while the zip is the source of truth: nothing in the database to show.
	static is_packed(chat) {
		const st = (chat && chat.deep_archive && chat.deep_archive.status) || "";
		return !!st && st !== "Restored";
	}

	find(id) {
		return this.chats.find((c) => c.id === id);
	}

	tab_of(chat) {
		if (typeof chat === "string") chat = this.find(chat);
		return EmployeeChatSource.is_entity(chat) ? "entity" : "employee";
	}

	chats_for_tab(tab) {
		return this.chats.filter((c) => this.tab_of(c) === tab);
	}

	// ------------------------------------------------------------------ list

	async load_list() {
		const threads = await frappe.xcall(`${EC_API}.get_threads`);
		const old = {};
		for (const c of this.chats) old[c.id] = c;
		this.chats = threads.map((t) => {
			const prev = old[t.name] || {};
			const chat = {
				id: t.name,
				raw: t,
				title: t.display_title || t.title || t.name,
				thread_type: t.thread_type,
				participants: t.participants || [],
				other_user: t.other_user,
				avatar: this.avatar(t),
				preview: t.last_message_preview || "",
				time: t.last_message_on,
				unread: t.unread || 0,
				muted: t.muted || 0,
				my_last_read: t.my_last_read,
				is_secret: !!t.is_secret,
				title_prefix_html: t.is_secret
					? `<i class="fa fa-lock" title="${__("Secret chat")}"></i> `
					: "",
				reference_doctype: t.reference_doctype,
				reference_name: t.reference_name,
				reference_label: t.reference_label,
				reference_removed: t.reference_removed,
				is_archived: !!t.is_archived,
				is_deep_archived: !!t.is_deep_archived,
				disable_archive: t.disable_archive,
				disable_deep_archive: t.disable_deep_archive,
				// Keep a live archive job's progress across list reloads.
				deep_archive: Object.assign({}, t.deep_archive || {}, prev.deep_archive_live || {}),
				read_only: !!t.read_only,
				can_purge: t.can_purge,
				other_last_read: prev.other_last_read,
			};
			chat.read_only_reason = EmployeeChatSource.is_packed(chat)
				? __("This chat is in the deep archive — its messages are being unpacked")
				: __("This chat is archived — new messages are not allowed");
			chat.list_badge_html = chat.is_deep_archived
				? `<i class="fa fa-archive" style="color:var(--text-muted)" title="${erpnext.chat_deep_archive.badge_hint()}"></i>`
				: "";
			chat.header_sub = this.header_sub(chat);
			if (t.thread_type === "Direct") {
				const other = (t.participants || []).find((p) => p.user !== this.me);
				chat.other_last_read = other ? other.last_read_on : null;
			}
			return chat;
		});
		return this.chats;
	}

	avatar(t) {
		if (t.thread_type === "Group") return { name: t.display_title, key: t.name, icon: "fa fa-users" };
		if (t.thread_type === "Document")
			return { name: t.display_title, key: t.name, icon: "fa fa-file-text-o" };
		const info = t.other_user ? frappe.user_info(t.other_user) : null;
		return { name: t.display_title, key: t.other_user || t.name, image: info && info.image };
	}

	header_sub(chat) {
		const esc = frappe.utils.escape_html;
		if (chat.thread_type === "Document")
			return esc(`${__(chat.reference_doctype)} · ${chat.reference_name}`);
		if (chat.thread_type === "Group") return esc(__("{0} participants", [chat.participants.length]));
		return esc(chat.other_user || __("Direct chat"));
	}

	// ------------------------------------------------------------------ opening

	new_chat(view) {
		this.new_chat_dialog(view);
	}

	// Ask for the key before loading: with it the bubbles render decrypted straight away,
	// without it they render locked and the header offers to unlock.
	async before_open(chat) {
		if (chat.is_secret && !erpnext.chat_crypto.is_unlocked()) await erpnext.chat_crypto.ensure_unlocked();
	}

	prelude_html(chat) {
		return chat.thread_type === "Document" && chat.reference_doctype
			? erpnext.chat_render.reference_banner_html(chat)
			: "";
	}

	placeholder_html(chat) {
		if (!EmployeeChatSource.is_packed(chat)) return null;
		const d = chat.deep_archive || {};
		const deep = erpnext.chat_deep_archive;
		const busy = d.status === "Restoring" || d.status === "Packing";
		const when = d.archived_on ? frappe.datetime.str_to_user(d.archived_on) : "";
		const count = d.message_count
			? __("{0} messages · {1} files", [d.message_count, d.file_count || 0])
			: "";
		let body;
		if (d.status === "Failed") {
			body = `<div class="text-danger">${__("Could not unpack this chat")}</div>
				<button class="btn btn-default btn-sm cv-unpack" title="${deep.failed_hint()}">${__("Try again")}</button>`;
		} else if (busy) {
			body = `<div class="cv-progress" title="${deep.auto_hint()}"><div class="cv-progress-bar" style="width:${
				d.percent || 0
			}%;"></div></div>
				<div class="cv-progress-label">${this.progress_label(d)}</div>`;
		} else {
			body = `<div class="text-muted" title="${deep.auto_hint()}">${deep.unpacking()}</div>`;
		}
		return `<div class="cv-deep-card" title="${deep.badge_hint()}">
			<div class="cv-deep-icon"><i class="fa fa-archive"></i></div>
			<div class="cv-deep-title">${__("This conversation was archived long ago")}</div>
			<div class="text-muted">${frappe.utils.escape_html([count, when].filter(Boolean).join(" · "))}</div>
			<div class="cv-deep-body">${body}</div>
		</div>`;
	}

	progress_label(d) {
		return `${d.status === "Packing" ? __("Packing…") : __("Unpacking…")} ${d.percent || 0}%`;
	}

	// Opening a deep-archived chat is the request to unpack it. A failed archive stays a
	// manual retry so a broken zip is not re-enqueued on every open.
	bind_placeholder($thread, chat, view) {
		$thread.find(".cv-unpack").on("click", () => this.unpack(chat, view));
		const status = (chat.deep_archive || {}).status || "";
		if (status === "Archived" && view.auto_unpacked !== chat.id) {
			view.auto_unpacked = chat.id;
			this.unpack(chat, view);
		} else {
			this.watch_archive(chat, view);
		}
	}

	async unpack(chat, view) {
		let state;
		try {
			state = await this.restore(chat.id);
		} catch (e) {
			return;
		}
		this.apply_archive_state(state, view);
		this.watch_archive(chat, view);
	}

	restore(id) {
		return frappe.xcall(`${EC_API}.restore_deep_archive`, { thread: id });
	}

	archive_state(id) {
		return frappe.xcall(`${EC_API}.get_deep_archive_state`, { thread: id });
	}

	leave_deep_archive(id) {
		return frappe.xcall(`${EC_API}.leave_deep_archive`, { thread: id });
	}

	// The realtime room only reaches participants; a reader who never joined a record chat
	// has to poll, so both paths run and whichever arrives first wins.
	watch_archive(chat, view) {
		clearInterval(this.archive_poll);
		const st = (chat.deep_archive || {}).status || "";
		if (st !== "Packing" && st !== "Restoring") return;
		this.archive_poll = setInterval(async () => {
			if (!view || view.active !== chat.id) return clearInterval(this.archive_poll);
			try {
				this.apply_archive_state(await this.archive_state(chat.id), view);
			} catch (e) {
				clearInterval(this.archive_poll);
			}
		}, 2000);
	}

	// Fold an archive state payload into the chat and redraw what it changed.
	apply_archive_state(state, view) {
		if (!state || !state.thread) return;
		const chat = (view && view.chats[state.thread]) || this.find(state.thread);
		if (!chat) return;
		const was_packed = EmployeeChatSource.is_packed(chat);
		chat.deep_archive = Object.assign({}, chat.deep_archive, state);
		chat.deep_archive_live =
			state.status === "Restoring" || state.status === "Packing" ? chat.deep_archive : null;
		if (state.read_only !== undefined) chat.read_only = !!state.read_only;
		if (state.is_deep_archived !== undefined) chat.is_deep_archived = !!state.is_deep_archived;
		if (!view) return;
		if (view.active !== chat.id) return view.render_list();
		if (was_packed && !EmployeeChatSource.is_packed(chat)) {
			clearInterval(this.archive_poll);
			view.reopen();
			return;
		}
		const d = chat.deep_archive || {};
		const $bar = view.$thread.find(".cv-progress-bar");
		if (
			EmployeeChatSource.is_packed(chat) &&
			$bar.length &&
			(d.status === "Restoring" || d.status === "Packing")
		) {
			// Move the bar in place: a full re-render would fight the animation.
			$bar.css("width", (d.percent || 0) + "%");
			view.$thread.find(".cv-progress-label").text(this.progress_label(d));
		} else if (EmployeeChatSource.is_packed(chat)) {
			view.render_placeholder();
		} else {
			view.reopen();
			return;
		}
		view.render_header();
		view.render_composer();
		view.render_list();
	}

	// ------------------------------------------------------------------ messages

	async fetch(chat, opts) {
		const rows = await frappe.xcall(`${EC_API}.get_messages`, {
			thread: chat.id,
			before: opts.before || null,
			after: opts.after || null,
			limit: opts.limit || 50,
		});
		await this.decrypt(rows);
		return rows;
	}

	// Decrypt in place: an opened secret message carries `_dec`, so rendering stays
	// synchronous and a locked thread simply has no `_dec` anywhere.
	async decrypt(rows) {
		if (!erpnext.chat_crypto.is_unlocked()) return;
		for (const m of rows) {
			if (m.is_encrypted && !m._dec && !m._dec_failed) {
				try {
					m._dec = await erpnext.chat_crypto.decrypt(m.thread, m.message, m.enc_iv);
				} catch (e) {
					m._dec_failed = true;
				}
			}
			const rp = m.reply_preview;
			if (rp && rp.is_encrypted && rp.ciphertext && !rp._done) {
				rp._done = true;
				try {
					const dec = await erpnext.chat_crypto.decrypt(m.thread, rp.ciphertext, rp.enc_iv);
					rp.text = erpnext.chat_render.preview_text({
						is_encrypted: true,
						dec,
						content_type: rp.content_type,
					});
				} catch (e) {
					rp.text = __("Encrypted");
				}
			}
		}
	}

	build(rows, chat) {
		const read_only = !!(chat && chat.read_only);
		let last_out = null;
		for (const r of rows) if (r.sender === this.me) last_out = r.name;
		const seen_upto = chat && chat.thread_type === "Direct" ? chat.other_last_read : null;
		return rows.map((r) => {
			const out = r.sender === this.me;
			const reactions = Object.entries(r.reactions || {})
				.filter(([, users]) => (users || []).length)
				.map(([emoji, users]) => ({ emoji, count: users.length, mine: users.includes(this.me) }));
			const m = {
				id: r.name,
				raw: r,
				out,
				incoming: !out,
				time: r.creation,
				author: r.sender_name || r.sender,
				author_key: r.sender,
				content_type: r.content_type,
				text: r.message || "",
				attach: r.attach,
				link_data: r.link_data,
				is_encrypted: !!r.is_encrypted,
				dec: r._dec || null,
				dec_failed: !!r._dec_failed,
				reactions,
				can_react: !read_only,
				can_reply: !read_only,
			};
			// Direct chats show whether the other person has read our latest message.
			if (out && chat && chat.thread_type === "Direct" && r.name === last_out) {
				m.status = seen_upto && seen_upto >= r.creation ? "seen" : "sent";
			}
			if (r.reply_preview) {
				m.quote = { author: r.reply_preview.sender_name || "", text: r.reply_preview.text || "" };
				m.reply_target = r.reply_preview.name;
			}
			return m;
		});
	}

	show_authors(chat) {
		return chat && chat.thread_type !== "Direct" ? "in" : false;
	}

	async load_messages(id, limit) {
		const chat = this.find(id);
		if (!chat) return [];
		return this.build(await this.fetch(chat, { limit: limit || 20 }), chat);
	}

	// ------------------------------------------------------------------ sending

	// Everything a secret thread sends is encrypted here, before it leaves the page.
	async encrypted_args(chat, payload) {
		const { ciphertext, iv } = await erpnext.chat_crypto.encrypt(chat.id, payload);
		return { message: ciphertext, is_encrypted: 1, enc_iv: iv };
	}

	async post(chat, args) {
		const row = await frappe.xcall(`${EC_API}.send_message`, { thread: chat.id, ...args });
		if (row) await this.decrypt([row]);
		return row;
	}

	async send_text(chat, text, reply) {
		if (chat.is_secret && !(await erpnext.chat_crypto.ensure_unlocked())) throw new Error("locked");
		// A message that is nothing but a desk URL becomes a rich link card.
		let card = null;
		if (/^https?:\/\/\S+$/.test(text)) {
			try {
				const c = await frappe.xcall(`${EC_API}.resolve_link`, { url: text });
				if (c && c.kind && c.kind !== "external") card = c;
			} catch (e) {
				// plain text then
			}
		}
		const reply_to = reply ? reply.id : null;
		if (card) return this.send_card(chat, card, reply_to);
		const args = chat.is_secret ? await this.encrypted_args(chat, { text }) : { message: text };
		return this.post(chat, { reply_to, ...args });
	}

	async send_card(chat, card, reply_to) {
		const args = { content_type: "link", reply_to };
		if (chat.is_secret) Object.assign(args, await this.encrypted_args(chat, { link: card }));
		else args.link_data = JSON.stringify(card);
		return this.post(chat, args);
	}

	// The paperclip offers a file/photo upload or a link to an ERPNext record.
	attach(chat, opts) {
		opts = opts || {};
		const view = opts.view;
		if (!view || !opts.event) return this.attach_file(chat, opts);
		const $pop = view.popover(
			`<div class="cv-menu">
				<div class="cv-menu-item" data-act="file"><i class="fa fa-paperclip"></i>${__("Media / File")}</div>
				<div class="cv-menu-item" data-act="link"><i class="fa fa-link"></i>${__("Link")}</div>
			</div>`,
			opts.event.currentTarget,
			"above"
		);
		$pop.find('[data-act="file"]').on("click", () => {
			view.close_popovers();
			this.attach_file(chat, opts);
		});
		$pop.find('[data-act="link"]').on("click", () => {
			view.close_popovers();
			this.link_dialog(chat, opts);
		});
	}

	link_dialog(chat, opts) {
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
				let card;
				try {
					card = await frappe.xcall(`${EC_API}.resolve_link`, { url });
				} catch (e) {
					card = null;
				}
				if (!card || !card.url) card = { kind: "page", url, title: url };
				if (chat.is_secret && !(await erpnext.chat_crypto.ensure_unlocked())) return;
				frappe.dom.freeze(__("Sending…"));
				try {
					const row = await this.send_card(chat, card, opts.reply ? opts.reply.id : null);
					if (opts.done) opts.done(row);
				} catch (e) {
					frappe.msgprint(__("Failed to send message"));
				} finally {
					frappe.dom.unfreeze();
				}
			},
		});
		d.show();
	}

	attach_file(chat, opts) {
		if (chat.is_secret) return this.attach_secret(chat, opts);
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
					frappe.dom.freeze(__("Sending…"));
					try {
						const row = await this.post(chat, {
							content_type,
							attach: file.file_url,
							message: opts.caption || "",
							reply_to: opts.reply ? opts.reply.id : null,
						});
						if (opts.done) opts.done(row);
						resolve(row);
					} catch (e) {
						frappe.msgprint(__("Failed to send file"));
						reject(e);
					} finally {
						frappe.dom.unfreeze();
					}
				},
			});
		});
	}

	// Secret attachments never touch FileUploader: the bytes are encrypted in the page and
	// uploaded as opaque blobs, together with a preview built here.
	async attach_secret(chat, opts) {
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
				text: opts.caption || "",
				file: { url, key: enc.key, iv: enc.iv, name: file.name, mime: file.type, size: file.size },
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
			const row = await this.post(chat, {
				content_type,
				// The ciphertext URL is kept for housekeeping; it reveals nothing.
				attach: url,
				// The encrypted preview's URL lives inside the ciphertext, so name it here too —
				// otherwise the server can never link (or purge) that blob.
				extra_files: payload.thumb ? JSON.stringify([payload.thumb.url]) : null,
				reply_to: opts.reply ? opts.reply.id : null,
				...(await this.encrypted_args(chat, payload)),
			});
			if (opts.done) opts.done(row);
			return row;
		} catch (e) {
			frappe.msgprint(__("Failed to send file"));
		} finally {
			frappe.dom.unfreeze();
		}
	}

	async send_voice(chat, rec, reply) {
		const reply_to = reply ? reply.id : null;
		if (!chat.is_secret) {
			const url = await erpnext.chat_media.upload_audio(rec.blob, rec.ext);
			return this.post(chat, { content_type: "audio", attach: url, message: "", reply_to });
		}
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
		return this.post(chat, {
			content_type: "audio",
			attach: url,
			reply_to,
			...(await this.encrypted_args(chat, payload)),
		});
	}

	async react(chat, m, emoji) {
		const mine = (m.reactions || []).some((r) => r.emoji === emoji && r.mine);
		const reactions = await frappe.xcall(`${EC_API}.${mine ? "clear_reaction" : "set_reaction"}`, {
			message: m.id,
			emoji,
		});
		return Object.assign({}, m.raw, { reactions });
	}

	mark_read(chat, upto) {
		return frappe.xcall(`${EC_API}.mark_read`, { thread: chat.id, upto: upto || null });
	}

	set_muted(chat, muted) {
		return frappe.xcall(`${EC_API}.set_muted`, { thread: chat.id, muted });
	}

	notify_typing(chat) {
		frappe.xcall(`${EC_API}.typing`, { thread: chat.id }).catch(() => {});
	}

	route_for(id) {
		return id ? `${this.page_route}?thread=${encodeURIComponent(id)}` : this.page_route;
	}

	// ------------------------------------------------------------------ header

	header_badges_html(chat) {
		if (!chat.is_deep_archived) return "";
		const deep = erpnext.chat_deep_archive;
		return `<span class="cv-chip" title="${deep.badge_hint()}"><i class="fa fa-archive"></i> ${deep.badge()}</span>`;
	}

	// Archiving is open to anyone in the chat; removing and the deep archive are role-gated
	// server-side and only offered on an archived chat. A chat pinned out of the lifecycle
	// hides the buttons the server would refuse anyway.
	header_actions(chat) {
		const view = this.view;
		const deep = erpnext.chat_deep_archive;
		const out = [];
		if (chat.is_secret && !erpnext.chat_crypto.is_unlocked()) {
			out.push({
				icon: "fa fa-unlock-alt",
				title: __("Unlock"),
				on_click: async () => {
					await erpnext.chat_crypto.ensure_unlocked();
					if (erpnext.chat_crypto.is_unlocked()) view.reopen();
				},
			});
		}
		const busy = (chat.deep_archive || {}).status;
		if (chat.is_deep_archived && chat.can_purge) {
			const blocked = busy === "Packing" || busy === "Restoring";
			out.push({
				icon: "fa fa-level-up",
				title: blocked ? deep.busy_hint() : deep.leave_hint(),
				disabled: blocked,
				on_click: () => this.leave_deep(chat, view),
			});
		}
		const no_archive = chat.disable_archive && !chat.is_archived;
		if (!chat.is_deep_archived && !no_archive) {
			out.push({
				icon: `fa fa-${chat.is_archived ? "inbox" : "archive"}`,
				title: chat.is_archived
					? __("Return the chat to the active list — everyone in it sees it there again.")
					: __("Move the chat to the Archive section for everyone. It keeps all its messages."),
				on_click: () => this.toggle_archive(chat, view),
			});
		}
		if (
			chat.is_archived &&
			chat.can_purge &&
			!EmployeeChatSource.is_packed(chat) &&
			!chat.is_deep_archived &&
			!chat.disable_deep_archive
		) {
			out.push({
				icon: "fa fa-file-zip-o",
				title: __(
					"Pack the chat into an archive file and free the database. It is unpacked automatically the next time someone opens it."
				),
				on_click: () => this.deep_archive(chat, view),
			});
		}
		if (chat.is_archived && chat.can_purge) {
			out.push({
				icon: "fa fa-trash-o",
				title: __("Delete the chat with all its messages and files. This cannot be undone."),
				on_click: () => this.purge(chat, view),
			});
		}
		return out;
	}

	// ------------------------------------------------------------------ archive actions

	toggle_archive(chat, view) {
		const archived = chat.is_archived ? 0 : 1;
		// Archiving is global and freezes a record chat, so both directions ask first.
		return new Promise((resolve) => {
			frappe.confirm(
				erpnext.chat_archive_prompt(archived, EmployeeChatSource.is_entity(chat)),
				async () => {
					try {
						const res = await frappe.xcall(`${EC_API}.set_archived`, {
							thread: chat.id,
							archived,
						});
						chat.is_archived = !!res.is_archived;
						chat.read_only = !!res.read_only;
						frappe.show_alert({
							message: chat.is_archived ? __("Chat archived") : __("Chat unarchived"),
							indicator: "blue",
						});
						view.render_header();
						view.render_composer();
						view.render_list();
					} catch (e) {
						// server message already shown
					}
					resolve();
				},
				resolve
			);
		});
	}

	deep_archive(chat, view) {
		frappe.confirm(
			__(
				"Pack this chat into the deep archive? Messages and files are moved into an archive file and removed from the chat; they are unpacked again automatically the next time someone opens the chat."
			),
			async () => {
				try {
					await frappe.xcall(`${EC_API}.deep_archive_thread`, { thread: chat.id });
				} catch (e) {
					return;
				}
				chat.deep_archive = Object.assign({}, chat.deep_archive, { status: "Packing", percent: 0 });
				chat.read_only = true;
				view.placeholder_active = true;
				view.render_placeholder();
				view.render_header();
				view.render_composer();
			}
		);
	}

	// Keep the unpacked copy for good and delete the archive file.
	leave_deep(chat, view) {
		frappe.confirm(erpnext.chat_deep_archive.leave_confirm(), async () => {
			let state;
			try {
				state = await this.leave_deep_archive(chat.id);
			} catch (e) {
				return;
			}
			this.apply_archive_state(state, view);
			this.watch_archive(chat, view);
			if (!state.is_deep_archived) {
				frappe.show_alert({ message: __("Chat returned from the deep archive"), indicator: "blue" });
			}
		});
	}

	purge(chat, view) {
		frappe.confirm(
			__("Delete this chat with all its messages and files? This cannot be undone."),
			async () => {
				try {
					await frappe.xcall(`${EC_API}.purge_thread`, { thread: chat.id });
				} catch (e) {
					return;
				}
				view.forget(chat.id);
				frappe.show_alert({ message: __("Chat removed"), indicator: "red" });
			}
		);
	}

	// Chat Manager only: exempt a chat from the archive lifecycle.
	async set_archive_policy(chat, values, view) {
		const res = await frappe.xcall(
			`${EC_API}.set_archive_policy`,
			Object.assign({ thread: chat.id }, values)
		);
		this.apply_archive_policy(res, view);
		frappe.show_alert({ message: __("Chat configuration saved"), indicator: "blue" });
		return res;
	}

	apply_archive_policy(state, view) {
		const chat = state && view && view.chats[state.thread];
		if (!chat) return;
		chat.disable_archive = state.disable_archive;
		chat.disable_deep_archive = state.disable_deep_archive;
		if (view.active === state.thread) view.render_header();
	}

	// ------------------------------------------------------------------ realtime

	realtime(view) {
		this.view = view;
		const for_known = (fn) => (d) => {
			if (d && view.chats[d.thread]) fn(d, view.chats[d.thread]);
		};
		return {
			chat_message: async (d) => {
				if (!d) return;
				if (d.sender && d.sender !== this.me) {
					const c = view.chats[d.thread];
					erpnext.chat_sound.play(c && c.muted);
				}
				if (d.thread === view.active && d.name) {
					await this.decrypt([d]);
					view.hide_typing();
					view.push(d);
				} else if (d.thread === view.active) {
					// A system event (people added, renamed): re-read the tail.
					view.load_new(false);
				}
				view.refresh_list_soon();
			},
			chat_typing: (d) => {
				if (!d || d.thread !== view.active || d.user === this.me) return;
				const chat = view.chat();
				const who = (chat.participants || []).find((p) => p.user === d.user);
				const name = who ? who.employee_name || d.user : "";
				view.show_typing(
					name && chat.thread_type !== "Direct" ? __("{0} is typing…", [name]) : __("typing…")
				);
			},
			chat_seen: (d) => {
				if (!d || d.thread !== view.active || d.user === this.me) return;
				view.chat().other_last_read = d.last_read_on;
				view.rebuild();
				view.render_thread(false);
			},
			chat_reaction: (d) => {
				if (!d || d.thread !== view.active) return;
				const row = view.raw.find((r) => r.name === d.message);
				if (row) view.patch(Object.assign({}, row, { reactions: d.reactions }));
			},
			chat_thread_archived: for_known((d, chat) => {
				chat.is_archived = !!d.is_archived;
				chat.read_only = !!d.read_only;
				if (view.active === d.thread) {
					view.render_header();
					view.render_composer();
				}
				view.render_list();
			}),
			chat_archive_policy: (d) => this.apply_archive_policy(d, view),
			chat_thread_purged: for_known((d) => view.forget(d.thread)),
			chat_deep_archived: for_known((d) =>
				this.apply_archive_state(
					{
						thread: d.thread,
						status: "Archived",
						is_deep_archived: 1,
						read_only: 1,
						message_count: d.message_count,
						file_count: d.file_count,
					},
					view
				)
			),
			chat_restore_progress: for_known((d) =>
				this.apply_archive_state({ thread: d.thread, status: "Restoring", percent: d.percent }, view)
			),
			chat_restore_done: for_known((d) =>
				this.apply_archive_state(
					{ thread: d.thread, status: "Restored", percent: 100, read_only: 1 },
					view
				)
			),
			chat_restore_failed: for_known((d) =>
				this.apply_archive_state({ thread: d.thread, status: "Failed" }, view)
			),
			chat_restore_expired: for_known((d) =>
				this.apply_archive_state({ thread: d.thread, status: "Archived" }, view)
			),
			chat_deep_archive_dropped: for_known((d) => {
				clearInterval(this.archive_poll);
				this.apply_archive_state(d, view);
			}),
		};
	}

	// ------------------------------------------------------------------ info dialog

	async show_info(chat, view) {
		const info = await frappe.xcall(`${EC_API}.get_thread_info`, { thread: chat.id });
		const media = [];
		const files = [];
		const links = [];
		const R = erpnext.chat_render;
		let dialog;
		const jump = (name) => () => {
			dialog.hide();
			view.jump_to_message(name);
		};

		if (info.is_secret) {
			// Nothing was classified server-side: decrypt each row here and sort it.
			if (await erpnext.chat_crypto.ensure_unlocked()) {
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
							on_click: () => R.download_encrypted(file),
						});
					}
					for (const url of (dec.text || "").match(R.URL_RE) || []) {
						links.push({
							url,
							sender_name: m.sender_name,
							creation: m.creation,
							on_click: jump(m.name),
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
					for (const url of (dec.text || "").match(R.URL_RE) || []) {
						links.push({
							url,
							sender_name: m.sender_name,
							creation: m.creation,
							on_click: jump(m.name),
						});
					}
				}
			}
		} else {
			for (const m of info.attachments) {
				const item = { sender_name: m.sender_name, creation: m.creation, caption: m.message || "" };
				if (m.content_type === "image")
					media.push({ ...item, html: erpnext.chat_media.image_html(m.attach) });
				else files.push({ ...item, file_name: m.file_name, file_size: m.file_size, url: m.attach });
			}
			for (const l of info.links) links.push({ ...l, on_click: l.message ? jump(l.message) : null });
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
							await frappe.xcall(`${EC_API}.remove_participant`, {
								thread: chat.id,
								user: p.user,
							});
							dialog.hide();
							await view.refresh(true);
							this.show_info(view.chats[chat.id], view);
					  }
					: null,
		}));

		const deep = erpnext.chat_deep_archive;
		const actions = [
			{
				label: info.muted ? __("Unmute chat") : __("Mute chat"),
				hint: info.muted
					? __("Play the notification sound for this chat again.")
					: __("Silence the notification sound for this chat on all your devices."),
				on_click: async () => {
					await view.toggle_mute();
					dialog.hide();
				},
			},
		];
		const packed = (info.deep_archive || {}).status;
		if (!info.is_deep_archived && !(info.disable_archive && !info.is_archived)) {
			actions.push({
				label: info.is_archived ? __("Unarchive chat") : __("Archive chat"),
				hint: info.is_archived
					? __("Return the chat to the active list — everyone in it sees it there again.")
					: __("Move the chat to the Archive section for everyone. It keeps all its messages."),
				on_click: async () => {
					await this.toggle_archive(chat, view);
					dialog.hide();
				},
			});
		} else if (info.can_purge) {
			actions.push({
				label: deep.leave_label(),
				hint: deep.leave_hint(),
				on_click: () => {
					dialog.hide();
					this.leave_deep(chat, view);
				},
			});
		}
		if (
			info.is_archived &&
			info.can_purge &&
			!packed &&
			!info.is_deep_archived &&
			!info.disable_deep_archive
		) {
			actions.push({
				label: __("Move to deep archive"),
				hint: __(
					"Pack the chat into an archive file and free the database. It is unpacked automatically the next time someone opens it."
				),
				on_click: () => {
					dialog.hide();
					this.deep_archive(chat, view);
				},
			});
		}
		if (info.is_archived && info.can_purge) {
			actions.push({
				label: __("Remove chat"),
				hint: __("Delete the chat with all its messages and files. This cannot be undone."),
				on_click: () => {
					dialog.hide();
					this.purge(chat, view);
				},
			});
		}
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
							await frappe.xcall(`${EC_API}.rename_thread`, {
								thread: chat.id,
								title: v.title,
							});
							dialog.hide();
							await view.refresh(true);
							view.render_header();
						},
						__("Rename chat")
					);
				},
			});
		}

		// Archive policy: a chat manager's decision about the whole conversation.
		const settings = info.can_purge
			? [
					{
						label: __("Do not archive this chat"),
						description: __(
							"Nobody can move the chat to the archive, and the scheduled auto-archive skips it."
						),
						checked: !!info.disable_archive,
						on_change: (value) => this.set_archive_policy(chat, { disable_archive: value }, view),
					},
					{
						label: __("Do not move this chat to the deep archive"),
						description: __(
							"The chat is never packed into an archive file, neither by hand nor by the scheduled job."
						),
						checked: !!info.disable_deep_archive,
						disabled: !!info.is_deep_archived,
						disabled_reason: __("The chat is already in the deep archive — return it first."),
						on_change: (value) =>
							this.set_archive_policy(chat, { disable_deep_archive: value }, view),
					},
			  ]
			: null;

		dialog = erpnext.chat_info.show({
			title: info.display_title,
			subtitle: [
				is_group ? __("Group chat") : __("Direct chat"),
				info.is_secret ? __("Secret") : null,
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
			settings,
			on_add_person: can_admin
				? () => {
						dialog.hide();
						this.add_people_dialog(chat, view);
				  }
				: null,
		});
	}

	// ------------------------------------------------------------------ dialogs

	people_field(present, on_rows) {
		return {
			fieldname: "people",
			fieldtype: "MultiSelectList",
			label: __("People"),
			reqd: 1,
			get_data: (txt) =>
				frappe.xcall(`${EC_API}.search_employees`, { txt }).then((rows) => {
					// A lock marks people who can already receive an encrypted thread key.
					this.secret_ready = new Set(rows.filter((r) => r.secret_ready).map((r) => r.user_id));
					if (on_rows) on_rows(rows);
					return rows
						.filter((r) => !present || !present.has(r.user_id))
						.map((r) => ({
							value: r.user_id,
							description: `${r.employee_name}${r.department ? " · " + r.department : ""}${
								r.secret_ready ? " · 🔒" : ""
							}`,
						}));
				}),
		};
	}

	secret_blockers(people) {
		const ready = this.secret_ready || new Set();
		const not_ready = people.filter((u) => !ready.has(u));
		if (not_ready.length) {
			frappe.msgprint(
				__("These people have not enabled secret chats yet: {0}", [not_ready.join(", ")])
			);
			return true;
		}
		return false;
	}

	new_chat_dialog(view) {
		const d = new frappe.ui.Dialog({
			title: __("New chat"),
			fields: [
				this.people_field(null, (rows) => {
					if (!rows.length) {
						d.set_df_property(
							"people",
							"description",
							__(
								"No employees found. An Employee must be Active and have a User linked in the field 'User ID'."
							)
						);
					}
				}),
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
				const args = {
					participant_users: JSON.stringify(people),
					thread_type: people.length > 1 ? "Group" : "Direct",
					title: v.title || null,
				};
				if (v.is_secret) {
					if (this.secret_blockers(people)) return;
					if (!(await erpnext.chat_crypto.ensure_unlocked())) return;
					// The thread key is generated here and wrapped per participant — the server
					// only ever files the wrapped copies.
					const { wrapped } = await erpnext.chat_crypto.new_thread_key(people.concat([this.me]));
					args.is_secret = 1;
					args.thread_keys = JSON.stringify(wrapped);
				}
				d.hide();
				const res = await frappe.xcall(`${EC_API}.create_thread`, args);
				view.open_new(res.name);
			},
		});
		d.show();
	}

	// In a secret group the thread key is re-wrapped for the newcomer here — the server
	// cannot do it, it never holds the key.
	add_people_dialog(chat, view) {
		if (chat.thread_type !== "Group") return;
		const present = new Set((chat.participants || []).map((p) => p.user));
		const d = new frappe.ui.Dialog({
			title: __("Add people"),
			fields: [this.people_field(present)],
			primary_action_label: __("Add"),
			primary_action: async (v) => {
				const people = v.people || [];
				if (!people.length) return;
				let wrapped = [];
				if (chat.is_secret) {
					if (this.secret_blockers(people)) return;
					if (!(await erpnext.chat_crypto.ensure_unlocked())) return;
					const key = await erpnext.chat_crypto.thread_key(chat.id);
					wrapped = await erpnext.chat_crypto.wrap_for_users(key, people);
				}
				d.hide();
				for (const user of people) {
					const thread_key = wrapped.find((w) => w.user === user);
					await frappe.xcall(`${EC_API}.add_participant`, {
						thread: chat.id,
						user,
						thread_key: thread_key ? JSON.stringify(thread_key) : null,
					});
				}
				await view.refresh(true);
				view.render_header();
				this.show_info(view.chats[chat.id], view);
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
					`<a href="#" class="cv-revoke" data-name="${dev.name}">${__("Revoke")}</a></li>`
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
					frappe.show_alert({ message: __("Biometric unlock enabled"), indicator: "green" });
					d.hide();
				} catch (e) {
					frappe.msgprint(__("This device does not support biometric unlock"));
				}
			},
		});
		d.$wrapper.on("click", ".cv-revoke", async (e) => {
			e.preventDefault();
			await cc.revoke_biometric($(e.currentTarget).data("name"));
			d.hide();
			frappe.show_alert({ message: __("Device removed"), indicator: "green" });
		});
		d.show();
	}
};
