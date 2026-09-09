// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Mobile App Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Check GitHub Now"), () => poll_now(frm));
	},
});

// The poll downloads the APK (tens of MB), so freeze the form rather than let the user
// click twice. Failures are recorded on the Single instead of raised, so the message
// comes from the returned document, not from an exception.
function poll_now(frm) {
	frappe.call({
		method: "erpnext.devices.doctype.mobile_app_settings.mobile_app_settings.poll_now",
		freeze: true,
		freeze_message: __("Checking GitHub for a new release..."),
		callback(r) {
			const result = r.message || {};
			frm.reload_doc();
			if (result.last_error) {
				frappe.msgprint({
					title: __("Poll failed"),
					message: result.last_error,
					indicator: "red",
				});
			} else if (result.latest_version) {
				frappe.show_alert({
					message: __("Latest release: {0}", [result.latest_version]),
					indicator: "green",
				});
			} else {
				frappe.show_alert(__("No release found"));
			}
		},
	});
}
