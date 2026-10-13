frappe.ui.form.on("Notification Settings", {
	refresh(frm) {
		if (frm.is_new() || frm.is_dirty()) return;
		if (!frm.doc.callmebot_enabled || !frm.doc.callmebot_phone || !frm.doc.callmebot_api_key) return;

		show_callmebot_status(frm);

		frm.add_custom_button(
			__("Send test message"),
			() => {
				frappe.call({
					method: "erpnext.erpnext_integrations.callmebot.send_test_message",
					args: { user: frm.doc.name },
					freeze: true,
					freeze_message: __("Sending test message..."),
					callback(r) {
						if (!r.message) return;
						frappe.msgprint({
							title: __("CallMeBot"),
							message: r.message.message,
							indicator: r.message.ok ? "green" : "red",
						});
						frm.reload_doc();
					},
				});
			},
			__("CallMeBot")
		);
	},
});

function show_callmebot_status(frm) {
	if (!["Paused", "Invalid API Key"].includes(frm.doc.callmebot_status)) return;

	frappe.call({
		method: "erpnext.erpnext_integrations.callmebot.get_status_help",
		args: { user: frm.doc.name },
		callback(r) {
			const help = r.message;
			if (!help?.message) return;
			let html = frappe.utils.escape_html(help.message);
			if (help.help_url) {
				const url = frappe.utils.escape_html(help.help_url);
				const label = __("How to restore WhatsApp notifications");
				html += ` <a href="${url}" target="_blank" rel="noopener">${label}</a>`;
			}
			frm.set_intro(html, "red");
		},
	});
}
