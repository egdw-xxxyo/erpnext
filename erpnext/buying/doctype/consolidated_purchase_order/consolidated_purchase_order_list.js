frappe.listview_settings["Consolidated Purchase Order"] = {
	add_fields: ["payment_receipts_progress", "payment_receipt_count", "payment_invoice_count"],
	onload(listview) {
		erpnext.buying.apply_procurement_work_queue_filters(listview, {
			participants_field: "procurement_participants",
			completion_field: "procurement_completion_status",
		});
	},
	formatters: {
		payment_receipts_progress(value, df, doc) {
			const paid = Math.max(0, cint(doc.payment_receipt_count));
			const total = Math.max(0, cint(doc.payment_invoice_count));
			const percent = total ? Math.min(100, (paid / total) * 100) : 0;
			const progress = `${paid}/${total}`;
			return `<div title="${__("Payment")}: ${frappe.utils.escape_html(
				progress
			)}" style="display:inline-flex;align-items:center;width:96px;min-width:96px;text-align:left">
				<div style="position:relative;height:18px;width:96px;border-radius:999px;background:var(--subtle-fg);overflow:hidden">
					<div style="height:100%;width:${percent}%;background:var(--green-500);border-radius:999px"></div>
					<span style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;white-space:nowrap;color:var(--text-color);font-size:var(--text-xs);font-weight:500;font-variant-numeric:tabular-nums">${frappe.utils.escape_html(
						progress
					)}</span>
				</div>
			</div>`;
		},
	},
};
