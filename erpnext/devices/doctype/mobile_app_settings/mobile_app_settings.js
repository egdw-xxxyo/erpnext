// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Mobile App Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Check GitHub Now"), () => poll_now(frm));
		show_version_gap(frm);
	},
});

// `required_android_version` is written on every migrate from the version this server build
// was shipped with; the published APK comes from the GitHub mirror, which can fail on its
// own. When the two disagree, benches are stuck on a build the server no longer supports and
// nothing else on the site says so.
function show_version_gap(frm) {
	frappe.call({
		method: "erpnext.devices.app_version.android_version_status",
		callback(r) {
			const status = r.message || {};
			if (!status.required || status.ok) {
				frm.dashboard.clear_headline();
				return;
			}
			const message =
				status.state === "missing"
					? __("No Android APK is published on this site. This server needs {0}.", [
							status.required,
					  ])
					: __("Published Android app is {0}, but this server needs {1}.", [
							status.available,
							status.required,
					  ]);
			frm.dashboard.set_headline(
				`<span class="text-danger">${frappe.utils.icon("solid-warning", "sm")} ${message}</span>`
			);
		},
	});
}

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
