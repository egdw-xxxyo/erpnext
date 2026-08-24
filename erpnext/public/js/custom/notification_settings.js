frappe.ui.form.on("Notification Settings", {
	refresh(frm) {
		if (frm.is_new() || frm.is_dirty()) return;
		if (!frm.doc.callmebot_enabled || !frm.doc.callmebot_phone || !frm.doc.callmebot_api_key) return;

		frm.add_custom_button(
			__("Send test message"),
			() => {
				frappe.call({
					method: "erpnext.erpnext_integrations.callmebot.send_test_message",
					args: { user: frm.doc.name },
					freeze: true,
					freeze_message: __("Sending test message..."),
					callback(r) {
						if (r.message) {
							frappe.msgprint({
								title: __("CallMeBot"),
								message: r.message,
								indicator: "green",
							});
						}
					},
				});
			},
			__("CallMeBot")
		);
	},
});
