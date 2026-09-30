// WhatsApp Contact: one customer number across every business number they write to —
// name and photo in ERP (rename, own photo, back to what WhatsApp reports), their chats,
// linked documents and activity. /app/whatsapp-person/<phone>

frappe.pages["whatsapp-person"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("WhatsApp Contact"),
		single_column: true,
	});
	wrapper.whatsapp_person = new WhatsAppPerson(page);
};

frappe.pages["whatsapp-person"].on_page_show = function (wrapper) {
	wrapper.whatsapp_person?.follow_route();
};

const WAP_API = "erpnext.crm.whatsapp_person";

class WhatsAppPerson {
	constructor(page) {
		this.page = page;
		this.phone = null;
		this.data = null;
		this.page.main.html(`<div class="whatsapp-person"></div>`);
		this.$body = this.page.main.find(".whatsapp-person");
		this.bind();
		frappe.router.on("change", () => {
			if (frappe.get_route()[0] === "whatsapp-person") this.follow_route();
		});
	}

	follow_route() {
		const phone = frappe.get_route()[1];
		if (!phone || phone === this.phone) return;
		this.phone = phone;
		this.data = null;
		this.$body.empty();
		this.load();
	}

	load() {
		return frappe.call({ method: `${WAP_API}.get_person`, args: { phone: this.phone } }).then((r) => {
			this.data = r.message;
			this.render();
		});
	}

	call(method, args) {
		return frappe
			.call({ method: `${WAP_API}.${method}`, args: { phone: this.phone, ...args }, freeze: true })
			.then((r) => {
				this.data = r.message;
				this.render();
			});
	}

	esc(v) {
		return frappe.utils.escape_html(v === null || v === undefined ? "" : String(v));
	}

	render() {
		const d = this.data;
		const E = erpnext.entity;
		const esc = (v) => this.esc(v);
		this.page.set_title(d.name);

		const facts = [
			[__("Phone"), `+${esc(d.phone)}`],
			[
				__("Name in WhatsApp"),
				d.whatsapp_name ? esc(d.whatsapp_name) : `<span class="text-muted">—</span>`,
			],
			[
				__("Contact"),
				d.contact
					? E.html({
							name: d.contact_name || d.contact,
							key: d.contact,
							icon: "fa fa-address-card-o",
							route: ["Form", "Contact", d.contact],
					  })
					: `<span class="text-muted">—</span>`,
			],
			[__("First message"), d.first_message ? frappe.datetime.str_to_user(d.first_message) : "—"],
			[__("Last message"), d.last_message ? frappe.datetime.comment_when(d.last_message) : "—"],
			[__("Messages in / out"), `${d.messages_in} / ${d.messages_out}`],
		]
			.map(
				([k, v]) =>
					`<div class="wap-fact"><span class="text-muted">${k}</span><span>${v}</span></div>`
			)
			.join("");

		const chats =
			d.chats
				.map(
					(c) => `
				<div class="wap-chat">
					${E.number(c.number, { size: 28 })}
					<div class="wap-chat-main text-muted">${esc(
						erpnext.chat_render.preview_text({ content_type: c.content_type, text: c.preview })
					)}</div>
					<span class="text-muted wap-small">${
						c.last_message_on ? frappe.datetime.comment_when(c.last_message_on) : ""
					}</span>
					${
						c.page
							? `<a class="btn btn-xs btn-default" href="${esc(
									E.url([c.page])
							  )}?chat=${encodeURIComponent(c.chat)}"><i class="fa fa-comments"></i> ${__(
									"Open chat"
							  )}</a>`
							: `<span class="text-muted wap-small">${__("not followed")}</span>`
					}
				</div>`
				)
				.join("") || `<div class="text-muted">${__("No chats")}</div>`;

		const links =
			E.list(
				d.links,
				(l) =>
					E.html({
						name: l.name,
						sub: __(l.doctype),
						key: l.doctype + l.name,
						icon: "fa fa-file-text-o",
						route: ["Form", l.doctype, l.name],
						size: 28,
					}),
				{}
			) || "";

		const edit = d.can_edit && d.has_custom_fields;
		this.$body.html(`
			<div class="wap-hero">
				${E.avatar_html({ name: d.name, key: d.phone, image: d.image }, 96)}
				<div class="wap-hero-main">
					<div class="wap-name">${esc(d.name)}</div>
					<div class="wap-phone">+${esc(d.phone)}</div>
					${
						d.custom_name && d.whatsapp_name && d.whatsapp_name !== d.custom_name
							? `<div class="text-muted wap-small">${__("In WhatsApp: {0}", [
									esc(d.whatsapp_name),
							  ])}</div>`
							: ""
					}
				</div>
				${
					edit
						? `<div class="wap-actions">
					<button class="btn btn-sm btn-default wap-rename"><i class="fa fa-pencil"></i> ${__("Rename")}</button>
					<button class="btn btn-sm btn-default wap-photo"><i class="fa fa-camera"></i> ${__("Change photo")}</button>
					${
						d.custom_name || d.image
							? `<button class="btn btn-sm btn-default wap-reset"><i class="fa fa-undo"></i> ${__(
									"Reset to WhatsApp"
							  )}</button>`
							: ""
					}
				</div>`
						: ""
				}
			</div>
			<div class="wap-grid">
				<div class="wap-panel"><h6>${__("Details")}</h6>${facts}</div>
				<div class="wap-panel"><h6>${__("Chats")}</h6>${chats}</div>
				<div class="wap-panel"><h6>${__("Linked Documents")}</h6><div class="wap-links">${links}</div></div>
			</div>
		`);
	}

	bind() {
		this.$body.on("click", ".wap-rename", () => {
			frappe.prompt(
				[
					{
						fieldname: "name",
						fieldtype: "Data",
						label: __("Name"),
						default: this.data.custom_name || this.data.name,
						description: __("Leave empty to use the name from WhatsApp"),
					},
				],
				(v) => this.call("rename", { name: v.name || "" }),
				__("Rename"),
				__("Save")
			);
		});
		this.$body.on("click", ".wap-photo", () => {
			new frappe.ui.FileUploader({
				allow_multiple: false,
				make_attachments_public: false,
				restrictions: { allowed_file_types: ["image/*"] },
				on_success: (file) => this.call("set_image", { file_url: file.file_url }),
			});
		});
		this.$body.on("click", ".wap-reset", () => {
			frappe.confirm(__("Use the name from WhatsApp and drop the custom photo?"), () =>
				this.call("reset")
			);
		});
	}
}
