// WhatsApp Mock (dev/test only): play the customer side of a WhatsApp Account in Mock Mode.
// Messages sent here arrive at the account exactly like a message from Meta, and everything
// our agents answer from the WhatsApp Chat page shows up here as the customer's phone would.

frappe.pages["whatsapp-mock"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("WhatsApp Mock"),
		single_column: true,
	});
	wrapper.mock = new WhatsAppMock(page, wrapper);
};

frappe.pages["whatsapp-mock"].on_page_show = function (wrapper) {
	if (wrapper.mock) wrapper.mock.start();
};

frappe.pages["whatsapp-mock"].on_page_hide = function (wrapper) {
	if (wrapper.mock) wrapper.mock.stop();
};

const MOCK_API = "erpnext.crm.whatsapp_mock.";

class WhatsAppMock {
	constructor(page, wrapper) {
		this.page = page;
		this.accounts = [];
		this.customers = [];
		this.account = null;
		this.phone = null;
		this.messages = [];
		this.reply_to = null;
		this.timer = null;
		if (frappe.boot.instance_env === "prod") {
			$(wrapper)
				.find(".layout-main-section")
				.html(
					`<div class="text-muted p-4">${__("WhatsApp Mock is not available on production")}</div>`
				);
			return;
		}
		this.render();
		this.load_state();
		frappe.realtime.on("whatsapp_message", () => this.refresh());
	}

	render() {
		const body = $(this.page.main).addClass("wa-mock");
		body.html(`
			<style>
				.wa-mock .wm-wrap { display: flex; gap: 12px; height: calc(100vh - 170px); min-height: 360px; }
				.wa-mock .wm-side { width: 280px; display: flex; flex-direction: column; gap: 8px; }
				.wa-mock .wm-list { flex: 1; overflow-y: auto; border: 1px solid var(--border-color); border-radius: var(--border-radius-md); }
				.wa-mock .wm-item { padding: 8px 12px; cursor: pointer; border-bottom: 1px solid var(--border-color); }
				.wa-mock .wm-item.active { background: var(--control-bg); }
				.wa-mock .wm-main { flex: 1; display: flex; flex-direction: column; border: 1px solid var(--border-color); border-radius: var(--border-radius-md); min-width: 0; }
				.wa-mock .wm-head { padding: 10px 14px; border-bottom: 1px solid var(--border-color); font-weight: 600; }
				.wa-mock .wm-msgs { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 6px; background: var(--subtle-fg); }
				.wa-mock .wm-bubble { max-width: 70%; padding: 6px 10px; border-radius: 10px; background: var(--card-bg); box-shadow: var(--shadow-sm); word-break: break-word; }
				.wa-mock .wm-bubble.me { align-self: flex-end; background: var(--green-100, #dcf8c6); color: var(--gray-900, #111); }
				.wa-mock .wm-meta { font-size: 11px; color: var(--text-muted); text-align: right; }
				.wa-mock .wm-reply { font-size: 11px; color: var(--text-muted); border-left: 3px solid var(--border-color); padding-left: 6px; margin-bottom: 2px; }
				.wa-mock .wm-compose { display: flex; gap: 8px; padding: 8px; border-top: 1px solid var(--border-color); align-items: center; }
				.wa-mock .wm-compose input[type=text] { flex: 1; }
				.wa-mock .wm-empty { margin: auto; color: var(--text-muted); }
			</style>
			<div class="wm-wrap">
				<div class="wm-side">
					<select class="form-control wm-account"></select>
					<button class="btn btn-primary btn-sm wm-new"><i class="fa fa-plus"></i> ${__("New chat")}</button>
					<div class="wm-list"></div>
				</div>
				<div class="wm-main">
					<div class="wm-head"></div>
					<div class="wm-msgs"><div class="wm-empty">${__("Pick a chat or start a new one")}</div></div>
					<div class="wm-compose" style="display:none">
						<label class="btn btn-default btn-sm mb-0" title="${__("Attach")}"><i class="fa fa-paperclip"></i>
							<input type="file" class="wm-file" style="display:none"></label>
						<input type="text" class="form-control wm-text" placeholder="${__("Message as the customer")}">
						<button class="btn btn-primary btn-sm wm-send"><i class="fa fa-paper-plane"></i></button>
					</div>
				</div>
			</div>`);
		this.$ = {
			account: body.find(".wm-account"),
			list: body.find(".wm-list"),
			head: body.find(".wm-head"),
			msgs: body.find(".wm-msgs"),
			compose: body.find(".wm-compose"),
			text: body.find(".wm-text"),
		};
		this.$.account.on("change", () => {
			this.account = this.$.account.val();
			this.phone = null;
			this.render_list();
			this.render_thread();
		});
		body.find(".wm-new").on("click", () => this.new_chat());
		body.find(".wm-send").on("click", () => this.send());
		this.$.text.on("keydown", (e) => {
			if (e.key === "Enter") this.send();
		});
		body.find(".wm-file").on("change", (e) => this.send_file(e.target));
	}

