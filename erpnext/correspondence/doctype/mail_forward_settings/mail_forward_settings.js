frappe.ui.form.on("Mail Forward Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Sync Folders Now"), () =>
			frappe.call({
				method: "erpnext.correspondence.doctype.mail_forward_settings.mail_forward_settings.sync_folders_now",
				freeze: true,
				freeze_message: __("Reading folder lists from the mail servers…"),
				callback: ({ message }) => {
					const rows = (message || []).map(({ email_account, error, folders }) =>
						error
							? `<li><b>${frappe.utils.escape_html(email_account)}</b>: ${__(
									"failed, see the mailbox row"
							  )}</li>`
							: `<li><b>${frappe.utils.escape_html(email_account)}</b>: ${folders
									.map(frappe.utils.escape_html)
									.join(", ")}</li>`
					);
					frappe.msgprint({
						title: __("Folders"),
						message: rows.length
							? `<ul>${rows.join("")}</ul>`
							: __("No mailboxes with automatic folders"),
					});
					frm.reload_doc();
				},
			})
		);
	},
});
