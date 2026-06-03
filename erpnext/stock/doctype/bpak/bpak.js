// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("BpAK", {
	refresh(frm) {
		if (!frm.is_new() && frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Package"), () => {
				frappe.new_doc("Package", { bpak: frm.doc.name });
			}, __("Create"));
			frm.add_custom_button(__("View Packages"), () => {
				frappe.set_route("List", "Package", { bpak: frm.doc.name });
			});
		}
		render_packed_summary(frm);
	},
});

function render_packed_summary(frm) {
	let wrapper = frm.fields_dict.packed_summary_html
		&& frm.fields_dict.packed_summary_html.$wrapper;
	if (!wrapper) return;
	if (frm.is_new()) {
		wrapper.empty();
		return;
	}
	frappe.call({
		method: "erpnext.stock.doctype.bpak.bpak.get_packed_summary",
		args: { bpak_name: frm.doc.name },
		callback: function (r) {
			let d = r.message || { packages: [], packed_total: 0, planned_total: 0 };
			let html = "";
			if (!d.packages.length) {
				html += `<p class="text-muted">${__("No packages yet.")}</p>`;
			} else {
				html += `<table class="table table-bordered" style="margin-bottom:8px;">
					<thead><tr>
						<th>${__("Package")}</th>
						<th>${__("Status")}</th>
						<th>${__("Item")}</th>
						<th class="text-right">${__("Serial No / Qty")}</th>
					</tr></thead><tbody>`;
				d.packages.forEach((pkg) => {
					let items = pkg.items.length ? pkg.items : [{ item_code: "", item_name: "", qty: 0, serial_no: "" }];
					items.forEach((it, idx) => {
						html += "<tr>";
						if (idx === 0) {
							let pkg_link = `<a href="/app/package/${encodeURIComponent(pkg.name)}">${frappe.utils.escape_html(pkg.name)}</a>`;
							html += `<td rowspan="${items.length}">${pkg_link}</td>`;
							html += `<td rowspan="${items.length}">${frappe.utils.escape_html(pkg.status || "")}</td>`;
						}
						let item_label = it.item_code
							? `${frappe.utils.escape_html(it.item_code)}${it.item_name ? " — " + frappe.utils.escape_html(it.item_name) : ""}`
							: `<span class="text-muted">${__("(empty)")}</span>`;
						html += `<td>${item_label}</td>`;
						let right = it.serial_no
							? frappe.utils.escape_html(it.serial_no)
							: it.qty;
						html += `<td class="text-right">${right}</td>`;
						html += "</tr>";
					});
				});
				html += "</tbody></table>";
			}
			let pct = d.planned_total
				? Math.round((d.packed_total / d.planned_total) * 100)
				: 0;
			html += `<div><strong>${__("Packed {0} out of {1}", [d.packed_total, d.planned_total])}</strong>`;
			if (d.planned_total) html += ` <span class="text-muted">(${pct}%)</span>`;
			html += "</div>";
			wrapper.html(html);
		},
	});
}
