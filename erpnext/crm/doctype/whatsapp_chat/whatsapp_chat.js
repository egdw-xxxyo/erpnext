// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("WhatsApp Chat", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Open Chat"), () => {
			window.location.href = `/app/whatsapp-chat-center?phone=${encodeURIComponent(frm.doc.phone)}`;
		}).addClass("btn-primary");
	},
});
