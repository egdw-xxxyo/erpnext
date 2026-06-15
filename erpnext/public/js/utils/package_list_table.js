/**
 * Reusable Package list table renderer.
 *
 * Usage:
 *   erpnext.utils.render_package_list_table({
 *       wrapper: $element,
 *       filters: { pallet: frm.doc.name },
 *       empty_message: __("No packages linked."),
 *   });
 */

frappe.provide("erpnext.utils");

erpnext.utils.render_package_list_table = function (opts) {
	const wrapper = opts.wrapper instanceof jQuery ? opts.wrapper : $(opts.wrapper);
	if (!wrapper || !wrapper.length) return;

	wrapper.empty();

	frappe.db
		.get_list("Package", {
			filters: opts.filters || {},
			fields: [
				"name",
				"status",
				"box_template",
				"bpak",
				"gross_weight",
				"sales_order",
				"shipment",
			],
			order_by: "creation asc",
			limit: 0,
		})
		.then((rows) => {
			if (!rows || !rows.length) {
				wrapper.html(
					`<p class="text-muted">${frappe.utils.escape_html(
						opts.empty_message || __("No packages found.")
					)}</p>`
				);
				return;
			}

			const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
			const link = (dt, name) =>
				name
					? `<a href="/app/${dt}/${encodeURIComponent(name)}">${esc(name)}</a>`
					: "";

			let html = `<table class="table table-bordered">
				<thead><tr>
					<th>${__("Package")}</th>
					<th>${__("Status")}</th>
					<th>${__("Box Type")}</th>
					<th>${__("BpAK")}</th>
					<th>${__("Sales Order")}</th>
					<th>${__("Shipment")}</th>
					<th class="text-right">${__("Gross Weight (kg)")}</th>
				</tr></thead><tbody>`;

			rows.forEach((r) => {
				html += `<tr>
					<td>${link("package", r.name)}</td>
					<td>${esc(r.status)}</td>
					<td>${esc(r.box_template)}</td>
					<td>${link("bpak", r.bpak)}</td>
					<td>${link("sales-order", r.sales_order)}</td>
					<td>${link("shipment", r.shipment)}</td>
					<td class="text-right">${esc(r.gross_weight || 0)}</td>
				</tr>`;
			});
			html += "</tbody></table>";
			wrapper.html(html);
		});
};
