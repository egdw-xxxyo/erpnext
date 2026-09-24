frappe.ui.form.on("Lead", {
	setup: function (frm) {
		frm.set_query("utm_medium", () => ({
			filters: frm.doc.utm_source ? { engagement_channel: frm.doc.utm_source } : {},
		}));
	},

	utm_source: function (frm) {
		if (!frm.doc.utm_medium) return;

		frappe.db.get_value("UTM Medium", frm.doc.utm_medium, "engagement_channel").then(({ message }) => {
			if (message?.engagement_channel && message.engagement_channel !== frm.doc.utm_source) {
				frm.set_value("utm_medium", null);
			}
		});
	},
});