	start() {
		if (this.timer || !this.$) return;
		this.timer = setInterval(() => this.refresh(), 4000);
	}

	stop() {
		clearInterval(this.timer);
		this.timer = null;
	}

	load_state() {
		return frappe.call(MOCK_API + "get_state").then((r) => {
			const state = r.message || {};
			this.accounts = state.accounts || [];
			this.customers = state.customers || [];
			if (!this.accounts.length) {
				this.$.msgs.html(
					`<div class="wm-empty">${__(
						"No WhatsApp Account is in Mock Mode. Tick Mock Mode on an account first."
					)}</div>`
				);
			}
			this.$.account.html(
				this.accounts
					.map(
						(a) =>
							`<option value="${frappe.utils.escape_html(a.name)}">${frappe.utils.escape_html(
								a.account_name || a.name
							)}</option>`
					)
					.join("")
			);
			if (!this.account || !this.accounts.find((a) => a.name === this.account)) {
				this.account = this.accounts.length ? this.accounts[0].name : null;
			}
			this.$.account.val(this.account);
			this.render_list();
		});
	}

	render_list() {
		const rows = this.customers.filter((c) => c.account === this.account);
		this.$.list.html(
			rows
				.map(
					(c) => `<div class="wm-item ${
						c.phone === this.phone ? "active" : ""
					}" data-phone="${frappe.utils.escape_html(c.phone)}">
						<div><b>${frappe.utils.escape_html(c.profile_name || c.phone)}</b></div>
						<div class="text-muted small">+${frappe.utils.escape_html(c.phone)}</div></div>`
				)
				.join("") || `<div class="p-3 text-muted">${__("No chats yet")}</div>`
		);
		this.$.list
			.find(".wm-item")
			.on("click", (e) => this.open($(e.currentTarget).data("phone").toString()));
	}

	new_chat() {
		if (!this.account) return;
		const d = new frappe.ui.Dialog({
			title: __("New chat"),
			fields: [
				{
					fieldname: "phone",
					fieldtype: "Data",
					label: __("Phone number"),
					reqd: 1,
					description: "380501234567",
				},
				{ fieldname: "name", fieldtype: "Data", label: __("Profile name") },
			],
			primary_action_label: __("Start"),
			primary_action: (v) => {
				const phone = (v.phone || "").replace(/\D/g, "");
				if (!phone) return;
				d.hide();
				if (!this.customers.find((c) => c.account === this.account && c.phone === phone)) {
					this.customers.unshift({ account: this.account, phone, profile_name: v.name || phone });
				}
				this.profile_name = v.name || null;
				this.render_list();
				this.open(phone);
			},
		});
		d.show();
	}

	open(phone) {
		this.phone = phone;
		this.messages = [];
		this.reply_to = null;
		this.render_list();
		this.$.compose.show();
		this.render_thread();
		this.refresh();
	}

