frappe.ui.form.on("Email Account", {
	refresh(frm) {
		const forwarding = frm.doc.__onload && frm.doc.__onload.mail_forwarding;
		if (!forwarding) return;
		frm.toggle_display(forwarding.hidden, false);
		frm.set_intro(
			forwarding.role === "Watched"
				? __(
						"This mailbox is watched for mail forwarding: it is read without marking mail as read, and settings that would change the mailbox or answer senders are set automatically and hidden."
				  )
				: __(
						"Mail forwarding sends its copies from this account: open tracking and unsubscribe links are turned off automatically and hidden."
				  ),
			"blue"
		);
		frm.add_custom_button(__("Mail Forward Settings"), () =>
			frappe.set_route("Form", "Mail Forward Settings")
		);
	},
});
