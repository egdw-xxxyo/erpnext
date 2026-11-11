// Виконавчий документ: що утримувати з офіційних виплат і кому перераховувати.

frappe.ui.form.on("Enforcement Order", {
	refresh(frm) {
		const colors = { Active: "green", Suspended: "orange", Closed: "gray" };
		frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");

		if (frm.is_new() || !flt(frm.doc.to_transfer)) return;

		frm.add_custom_button(__("Transfer to Recipient"), () => {
			frappe.prompt(
				[
					{
						fieldtype: "HTML",
						fieldname: "details",
						options: `<p>${__("{0} to {1}, IBAN {2}.", [
							format_currency(frm.doc.to_transfer, frappe.defaults.get_default("currency")),
							frappe.utils.escape_html(frm.doc.recipient_name),
							frappe.utils.escape_html(frm.doc.recipient_iban),
						])}</p>`,
					},
					{
						fieldname: "posting_date",
						fieldtype: "Date",
						label: __("Payment Date"),
						default: frappe.datetime.get_today(),
						reqd: 1,
					},
				],
				(values) =>
					frm
						.call({ doc: frm.doc, method: "transfer", args: values, freeze: true })
						.then(() => frm.reload_doc()),
				__("Transfer to Recipient"),
				__("Post")
			);
		});
	},
});