	refresh() {
		if (!this.account) return;
		if (!this.phone) return this.load_state();
		frappe
			.call({
				method: MOCK_API + "get_conversation",
				args: { account: this.account, phone: this.phone },
				freeze: false,
				silent: true,
			})
			.then((r) => {
				this.messages = r.message || [];
				this.render_thread();
			});
	}

	render_thread() {
		if (!this.phone) {
			this.$.head.text("");
			this.$.compose.hide();
			return;
		}
		const customer =
			this.customers.find((c) => c.account === this.account && c.phone === this.phone) || {};
		this.$.head.html(
			`${frappe.utils.escape_html(
				customer.profile_name || this.phone
			)} <span class="text-muted small">+${frappe.utils.escape_html(this.phone)}</span>`
		);
		const box = this.$.msgs[0];
		const at_bottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
		const by_id = Object.fromEntries(this.messages.map((m) => [m.message_id, m]));
		this.$.msgs.html(
			this.messages
				.map((m) => {
					const mine = m.type === "Incoming";
					const quoted = m.reply_to_message_id && by_id[m.reply_to_message_id];
					const attach = m.attach
						? m.content_type === "image"
							? `<a href="${m.attach}" target="_blank"><img src="${m.attach}" style="max-width:240px;border-radius:6px"></a>`
							: `<a href="${
									m.attach
							  }" target="_blank"><i class="fa fa-file-o"></i> ${frappe.utils.escape_html(
									m.attach.split("/").pop()
							  )}</a>`
						: "";
					const text =
						m.content_type === "reaction"
							? `<span style="font-size:20px">${frappe.utils.escape_html(
									m.message || ""
							  )}</span>`
							: frappe.utils.escape_html(m.message || "").replace(/\n/g, "<br>");
					const status = mine ? "" : ` · ${frappe.utils.escape_html(m.status || "")}`;
					return `<div class="wm-bubble ${mine ? "me" : ""}" data-id="${frappe.utils.escape_html(
						m.message_id || ""
					)}">
						${
							quoted
								? `<div class="wm-reply">${frappe.utils.escape_html(
										(quoted.message || "").slice(0, 80)
								  )}</div>`
								: ""
						}
						${attach}${text}
						<div class="wm-meta">${frappe.datetime.str_to_user(m.creation).slice(-8)}${status}</div></div>`;
				})
				.join("") || `<div class="wm-empty">${__("No messages yet")}</div>`
		);
		this.$.msgs.find(".wm-bubble[data-id]").on("dblclick", (e) => {
			this.reply_to = $(e.currentTarget).data("id") || null;
			this.$.text.attr(
				"placeholder",
				this.reply_to ? __("Replying… (message as the customer)") : __("Message as the customer")
			);
			this.$.text.focus();
		});
		if (at_bottom) box.scrollTop = box.scrollHeight;
	}

	send() {
		const text = this.$.text.val();
		if (!text.trim() || !this.phone) return;
		this.deliver({ text });
		this.$.text.val("");
	}

	deliver(args) {
		return frappe
			.call({
				method: MOCK_API + "send_as_customer",
				args: {
					account: this.account,
					phone: this.phone,
					profile_name: (
						this.customers.find((c) => c.account === this.account && c.phone === this.phone) || {}
					).profile_name,
					reply_to: this.reply_to,
					...args,
				},
			})
			.then(() => {
				this.reply_to = null;
				this.$.text.attr("placeholder", __("Message as the customer"));
				this.refresh();
			});
	}

	send_file(input) {
		const file = input.files[0];
		input.value = "";
		if (!file || !this.phone) return;
		const form = new FormData();
		form.append("file", file, file.name);
		form.append("is_private", 1);
		fetch("/api/method/upload_file", {
			method: "POST",
			headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
			body: form,
		})
			.then((r) => r.json())
			.then((r) => this.deliver({ file_url: r.message.file_url, text: this.$.text.val() || null }))
			.then(() => this.$.text.val(""));
	}
}
