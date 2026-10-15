frappe.ui.form.on("Supplier", {
	refresh: render_supplier_accounting_stats,
	custom_is_vat_payer: render_supplier_accounting_stats,
});

function render_supplier_accounting_stats(frm) {
	const host = frm.fields_dict.accounting_statistics_html?.$wrapper;
	if (!host) return;
	// Move the existing indicators themselves; retain their native refresh behaviour.
	frm.dashboard.stats_area.wrapper.appendTo(host);
	frm.dashboard.stats_area.collapse(false);
	frm.dashboard.stats_area.head?.hide();
	if (frm.is_new()) return;
	const token = (frm.__paid_vat_request || 0) + 1;
	frm.__paid_vat_request = token;
	frappe.call({
		method: "erpnext.accounts.supplier_vat_display.get_supplier_paid_vat",
		args: { supplier: frm.doc.name },
		callback(response) {
			if (token !== frm.__paid_vat_request) return;
			host.find(".supplier-paid-vat").remove();
			const data = response.message;
			if (!data || data.visible === false) return;
			const block = $('<div class="supplier-paid-vat" style="padding:15px"></div>').appendTo(host);
			$("<strong></strong>").text(__("Paid VAT")).appendTo(block);
			if (!data.groups.length) {
				$("<div></div>")
					.text(data.payer ? "0.00" : "—")
					.appendTo(block);
			}
			for (const group of data.groups) {
				const line = $("<div></div>").appendTo(block);
				if (data.groups.length > 1) {
					line.append(
						erpnext.entity.html({
							name: group.company,
							route: ["Form", "Company", group.company],
						})
					);
				}
				$("<span></span>").text(format_currency(group.vat, group.currency)).appendTo(line);
			}
		},
	});
}
