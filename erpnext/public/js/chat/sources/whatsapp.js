// WhatsApp as a chat source: the WhatsApp Chat page and the chat bubble both talk to
// WhatsApp through this class. Chats belong to a business number; the user sees the
// numbers they are assigned to, read-only on the ones they only watch.

frappe.provide("erpnext.chat_sources");

const WA_API = "erpnext.crm.page.whatsapp_chat.whatsapp_chat";
const WA_LINKABLE = ["Lead", "Contact", "Customer", "Opportunity", "Quotation", "Sales Order"];

erpnext.chat_sources.WhatsApp = class WhatsAppSource {
	constructor() {
		this.key = "whatsapp";
		this.label = __("WhatsApp");
		this.page_route = "/app/whatsapp-chat-center";
		this.media_source = "whatsapp";
		this.search_placeholder = __("Search number or name");
		this.realtime_events = ["whatsapp_message", "whatsapp_read"];
		this.side_panel = true;
		this.chats = [];
		this.account_filter = null;
		// Only people who answer a number can start a chat from it.
		if (!this.writable_numbers().length) this.new_chat = null;
	}

	static available() {
		return erpnext.whatsapp.can_use();
	}

	// The business numbers this user sees: [{name, label, access, read_only}].
	numbers() {
		return frappe.boot.whatsapp_accounts || [];
	}

	writable_numbers() {
		return this.numbers().filter((n) => !n.read_only);
	}

	find(id) {
		return this.chats.find((c) => c.id === id);
	}

	// ------------------------------------------------------------------ list

	async load_list() {
		const rows = await frappe.xcall(`${WA_API}.get_chats`, { account: this.account_filter || null });
		const R = erpnext.chat_render;
		const several = this.numbers().length > 1 && !this.account_filter;
		this.chats = rows.map((c) => {
			const label = c.number_label || "";
			return {
				id: c.name,
				title: c.title || c.phone,
				phone: c.phone,
				account: c.whatsapp_account,
				via: label,
				show_via: several,
				avatar: { name: c.title || c.phone, key: c.phone },
				preview: R.preview_text({ content_type: c.preview_content_type, text: c.preview }),
				preview_icon: R.media_icon(c.preview_content_type),
				time: c.last_message_on,
				unread: c.unread || 0,
				muted: c.muted || 0,
				my_last_read: c.my_last_read,
				read_only: !!c.read_only,
				read_only_reason: c.read_only ? __("Read only — you are a spectator of this number") : null,
				search_text: `${c.phone} ${label}`,
				list_badge_html: several
					? `<span class="cv-via" title="${__("WhatsApp number")}">${frappe.utils.escape_html(
							label
					  )}</span>`
					: "",
				header_sub:
					(c.title && c.title !== c.phone
						? `+${frappe.utils.escape_html(c.phone)}`
						: __("WhatsApp")) +
					`<span class="cv-chip" title="${__(
						"You write from this number"
					)}"><i class="fa fa-whatsapp"></i>${frappe.utils.escape_html(
						__("via {0}", [label])
					)}</span>`,
			};
		});
		return this.chats;
	}

	sidebar_tools_html() {
		if (this.numbers().length < 2) return "";
		return `<select class="form-control input-xs cv-number-filter">
			<option value="">${__("All numbers")}</option>
			${this.numbers()
				.map(
					(n) =>
						`<option value="${frappe.utils.escape_html(n.name)}">${frappe.utils.escape_html(
							n.label
						)}</option>`
				)
				.join("")}
		</select>`;
	}

	bind_sidebar_tools($el, view) {
		this.$number_filter = $el.find(".cv-number-filter");
		this.$number_filter.on("change", (e) => {
			this.account_filter = $(e.currentTarget).val() || null;
			view.refresh(true);
		});
	}

	// ------------------------------------------------------------------ opening

	// Deep links: ?chat=<chat>, ?phone=380… (phone icon, CRM form panel) or
	// ?number=<account> (the number card in WhatsApp Overview) to filter the list.
	open_request(view, ro) {
		const number = ro.number || frappe.utils.get_url_arg("number");
		if (number && this.numbers().some((n) => n.name === number)) {
			this.account_filter = number;
			this.$number_filter?.val(number);
			view.refresh(true);
			return true;
		}
		const chat = ro.chat || frappe.utils.get_url_arg("chat");
		if (chat) {
			if (view.chats[chat]) view.open(chat);
			return true;
		}
		const phone = ro.phone || frappe.utils.get_url_arg("phone");
		if (phone) {
			this.open_phone(view, phone);
			return true;
		}
		return false;
	}

	async open_phone(view, raw) {
		const phone = String(raw || "").replace(/\D/g, "");
		if (!phone) return;
		const existing = await frappe.xcall(`${WA_API}.find_chats`, { phone });
		const known = existing.find((c) => view.chats[c.name]);
		if (known) return view.open(known.name);
		this.pick_number(__("New chat with +{0}", [phone]), ({ account }) =>
			this.start(view, phone, account)
		);
	}

	async start(view, phone, account) {
		const chat = await frappe.xcall(`${WA_API}.start_chat`, { phone, account });
		view.open_new(chat);
	}

	// Ask which business number to write from when the user answers more than one.
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

	new_chat(view) {
		this.pick_number(__("New chat"), ({ phone, account }) => this.start(view, phone, account), [
			{
				fieldname: "phone",
				fieldtype: "Data",
				label: __("Phone number"),
				reqd: 1,
				description: __("Include country code, e.g. 380XXXXXXXXX"),
			},
		]);
	}

	// ------------------------------------------------------------------ messages

	fetch(chat, opts) {
		return frappe.xcall(`${WA_API}.get_messages`, {
			chat: chat.id,
			before: opts.before || null,
			after: opts.after || null,
			limit: opts.limit || 50,
		});
	}

	// Reactions arrive as their own rows pointing at a message_id; fold them into badges on
	// the target (one reaction per side — the newest wins, an empty one removes it).
	build(rows, chat) {
		const R = erpnext.chat_render;
		const by_mid = {};
		for (const r of rows) if (r.message_id) by_mid[r.message_id] = r;
		const reacted = {}; // message_id -> {in, out}
		for (const r of rows) {
			if (r.content_type !== "reaction" || !r.reply_to_message_id) continue;
			const side = r.type === "Outgoing" ? "out" : "in";
			(reacted[r.reply_to_message_id] = reacted[r.reply_to_message_id] || {})[side] = r.message || "";
		}
		const read_only = !!(chat && chat.read_only);
		const out = [];
		for (const r of rows) {
			if (r.content_type === "reaction") continue;
			const is_out = r.type === "Outgoing";
			const status = (r.status || "").toLowerCase();
			const m = {
				id: r.name,
				raw: r,
				out: is_out,
				incoming: !is_out,
				time: r.creation,
				author: is_out
					? r.sender_name || __("You")
					: (chat && chat.title) || r.profile_name || r.from,
				author_key: is_out ? r.owner : r.from,
				content_type: r.content_type,
				text: r.message || "",
				attach: r.attach,
				status: is_out ? status || "pending" : null,
				error: r.status_error,
				message_id: r.message_id,
				reply_key: r.message_id,
				can_react: !!r.message_id && !read_only,
				can_reply: !read_only,
				can_resend: is_out && status === "failed" && !read_only,
			};
			const target = r.is_reply && r.reply_to_message_id ? by_mid[r.reply_to_message_id] : null;
			if (target) {
				m.quote = {
					author:
						target.type === "Outgoing"
							? target.sender_name || __("You")
							: (chat && chat.title) || target.profile_name || target.from,
					text: R.preview_text({ content_type: target.content_type, text: target.message }),
				};
				m.reply_target = target.name;
			}
			const rx = r.message_id && reacted[r.message_id];
			if (rx) {
				const list = [];
				if (rx.in) list.push({ emoji: rx.in, count: 1, mine: false });
				if (rx.out) {
					const same = list.find((x) => x.emoji === rx.out);
					if (same) {
						same.count = 2;
						same.mine = true;
					} else list.push({ emoji: rx.out, count: 1, mine: true });
				}
				m.reactions = list;
			}
			out.push(m);
		}
		return out;
	}

	// Outgoing messages carry the manager who sent them — several people answer one number.
	show_authors() {
		return "out";
	}

	async load_messages(id, limit) {
		const chat = this.find(id);
		if (!chat) return [];
		return this.build(await this.fetch(chat, { limit: limit || 20 }), chat);
	}

	// ------------------------------------------------------------------ sending

	send_text(chat, text, reply) {
		return frappe.xcall(`${WA_API}.send_text`, {
			chat: chat.id,
			message: text,
			reply_to_message_id: reply ? reply.id : null,
		});
	}

	attach(chat, opts) {
		opts = opts || {};
		return new Promise((resolve, reject) => {
			new frappe.ui.FileUploader({
				folder: "Home/Attachments",
				on_success: async (file) => {
					let ct = erpnext.chat_media.detect_type(
						file.file_type || file.type,
						file.file_name || file.file_url
					);
					if (!["image", "video", "audio"].includes(ct)) ct = "document";
					frappe.dom.freeze(__("Sending..."));
					try {
						await frappe.xcall(`${WA_API}.send_media`, {
							chat: chat.id,
							attach: file.file_url,
							content_type: ct,
							caption: opts.caption || null,
							reply_to_message_id: opts.reply ? opts.reply.id : null,
						});
						if (opts.done) opts.done();
						resolve();
					} catch (e) {
						frappe.msgprint(__("Failed to send media"));
						reject(e);
					} finally {
						frappe.dom.unfreeze();
					}
				},
			});
		});
	}

	// The server transcodes webm (all Chrome records) to ogg/opus, which Meta accepts.
	async send_voice(chat, rec, reply) {
		const url = await erpnext.chat_media.upload_audio(rec.blob, rec.ext);
		return frappe.xcall(`${WA_API}.send_media`, {
			chat: chat.id,
			attach: url,
			content_type: "audio",
			caption: "",
			reply_to_message_id: reply ? reply.id : null,
		});
	}

	// One reaction per message on our side: tapping ours again removes it.
	react(chat, m, emoji) {
		const mine = (m.reactions || []).find((r) => r.mine);
		return frappe.xcall(`${WA_API}.send_reaction`, {
			chat: chat.id,
			message_id: m.message_id,
			emoji: mine && mine.emoji === emoji ? "" : emoji,
		});
	}

	resend(chat, m) {
		const text = (m.text || "").replace(/<[^>]*>/g, "").trim();
		if (R_MEDIA(m)) {
			return frappe.xcall(`${WA_API}.send_media`, {
				chat: chat.id,
				attach: m.attach,
				content_type: m.content_type,
				caption: text,
			});
		}
		if (!text) {
			frappe.msgprint(__("Nothing to resend"));
			return Promise.resolve();
		}
		return frappe.xcall(`${WA_API}.send_text`, { chat: chat.id, message: text });
	}

	mark_read(chat, upto) {
		return frappe.xcall(`${WA_API}.mark_read`, { chat: chat.id, upto: upto || null });
	}

	set_muted(chat, muted) {
		return frappe.xcall(`${WA_API}.set_muted`, { chat: chat.id, muted });
	}

	notify_typing(chat) {
		frappe.xcall(`${WA_API}.notify_typing`, { chat: chat.id }).catch(() => {});
	}

	compose_buttons(chat) {
		if (chat.read_only) return [];
		return [
			{
				icon: "fa fa-file-text-o",
				title: __("Send template"),
				on_click: (view) => this.template_dialog(chat, view),
			},
		];
	}

	menu_items(m) {
		if (!frappe.user.has_role("System Manager")) return [];
		return [
			{
				icon: "fa fa-external-link",
				label: __("Open WhatsApp Message"),
				action: () => frappe.set_route("Form", "WhatsApp Message", m.id),
			},
		];
	}

	route_for(id) {
		return id ? `${this.page_route}?chat=${encodeURIComponent(id)}` : this.page_route;
	}

	// ------------------------------------------------------------------ realtime

	realtime(view) {
		const me = frappe.session.user;
		return {
			whatsapp_message: (d) => {
				if (d && d.type === "Incoming") {
					const c = view.chats[d.chat];
					erpnext.chat_sound.play(c && c.muted);
				}
				if (d && d.chat === view.active) view.load_new(false);
				view.refresh_list_soon();
			},
			whatsapp_read: () => view.refresh_list_soon(),
			whatsapp_typing: (d) => {
				if (!d || d.chat !== view.active || d.user === me) return;
				view.show_typing(__("{0} is typing…", [d.full_name || d.user]));
			},
		};
	}

	// ------------------------------------------------------------------ templates

	// Approved templates are the only way to write outside Meta's 24h window.
	async template_dialog(chat, view) {
		let templates;
		try {
			templates = await frappe.xcall(`${WA_API}.list_templates`);
		} catch (e) {
			frappe.msgprint(__("Could not load templates"));
			return;
		}
		if (!templates || !templates.length) {
			frappe.msgprint(__("No approved templates found. Create and sync a WhatsApp Template first."));
			return;
		}
		const by_name = {};
		templates.forEach((t) => (by_name[t.name] = t));
		const send = (template, body_params) =>
			view.run_send(
				() =>
					frappe.xcall(`${WA_API}.send_template`, {
						chat: chat.id,
						template,
						body_params: body_params ? JSON.stringify(body_params) : null,
					}),
				__("Failed to send template")
			);
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
				if (!t || !(t.params || []).length) return send(template, null);
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
						send(template, body);
					},
					__("Template parameters"),
					__("Send")
				);
			},
			__("Send template"),
			__("Next")
		);
	}

	// ------------------------------------------------------------------ info + side panel

	async show_info(chat, view) {
		const info = await frappe.xcall(`${WA_API}.get_chat_overview`, { chat: chat.id });
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
		const people = [{ name: info.title, subtitle: `+${info.phone}`, user: info.phone }];
		if (info.contact) people.push({ name: info.contact, subtitle: __("Contact") });
		for (const m of info.managers || [])
			people.push({ name: m.full_name || m.user, subtitle: __("Responsible") });
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
						await view.toggle_mute();
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

	async render_side(chat, $el, view) {
		$el.html(`<div class="text-muted">${__("Loading...")}</div>`);
		let ctx;
		try {
			ctx = await frappe.xcall(`${WA_API}.get_chat_context`, { chat: chat.id });
		} catch (e) {
			$el.html(`<div class="text-muted">${__("Could not load context")}</div>`);
			return;
		}
		if (view.active !== chat.id) return;
		const esc = frappe.utils.escape_html;
		const read_only = !!ctx.read_only;
		const ent = (e, removable) => `<div class="cv-ent">
			<span class="cv-ent-main" data-dt="${esc(e.doctype)}" data-nm="${esc(e.name)}">${esc(
			e.label
		)}<div class="cv-ent-sub">${esc(__(e.doctype))}</div></span>${
			removable
				? `<span class="cv-unlink" title="${__("Unlink")}"><i class="fa fa-times"></i></span>`
				: ""
		}
		</div>`;
		const linked =
			(ctx.linked || []).map((e) => ent(e, !read_only)).join("") ||
			`<div class="text-muted" style="font-size:var(--text-sm);">${__("None")}</div>`;
		const derived = (ctx.derived || []).map((e) => ent(e, false)).join("");
		const managers = (ctx.managers || []).map((m) => esc(m.full_name || m.user)).join(", ");
		const actions = read_only
			? ""
			: `<div class="cv-side-actions">
				<button class="btn btn-xs btn-default cv-link-btn"><i class="fa fa-link"></i>${__("Link Document")}</button>
			</div>
			<h6>${__("Create from Chat")}</h6>
			<div class="cv-side-actions">
				<button class="btn btn-xs btn-default" data-create="opportunity"><i class="fa fa-handshake-o"></i>${__(
					"Opportunity"
				)}</button>
				<button class="btn btn-xs btn-default" data-create="todo"><i class="fa fa-check-square-o"></i>${__(
					"Task"
				)}</button>
				<button class="btn btn-xs btn-default" data-create="note"><i class="fa fa-sticky-note-o"></i>${__(
					"Note"
				)}</button>
				<button class="btn btn-xs btn-default" data-create="event"><i class="fa fa-calendar"></i>${__(
					"Event"
				)}</button>
			</div>`;
		$el.html(`
			<h6>${__("WhatsApp number")}</h6>
			<div class="cv-ent cv-number-ent" style="justify-content:flex-start;gap:10px;"${
				frappe.boot.whatsapp_manager ? ` data-account="${esc(ctx.whatsapp_account)}"` : ""
			}>${erpnext.chat_render.avatar_html(
			ctx.number_image
				? { image: ctx.number_image }
				: { name: ctx.account_name, key: ctx.whatsapp_account, icon: "fa fa-whatsapp" },
			32
		)}<span class="cv-ent-main">${esc(ctx.number_label || "")}<div class="cv-ent-sub">${esc(
			ctx.verified_name || ctx.account_name || ""
		)}${read_only ? " · " + __("read only") : ""}</div></span></div>
			${actions}
			<h6>${__("Linked Documents")}</h6>
			<div>${linked}</div>
			${derived ? `<h6>${__("Related (by contact)")}</h6><div>${derived}</div>` : ""}
			<h6>${__("Responsible")}</h6>
			<div class="text-muted" style="font-size:var(--text-sm);">${managers || __("None")}</div>
		`);
		const rerender = () => this.render_side(chat, $el, view);
		$el.find(".cv-number-ent[data-account]")
			.css("cursor", "pointer")
			.attr("title", __("Open number card"))
			.on("click", (e) =>
				frappe.set_route("whatsapp-overview", "number", $(e.currentTarget).attr("data-account"))
			);
		$el.find(".cv-ent-main[data-dt]").on("click", (e) =>
			frappe.set_route("Form", $(e.currentTarget).attr("data-dt"), $(e.currentTarget).attr("data-nm"))
		);
		$el.find(".cv-unlink").on("click", async (e) => {
			const $m = $(e.currentTarget).siblings(".cv-ent-main");
			await frappe.xcall(`${WA_API}.unlink_entity`, {
				chat: chat.id,
				link_doctype: $m.attr("data-dt"),
				link_name: $m.attr("data-nm"),
			});
			rerender();
		});
		$el.find(".cv-link-btn").on("click", () => this.link_dialog(chat, rerender));
		$el.find("[data-create]").on("click", (e) =>
			this.create(chat, $(e.currentTarget).attr("data-create"), rerender)
		);
	}

	link_dialog(chat, done) {
		const d = new frappe.ui.Dialog({
			title: __("Link Document"),
			fields: [
				{
					fieldname: "link_doctype",
					fieldtype: "Select",
					label: __("Type"),
					options: WA_LINKABLE.join("\n"),
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
				await frappe.xcall(`${WA_API}.link_entity`, {
					chat: chat.id,
					link_doctype: v.link_doctype,
					link_name: v.link_name,
				});
				d.hide();
				done();
			},
		});
		d.show();
	}

	create(chat, what, done) {
		const go = (res) => {
			frappe.show_alert({ message: __("Created {0}", [res.name]), indicator: "green" });
			frappe.set_route("Form", res.doctype, res.name);
		};
		const call = (method, args, title, fields) => {
			const run = async (v) => {
				const res = await frappe.xcall(`${WA_API}.${method}`, { chat: chat.id, ...(v || {}) });
				if (method === "create_opportunity") done();
				go(res);
			};
			if (!fields) return run(args);
			frappe.prompt(fields, run, title, __("Create"));
		};
		if (what === "opportunity") return call("create_opportunity", {});
		if (what === "todo") {
			return call("create_todo", null, __("New Task"), [
				{ fieldname: "description", fieldtype: "Small Text", label: __("Task"), reqd: 1 },
			]);
		}
		if (what === "note") {
			return call("create_note", null, __("New Note"), [
				{ fieldname: "title", fieldtype: "Data", label: __("Title"), reqd: 1 },
				{ fieldname: "content", fieldtype: "Text Editor", label: __("Content") },
			]);
		}
		if (what === "event") {
			return call("create_event", null, __("New Event"), [
				{ fieldname: "subject", fieldtype: "Data", label: __("Subject"), reqd: 1 },
				{ fieldname: "starts_on", fieldtype: "Datetime", label: __("Starts On"), reqd: 1 },
			]);
		}
	}
};

function R_MEDIA(m) {
	return ["image", "video", "audio", "document"].includes(m.content_type) && !!m.attach;
}
