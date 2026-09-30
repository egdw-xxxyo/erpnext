frappe.pages["whatsapp-access"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("WhatsApp Access"),
		single_column: true,
	});
	wrapper.whatsapp_access = new WhatsAppAccess(page);
};

const WAA_METHOD = "erpnext.crm.page.whatsapp_access.whatsapp_access";
const WAA_LEVELS = [
	["", "—"],
	["Responsible", "Responsible"],
	["Spectator", "Spectator"],
];

class WhatsAppAccess {
	constructor(page) {
		this.page = page;
		this.data = null;
		this.changes = {};
		this.filter = "";
		this.make();
		this.load();
	}

	make() {
		this.page.set_primary_action(__("Save"), () => this.save(), "check");
		this.page.add_inner_button(__("Add User"), () => this.add_user());
		this.page.add_inner_button(__("WhatsApp Overview"), () => frappe.set_route("whatsapp-overview"));
		this.page.add_inner_button(__("Working Hours"), () =>
			frappe.set_route("Form", "WhatsApp Chat Settings")
		);
		this.search = this.page.add_field({
			fieldname: "search",
			fieldtype: "Data",
			label: __("Search"),
			placeholder: __("Search"),
			change: () => {
				this.filter = (this.search.get_value() || "").trim().toLowerCase();
				this.render();
			},
		});
		this.search.$input.on(
			"input",
			frappe.utils.debounce(() => this.search.$input.trigger("change"), 250)
		);
		this.page.main.html(`
			<div class="whatsapp-access">
				<div class="waa-help text-muted">
					<div><b>${__("Responsible")}</b> — ${__("sees the chats of the number and answers them")}</div>
					<div><b>${__("Spectator")}</b> — ${__("sees the chats of the number read-only")}</div>
					<div>${__("System Managers see and answer every number without an assignment.")}</div>
				</div>
				<div class="waa-body"></div>
			</div>
		`);
		this.$body = this.page.main.find(".waa-body");
		this.$body.on("change", ".waa-select", (e) => {
			const $s = $(e.currentTarget);
			const key = `${$s.data("user")}::${$s.data("account")}`;
			const value = $s.val() || "";
			if ((this.data.access[key] || "") === value) delete this.changes[key];
			else this.changes[key] = value;
			$s.toggleClass("waa-changed", key in this.changes);
			this.update_dirty();
		});
		this.inject_styles();
	}

	inject_styles() {
		if (document.getElementById("waa-styles")) return;
		$(`<style id="waa-styles">
			.whatsapp-access{padding:4px 0 40px;}
			.whatsapp-access .waa-help{font-size:12px;margin-bottom:14px;display:flex;flex-direction:column;gap:2px;}
			.whatsapp-access .waa-table{background:var(--card-bg);font-size:13px;}
			.whatsapp-access .waa-table th{font-weight:500;vertical-align:bottom;}
			.whatsapp-access .waa-table th .waa-num{font-weight:600;color:var(--text-color);white-space:nowrap;}
			.whatsapp-access .waa-table th .fa-whatsapp{color:#25d366;margin-right:4px;}
			.whatsapp-access .waa-user{white-space:nowrap;}
			.whatsapp-access .waa-select{min-width:140px;}
			.whatsapp-access .waa-select.waa-changed{border-color:var(--primary);box-shadow:0 0 0 1px var(--primary);}
			.whatsapp-access .waa-admin{font-size:11px;}
			.whatsapp-access .waa-wrap{overflow-x:auto;}
		</style>`).appendTo(document.head);
	}

	load() {
		return frappe.xcall(`${WAA_METHOD}.get_matrix`).then((data) => this.set_data(data));
	}

	set_data(data) {
		this.data = data;
		this.changes = {};
		this.update_dirty();
		this.render();
	}

	update_dirty() {
		const n = Object.keys(this.changes).length;
		this.page.set_indicator(n ? __("{0} unsaved changes", [n]) : "", n ? "orange" : "");
	}

	render() {
		const d = this.data;
		if (!d) return;
		if (!d.installed) {
			this.$body.html(
				`<div class="text-muted">${__("The WhatsApp app is not installed on this site.")}</div>`
			);
			return;
		}
		if (!d.accounts.length) {
			this.$body.html(`<div class="text-muted">${__("No WhatsApp numbers yet")}</div>`);
			return;
		}
		const esc = frappe.utils.escape_html;
		const users = d.users.filter(
			(u) => !this.filter || `${u.full_name || ""} ${u.name}`.toLowerCase().includes(this.filter)
		);
		const head = d.accounts
			.map(
				(a) => `<th><div class="waa-num"><i class="fa fa-whatsapp"></i>${esc(a.label)}</div>
					<div class="text-muted">${esc(a.verified_name || a.account_name || a.name)}</div></th>`
			)
			.join("");
		const body = users
			.map((u) => {
				const cells = d.accounts
					.map((a) => {
						const key = `${u.name}::${a.name}`;
						const value = key in this.changes ? this.changes[key] : d.access[key] || "";
						const options = WAA_LEVELS.map(
							([v, label]) =>
								`<option value="${v}" ${v === value ? "selected" : ""}>${esc(
									__(label)
								)}</option>`
						).join("");
						return `<td><select class="form-control input-xs waa-select ${
							key in this.changes ? "waa-changed" : ""
						}" data-user="${esc(u.name)}" data-account="${esc(a.name)}">${options}</select></td>`;
					})
					.join("");
				return `<tr>
					<td class="waa-user"><div>${esc(u.full_name || u.name)}</div>
						<div class="text-muted waa-admin">${esc(u.name)}${
					u.is_admin ? ` · ${__("System Manager — sees every number")}` : ""
				}</div></td>
					${cells}
				</tr>`;
			})
			.join("");
		this.$body.html(`
			<div class="waa-wrap"><table class="table table-bordered waa-table">
				<thead><tr><th>${__("User")}</th>${head}</tr></thead>
				<tbody>${
					body ||
					`<tr><td colspan="${d.accounts.length + 1}" class="text-muted">${__(
						"No users with the WhatsApp User role yet — use Add User"
					)}</td></tr>`
				}</tbody>
			</table></div>
		`);
	}

	save() {
		const changes = Object.entries(this.changes).map(([key, access]) => {
			const [user, whatsapp_account] = key.split("::");
			return { user, whatsapp_account, access };
		});
		if (!changes.length) {
			frappe.show_alert({ message: __("Nothing to save"), indicator: "gray" });
			return;
		}
		frappe.xcall(`${WAA_METHOD}.save_access`, { changes: JSON.stringify(changes) }).then((data) => {
			this.set_data(data);
			frappe.show_alert({ message: __("Saved"), indicator: "green" });
		});
	}

	add_user() {
		frappe.prompt(
			[
				{
					fieldname: "user",
					fieldtype: "Link",
					options: "User",
					label: __("User"),
					reqd: 1,
					get_query: () => ({ filters: { enabled: 1, user_type: "System User" } }),
				},
			],
			({ user }) =>
				frappe.xcall(`${WAA_METHOD}.add_user`, { user }).then((data) => {
					const pending = this.changes;
					this.set_data(data);
					this.changes = pending;
					this.update_dirty();
					this.render();
				}),
			__("Add User"),
			__("Add")
		);
	}
}
