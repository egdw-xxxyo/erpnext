frappe.provide("erpnext");

erpnext.GlobalScanner = class GlobalScanner {
	constructor() {
		this.dialog = null;
	}

	mount_button() {
		if ($(".navbar .global-scanner-btn").length) return;
		const $search = $(".navbar .search-bar").first();
		if (!$search.length) return;

		const $btn = $(`
			<button type="button" class="btn btn-default btn-sm global-scanner-btn"
				title="${__("Scan barcode")} (Ctrl+Shift+B)"
				style="margin-left: 6px; display: inline-flex; align-items: center; padding: 4px 8px;">
				<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
					stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<path d="M3 5v14M7 5v14M11 5v14M15 5v14M19 5v14"/>
				</svg>
			</button>
		`);
		$btn.on("click", () => this.show());
		$search.after($btn);
	}

	show() {
		if (!this.dialog) this.dialog = this.build_dialog();
		this.dialog.show();
		setTimeout(() => {
			const $input = this.dialog.fields_dict.barcode.$input;
			$input.val("").focus();
			this.dialog.$wrapper.find(".scan-results").empty();
		}, 100);
	}

	build_dialog() {
		const dialog = new frappe.ui.Dialog({
			title: __("Scan barcode"),
			size: "large",
			fields: [
				{
					fieldtype: "Data",
					fieldname: "barcode",
					label: __("Barcode"),
					options: "Barcode",
					reqd: 1,
				},
				{ fieldtype: "HTML", fieldname: "results" },
			],
		});

		dialog.$wrapper.find('[data-fieldname="results"]').addClass("scan-results");

		const $input = dialog.fields_dict.barcode.$input;
		const handle = frappe.utils.debounce(() => {
			const value = ($input.val() || "").trim();
			if (!value) return;
			this.scan(value, dialog);
		}, 100);

		$input.on("change", handle);
		$input.on("keydown", (e) => {
			if (e.key === "Enter") {
				e.preventDefault();
				handle();
			}
		});

		return dialog;
	}

	async scan(barcode, dialog) {
		const $results = dialog.$wrapper.find(".scan-results");
		$results.html(`<div class="text-muted">${__("Searching...")}</div>`);
		try {
			const r = await frappe.call({
				method: "erpnext.stock.global_scan.global_scan",
				args: { barcode },
			});
			$results.empty().append(this.render(r.message || {}));
		} catch (e) {
			$results.html(
				`<div class="text-danger">${frappe.utils.escape_html(e.message || String(e))}</div>`
			);
		}
		setTimeout(() => {
			const $input = dialog.fields_dict.barcode.$input;
			$input.select();
		}, 50);
	}

	render(result) {
		const type = result.type;
		if (!type) {
			return $(`<div class="text-muted" style="padding: 12px;">
				${__("Not found")}: <code>${frappe.utils.escape_html(result.barcode || "")}</code>
			</div>`);
		}

		const renderers = {
			workplace: this.render_workplace,
			employee: this.render_employee,
			serial_no: this.render_serial_no,
			package: this.render_package,
			item: this.render_item,
			batch: this.render_batch,
			warehouse: this.render_warehouse,
		};
		const fn = renderers[type] || this.render_generic;
		return fn.call(this, result);
	}

	link(route, label) {
		const safe = frappe.utils.escape_html(label);
		return `<a href="${route}" target="_blank">${safe}</a>`;
	}

	doc_link(doctype, name) {
		if (!name) return "";
		const route = `/app/${frappe.router.slug(doctype)}/${encodeURIComponent(name)}`;
		return this.link(route, name);
	}

	card(title_html, body_html) {
		return $(`
			<div class="scanner-card" style="border:1px solid var(--border-color); border-radius:6px; padding:12px; margin-top:8px;">
				<div style="font-weight:600; font-size:14px; margin-bottom:8px;">${title_html}</div>
				<div>${body_html}</div>
			</div>
		`);
	}

	row(label, value_html) {
		if (!value_html) return "";
		return `<div style="display:flex; gap:8px; margin:2px 0;">
			<div style="min-width:140px; color:var(--text-muted);">${frappe.utils.escape_html(label)}</div>
			<div>${value_html}</div>
		</div>`;
	}

	render_workplace(r) {
		const d = r.doc;
		const title = `${__("Workplace")}: ${this.doc_link("Workplace", d.name)}`;
		const ops = (d.operations || [])
			.map((o) => `<span class="badge" style="margin-right:4px;">${frappe.utils.escape_html(o)}</span>`)
			.join("");
		const body = [
			this.row(__("Name"), frappe.utils.escape_html(d.workplace_name || "")),
			this.row(__("Company"), frappe.utils.escape_html(d.company || "")),
			d.description ? this.row(__("Description"), frappe.utils.escape_html(d.description)) : "",
			ops ? this.row(__("Operations"), ops) : "",
		].join("");
		return this.card(title, body);
	}

	render_employee(r) {
		const d = r.doc;
		const title = `${__("Employee")}: ${this.doc_link("Employee", d.name)}`;
		const body = [
			this.row(__("Name"), frappe.utils.escape_html(d.employee_name || "")),
			this.row(__("Designation"), frappe.utils.escape_html(d.designation || "")),
			this.row(__("Department"), d.department ? this.doc_link("Department", d.department) : ""),
			this.row(__("Company"), frappe.utils.escape_html(d.company || "")),
			this.row(__("Status"), frappe.utils.escape_html(d.status || "")),
		].join("");
		return this.card(title, body);
	}

	render_serial_no(r) {
		const d = r.doc;
		const title = `${__("Serial No")}: ${this.doc_link("Serial No", d.name)}`;
		const body = [
			this.row(
				__("Item"),
				d.item_code
					? this.doc_link("Item", d.item_code) +
							(d.item_name ? ` — ${frappe.utils.escape_html(d.item_name)}` : "")
					: ""
			),
			this.row(__("Batch"), d.batch_no ? this.doc_link("Batch", d.batch_no) : ""),
			this.row(__("Warehouse"), d.warehouse ? this.doc_link("Warehouse", d.warehouse) : ""),
			this.row(__("Status"), frappe.utils.escape_html(d.status || "")),
		].join("");
		const $card = this.card(title, body);

		if (r.additional_attributes && r.additional_attributes.length) {
			const attr_body = r.additional_attributes
				.map((a) => {
					const label = frappe.utils.escape_html(a.label || a.value || "");
					const notes = a.notes
						? ` <span class="text-muted">— ${frappe.utils.escape_html(a.notes)}</span>`
						: "";
					return this.row(a.attribute, label + notes);
				})
				.join("");
			$card.append(
				`<div style="margin-top:10px; padding-top:10px; border-top:1px dashed var(--border-color);"><div style="font-weight:600; margin-bottom:6px;">${__(
					"Additional Attributes"
				)}</div>${attr_body}</div>`
			);
		}

		if (r.purchase_receipt) {
			const pr = r.purchase_receipt;
			const pr_body = [
				this.row(__("Purchase Receipt"), this.doc_link("Purchase Receipt", pr.name)),
				this.row(
					__("Posting Date"),
					pr.posting_date ? frappe.format(pr.posting_date, { fieldtype: "Date" }) : ""
				),
				this.row(
					__("Supplier"),
					pr.supplier
						? this.doc_link("Supplier", pr.supplier) +
								(pr.supplier_name ? ` — ${frappe.utils.escape_html(pr.supplier_name)}` : "")
						: ""
				),
			].join("");
			$card.append(
				`<div style="margin-top:10px; padding-top:10px; border-top:1px dashed var(--border-color);"><div style="font-weight:600; margin-bottom:6px;">${__(
					"Origin"
				)}</div>${pr_body}</div>`
			);
		}

		if (r.quality_inspections && r.quality_inspections.length) {
			const rows = r.quality_inspections
				.map((q) => {
					return [
						this.row(__("Quality Inspection"), this.doc_link("Quality Inspection", q.name)),
						this.row(__("Status"), frappe.utils.escape_html(q.status || "")),
						this.row(__("Inspection Type"), frappe.utils.escape_html(q.inspection_type || "")),
						this.row(
							__("Report Date"),
							q.report_date ? frappe.format(q.report_date, { fieldtype: "Date" }) : ""
						),
					].join("");
				})
				.join('<hr style="border:0;border-top:1px dashed var(--border-color);margin:6px 0;">');
			$card.append(
				`<div style="margin-top:10px; padding-top:10px; border-top:1px dashed var(--border-color);"><div style="font-weight:600; margin-bottom:6px;">${__(
					"Quality Inspections"
				)}</div>${rows}</div>`
			);
		}

		if (r.package) {
			const p = r.package;
			const pkg_body = [
				this.row(__("Package"), this.doc_link("Package", p.name)),
				this.row(__("Status"), frappe.utils.escape_html(p.status || "")),
				this.row(
					__("Delivery Note"),
					p.delivery_note ? this.doc_link("Delivery Note", p.delivery_note) : ""
				),
				this.row(__("Sales Order"), p.sales_order ? this.doc_link("Sales Order", p.sales_order) : ""),
			].join("");
			$card.append(
				`<div style="margin-top:10px; padding-top:10px; border-top:1px dashed var(--border-color);"><div style="font-weight:600; margin-bottom:6px;">${__(
					"Packaging"
				)}</div>${pkg_body}</div>`
			);
		}

		if (r.bpak) {
			$card.append(this.bpak_section(r.bpak));
		}

		return $card;
	}

	bpak_section(b) {
		const body = [
			this.row(__("BpAK"), this.doc_link("BpAK", b.name)),
			this.row(__("Serial No"), frappe.utils.escape_html(b.serial_no || "")),
			this.row(
				__("Template"),
				b.bpak_template
					? this.doc_link("BpAK Template", b.bpak_template) +
							(b.bpak_template_name
								? ` — ${frappe.utils.escape_html(b.bpak_template_name)}`
								: "")
					: ""
			),
			this.row(__("Status"), frappe.utils.escape_html(b.status || "")),
			this.row(__("Sales Order"), b.sales_order ? this.doc_link("Sales Order", b.sales_order) : ""),
			this.row(__("Customer"), b.customer ? this.doc_link("Customer", b.customer) : ""),
		].join("");
		return `<div style="margin-top:10px; padding-top:10px; border-top:1px dashed var(--border-color);"><div style="font-weight:600; margin-bottom:6px;">${__(
			"BpAK"
		)}</div>${body}</div>`;
	}

	render_package(r) {
		const d = r.doc;
		const title = `${__("Package")}: ${this.doc_link("Package", d.name)}`;
		const refs = [
			this.row(__("Status"), frappe.utils.escape_html(d.status || "")),
			this.row(
				__("Purchase Receipt"),
				d.purchase_receipt ? this.doc_link("Purchase Receipt", d.purchase_receipt) : ""
			),
			this.row(__("Sales Order"), d.sales_order ? this.doc_link("Sales Order", d.sales_order) : ""),
			this.row(
				__("Delivery Note"),
				d.delivery_note ? this.doc_link("Delivery Note", d.delivery_note) : ""
			),
			this.row(__("Shipment"), d.shipment ? this.doc_link("Shipment", d.shipment) : ""),
		].join("");

		const rows = (r.items || [])
			.map((it) => {
				const serials = (it.serial_no || "")
					.split(/[\s,]+/)
					.filter(Boolean)
					.map((s) => this.doc_link("Serial No", s))
					.join(", ");
				return `<tr>
				<td>${it.item_code ? this.doc_link("Item", it.item_code) : ""}${
					it.item_name
						? `<div class="text-muted small">${frappe.utils.escape_html(it.item_name)}</div>`
						: ""
				}</td>
				<td>${frappe.utils.escape_html(String(it.qty || ""))}</td>
				<td>${it.batch_no ? this.doc_link("Batch", it.batch_no) : ""}</td>
				<td>${serials}</td>
			</tr>`;
			})
			.join("");

		const table = `<table class="table table-bordered" style="margin-top:8px;">
			<thead><tr>
				<th>${__("Item")}</th><th>${__("Qty")}</th><th>${__("Batch")}</th><th>${__("Serial Nos")}</th>
			</tr></thead>
			<tbody>${rows || `<tr><td colspan="4" class="text-muted">${__("No items")}</td></tr>`}</tbody>
		</table>`;

		const $card = this.card(title, refs + table);
		if (r.bpak) {
			$card.append(this.bpak_section(r.bpak));
		}
		return $card;
	}

	render_item(r) {
		const d = r.doc;
		const title = `${__("Item")}: ${this.doc_link("Item", d.item_code)}`;
		const body = [
			d.item_name ? this.row(__("Name"), frappe.utils.escape_html(d.item_name)) : "",
			d.barcode ? this.row(__("Barcode"), frappe.utils.escape_html(d.barcode)) : "",
			d.uom ? this.row(__("UOM"), frappe.utils.escape_html(d.uom)) : "",
		].join("");
		return this.card(title, body);
	}

	render_batch(r) {
		const d = r.doc;
		const title = `${__("Batch")}: ${this.doc_link("Batch", d.batch_no)}`;
		const body = this.row(__("Item"), d.item_code ? this.doc_link("Item", d.item_code) : "");
		return this.card(title, body);
	}

	render_warehouse(r) {
		const d = r.doc;
		return this.card(`${__("Warehouse")}: ${this.doc_link("Warehouse", d.warehouse)}`, "");
	}

	render_generic(r) {
		return this.card(__("Result"), `<pre>${frappe.utils.escape_html(JSON.stringify(r, null, 2))}</pre>`);
	}
};

$(document).on("toolbar_setup", () => {
	if (!erpnext._global_scanner) {
		erpnext._global_scanner = new erpnext.GlobalScanner();
	}
	erpnext._global_scanner.mount_button();
});

$(document).ready(() => {
	if (!erpnext._global_scanner) {
		erpnext._global_scanner = new erpnext.GlobalScanner();
	}
	const tryMount = () => erpnext._global_scanner.mount_button();
	tryMount();
	setTimeout(tryMount, 500);
	setTimeout(tryMount, 1500);

	frappe.ui.keys.add_shortcut({
		shortcut: "ctrl+shift+b",
		action: () => erpnext._global_scanner.show(),
		description: __("Scan barcode"),
		ignore_inputs: true,
	});
});
