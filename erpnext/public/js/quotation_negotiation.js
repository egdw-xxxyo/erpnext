// Quotation negotiation helpers: record a curated negotiation step (a Quotation
// Version with a reason/summary) and jump to the version history.

frappe.ui.form.on("Quotation", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(
			__("Record Negotiation Step"),
			() => {
				frappe.prompt(
					[
						{
							fieldname: "change_reason",
							fieldtype: "Small Text",
							label: __("Change Reason"),
						},
						{
							fieldname: "change_summary",
							fieldtype: "Small Text",
							label: __("Change Summary"),
						},
					],
					async (v) => {
						const name = await frappe.xcall(
							"erpnext.selling.doctype.quotation_version.quotation_version.create_manual_version",
							{
								quotation: frm.doc.name,
								change_reason: v.change_reason,
								change_summary: v.change_summary,
							}
						);
						if (name) {
							frappe.show_alert({
								message: __("Negotiation step recorded"),
								indicator: "green",
							});
						}
					},
					__("Record Negotiation Step"),
					__("Record")
				);
			},
			__("Negotiation")
		);

		frm.add_custom_button(
			__("Version History"),
			() => {
				frappe.set_route("List", "Quotation Version", { quotation: frm.doc.name });
			},
			__("Negotiation")
		);
	},
});
