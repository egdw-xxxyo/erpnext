// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// The button is offered by comparing the document's pointer with this revision rather
// than by reading the revision's own status, so the client never carries a copy of the
// status vocabulary the server owns.

const FILE_FIELDS = ["word_file", "pdf_file", "signed_scan", "additional_attachment"];

function lock_filled_files(frm) {
	const submitted = frm.doc.docstatus === 1;
	FILE_FIELDS.forEach((fieldname) =>
		frm.set_df_property(fieldname, "read_only", submitted && !!frm.doc[fieldname] ? 1 : 0)
	);
}

frappe.ui.form.on("Technical Document Revision", {
	async refresh(frm) {
		lock_filled_files(frm);
		if (frm.doc.docstatus !== 1) return;

		const { message } = await frappe.db.get_value(
			"Technical Document",
			frm.doc.technical_document,
			"current_revision"
		);
		if (message && message.current_revision === frm.doc.name) {
			frm.dashboard.add_indicator(__("Current version"), "green");
			return;
		}

		frm.add_custom_button(__("Make Effective"), () => confirm_make_effective(frm));
	},
});

function confirm_make_effective(frm) {
	frappe.confirm(
		__(
			"Revision {0} becomes the one in force, and the revision in force until now becomes superseded. Continue?",
			[frm.doc.revision_number]
		),
		() =>
			frm
				.call({
					method: "erpnext.technical_documentation.doctype.technical_document_revision.technical_document_revision.make_effective",
					args: { revision: frm.doc.name },
					freeze: true,
					freeze_message: __("Putting the revision into force"),
				})
				.then(() => {
					frappe.show_alert({ message: __("Revision is now in force"), indicator: "green" });
					frm.reload_doc();
				})
	);
}
