frappe.provide("erpnext.sensitive_data");

erpnext.sensitive_data = Object.assign(erpnext.sensitive_data, {
	METHOD: "erpnext.access_control.sensitive",
	UNTIL_HEADER: "X-Sensitive-Until",
	state: { dialog: null, until: null, timer: null },

	status: () => frappe.boot.sensitive_data || {},

	update_status(status) {
		frappe.boot.sensitive_data = { ...erpnext.sensitive_data.status(), ...status };
		erpnext.sensitive_data.set_until(status.until);
	},

	set_until(until) {
		const state = erpnext.sensitive_data.state;
		state.until = until ? until * 1000 : null;
		clearTimeout(state.timer);
		if (state.until) {
			state.timer = setTimeout(
				() => erpnext.sensitive_data.set_until(null),
				Math.max(state.until - Date.now(), 0)
			);
		}
		erpnext.sensitive_data.render_indicator();
	},

	render_indicator() {
		const until = erpnext.sensitive_data.state.until;
		$(".sensitive-unlocked").remove();
		if (!until) return;
		const time = moment(until).format("HH:mm");
		$(`<div class="sensitive-unlocked">
			<i class="fa fa-unlock-alt"></i>
			<span>${__("Protected data is open until {0}", [time])}</span>
			<a class="sensitive-lock-now"><i class="fa fa-lock"></i> ${__("Lock now")}</a>
		</div>`)
			.appendTo("body")
			.find(".sensitive-lock-now")
			.on("click", () => erpnext.sensitive_data.lock());
	},

	on_protected_route() {
		const [view, name] = frappe.get_route();
		const objects = erpnext.sensitive_data.status().objects || {};
		if (view === "query-report") return (objects.reports || []).includes(name);
		return (objects.doctypes || []).includes(name) || (objects.pages || []).includes(view);
	},

	lock() {
		const leave = erpnext.sensitive_data.on_protected_route();
		return frappe
			.xcall(`${erpnext.sensitive_data.METHOD}.lock`)
			.then(() => (leave ? window.location.assign("/desk") : window.location.reload()));
	},

	after_unlock(status, retry) {
		erpnext.sensitive_data.update_status(status);
		erpnext.sensitive_data.close();
		if (retry === "reload") {
			window.location.reload();
			return;
		}
		frappe.show_alert(
			{ message: __("Protected data is open. Repeat the action"), indicator: "green" },
			7
		);
	},

	close() {
		const state = erpnext.sensitive_data.state;
		if (state.dialog) state.dialog.hide();
		state.dialog = null;
	},

	drop_msgprint() {
		const dialog = frappe.msg_dialog;
		if (!dialog) return;
		const modal = dialog.$wrapper.data("bs.modal");
		dialog.custom_onhide = null;
		if (modal && modal._isShown && !dialog.$wrapper.is(":visible")) {
			dialog.$wrapper.one("shown.bs.modal", () => frappe.hide_msgprint(true));
			return;
		}
		frappe.hide_msgprint(true);
	},

	prompt(retry) {
		const state = erpnext.sensitive_data.state;
		if (state.dialog && state.dialog.display) return;
		erpnext.sensitive_data.drop_msgprint();
		frappe.xcall(`${erpnext.sensitive_data.METHOD}.get_status`).then((status) => {
			erpnext.sensitive_data.drop_msgprint();
			erpnext.sensitive_data.update_status(status);
			if (status.until) {
				erpnext.sensitive_data.after_unlock(status, retry);
			} else if (status.blocked) {
				erpnext.sensitive_data.blocked_dialog(status, retry);
			} else if (!status.has_pin) {
				erpnext.sensitive_data.setup_dialog(status, retry);
			} else {
				erpnext.sensitive_data.unlock_dialog(status, retry);
			}
		});
	},

	show(dialog) {
		erpnext.sensitive_data.state.dialog = dialog;
		erpnext.sensitive_data.quiet_passwords(dialog);
		dialog.show();
		return dialog;
	},

	quiet_passwords(group) {
		Object.values(group.fields_dict)
			.filter((control) => control.df.fieldtype === "Password")
			.forEach((control) => control.disable_password_checks());
	},

	intro(text) {
		return `<p class="text-muted">${text}</p>`;
	},

	pin_field(fieldname, label) {
		return { fieldtype: "Password", fieldname, label, reqd: 1, length: 6 };
	},

	forgot_html() {
		return `<a class="sensitive-forgot small">${__("Forgot your PIN?")}</a>`;
	},

	duration_text(status) {
		return status.idle_minutes
			? __("The data stays open for {0} minutes, or until {1} minutes pass without opening it.", [
					status.unlock_minutes,
					status.idle_minutes,
			  ])
			: __("The data stays open for {0} minutes.", [status.unlock_minutes]);
	},

	unlock_dialog(status, retry) {
		const dialog = new frappe.ui.Dialog({
			title: __("Enter PIN"),
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "intro",
					options: erpnext.sensitive_data.intro(
						__("This data is protected by your personal PIN.") +
							" " +
							erpnext.sensitive_data.duration_text(status)
					),
				},
				erpnext.sensitive_data.pin_field("pin", __("PIN")),
				{ fieldtype: "HTML", fieldname: "error" },
				{
					fieldtype: "HTML",
					fieldname: "forgot",
					options: erpnext.sensitive_data.forgot_html(),
				},
			],
			primary_action_label: __("Unlock"),
			primary_action: ({ pin }) =>
				frappe.xcall(`${erpnext.sensitive_data.METHOD}.unlock`, { pin }).then((result) => {
					if (!result.refusal) {
						erpnext.sensitive_data.after_unlock(result, retry);
						return;
					}
					if (result.refusal === "blocked") {
						erpnext.sensitive_data.close();
						erpnext.sensitive_data.blocked_dialog(result, retry);
						return;
					}
					dialog.set_value("pin", "");
					dialog.fields_dict.error.$wrapper.html(
						`<div class="alert alert-danger">${frappe.utils.escape_html(result.message)}</div>`
					);
				}),
		});
		dialog.fields_dict.forgot.$wrapper
			.find(".sensitive-forgot")
			.on("click", () => erpnext.sensitive_data.reset_dialog(retry));
		erpnext.sensitive_data.show(dialog);
		dialog.$wrapper.on("shown.bs.modal", () => dialog.get_field("pin").$input.focus());
	},

	setup_dialog(status, retry) {
		erpnext.sensitive_data.password_dialog(
			__("Create a PIN"),
			__(
				"Protected data opens only after your personal PIN, so nobody can read it at your computer while you are away."
			) +
				" " +
				__("Choose 6 digits that only you know."),
			retry
		);
	},

	reset_dialog(retry) {
		erpnext.sensitive_data.close();
		frappe.hide_msgprint(true);
		erpnext.sensitive_data.password_dialog(
			__("Reset PIN"),
			__(
				"Confirm it is you with your login password and choose a new PIN. Access Managers will be notified."
			),
			retry
		);
	},

	password_dialog(title, intro, retry) {
		const dialog = new frappe.ui.Dialog({
			title,
			fields: [
				{ fieldtype: "HTML", fieldname: "intro", options: erpnext.sensitive_data.intro(intro) },
				{
					fieldtype: "Password",
					fieldname: "password",
					label: __("Your login password"),
					reqd: 1,
				},
				erpnext.sensitive_data.pin_field("pin", __("New PIN")),
				erpnext.sensitive_data.pin_field("confirm", __("Repeat PIN")),
			],
			primary_action_label: __("Save PIN"),
			primary_action: (values) =>
				frappe
					.xcall(`${erpnext.sensitive_data.METHOD}.set_pin`, values)
					.then((result) => erpnext.sensitive_data.after_unlock(result, retry)),
		});
		erpnext.sensitive_data.show(dialog);
	},

	blocked_dialog(status, retry) {
		frappe.msgprint({
			title: __("PIN is blocked"),
			indicator: "red",
			message: __(
				"Your PIN is blocked after too many wrong attempts. Set a new one with your login password."
			),
			primary_action: {
				label: __("Reset PIN"),
				action: () => erpnext.sensitive_data.reset_dialog(retry),
			},
		});
	},

	change_dialog() {
		const dialog = new frappe.ui.Dialog({
			title: __("Change PIN"),
			fields: [
				erpnext.sensitive_data.pin_field("current_pin", __("Current PIN")),
				erpnext.sensitive_data.pin_field("pin", __("New PIN")),
				erpnext.sensitive_data.pin_field("confirm", __("Repeat PIN")),
				{ fieldtype: "HTML", fieldname: "error" },
				{ fieldtype: "HTML", fieldname: "forgot", options: erpnext.sensitive_data.forgot_html() },
			],
			primary_action_label: __("Save PIN"),
			primary_action: (values) =>
				frappe.xcall(`${erpnext.sensitive_data.METHOD}.change_pin`, values).then((result) => {
					if (!result.refusal) {
						erpnext.sensitive_data.update_status(result);
						erpnext.sensitive_data.close();
						frappe.show_alert({ message: __("PIN changed"), indicator: "green" });
						return;
					}
					dialog.fields_dict.error.$wrapper.html(
						`<div class="alert alert-danger">${frappe.utils.escape_html(result.message)}</div>`
					);
				}),
		});
		dialog.fields_dict.forgot.$wrapper
			.find(".sensitive-forgot")
			.on("click", () => erpnext.sensitive_data.reset_dialog());
		erpnext.sensitive_data.show(dialog);
	},

	masked_here(frm) {
		const fields = (erpnext.sensitive_data.status().fields || {})[frm.doctype] || [];
		const masked = frappe.get_meta(frm.doctype).masked_fields || [];
		return fields.filter((fieldname) => masked.includes(fieldname));
	},

	show_masked_hint(frm) {
		const fields = frm && !frm.is_new() ? erpnext.sensitive_data.masked_here(frm) : [];
		if (!fields.length) return;
		const labels = fields.map((fieldname) => __(frappe.meta.get_label(frm.doctype, fieldname)));
		frm.dashboard.add_comment(
			`<i class="fa fa-lock"></i> ${__("Protected fields are hidden: {0}.", [
				frappe.utils.escape_html(labels.join(", ")),
			])}
			<a class="sensitive-hint-unlock">${__("Enter PIN to show them")}</a>`,
			"orange",
			true
		);
	},

	read_header(xhr) {
		const until =
			xhr && xhr.getResponseHeader && xhr.getResponseHeader(erpnext.sensitive_data.UNTIL_HEADER);
		if (until) erpnext.sensitive_data.set_until(parseInt(until, 10));
	},

	install() {
		frappe.request.on_error("SensitiveDataLocked", (r) =>
			erpnext.sensitive_data.prompt((r._sensitive_locked || {}).retry)
		);
		$(document).ajaxComplete((event, xhr) => erpnext.sensitive_data.read_header(xhr));
		$(document).on("form-refresh", (event, frm) => erpnext.sensitive_data.show_masked_hint(frm));
		$(document).on("click", ".sensitive-hint-unlock", () => erpnext.sensitive_data.prompt("reload"));
		$(document).on("app_ready", () =>
			erpnext.sensitive_data.set_until(erpnext.sensitive_data.status().until)
		);
		$("<style>")
			.text(
				`.sensitive-unlocked { position: fixed; left: 50%; transform: translateX(-50%); bottom: 16px; z-index: 1030;
					display: flex; gap: 8px; align-items: center; padding: 6px 12px;
					border-radius: var(--border-radius-full); background: var(--bg-orange);
					color: var(--text-on-orange); font-size: var(--text-sm); box-shadow: var(--shadow-sm); }
				.sensitive-unlocked a { color: inherit; font-weight: 600; cursor: pointer; }
				.sensitive-forgot, .sensitive-hint-unlock { cursor: pointer; font-weight: 600; }`
			)
			.appendTo("head");
	},
});

erpnext.sensitive_data.install();
