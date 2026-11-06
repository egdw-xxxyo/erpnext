frappe.ui.form.on("Commercial Offer", {
	onload(frm) {
		if (frm.is_new() && !frm.doc.company) {
			frm.set_value("company", frappe.defaults.get_user_default("Company"));
		}
	},

	setup(frm) {
		frm.set_query("base_template", () => ({ filters: { is_template: 1, disabled: 0 } }));
		const override_df = frappe.meta.get_docfield("Commercial Offer Field", "custom_value");
		if (override_df) override_df.formatter = erpnext.commercial_offer.format_override;
		const can_submit = frm.toolbar.can_submit.bind(frm.toolbar);
		frm.toolbar.can_submit = () => !frm.doc.is_template && can_submit();
	},

	is_template(frm) {
		frm.toolbar.refresh();
	},

	base_template(frm) {
		if (frm.doc.base_template && frm.is_new()) {
			erpnext.commercial_offer.make_from_template(frm.doc.base_template);
		}
	},

	refresh(frm) {
		erpnext.commercial_offer.bind_override_popover(frm);
		frm.set_df_property(
			"fields_help",
			"options",
			`<p class="text-muted">${__(
				"Key Capability rows fill the icon strip on page 1; Specification rows fill the table on page 2."
			)}<br>${__(
				"A value starting with = is a formula, e.g. ={Range}*2. {Name} reads a parameter of the source item or another row."
			)}</p>`
		);
		if (frm.doc.is_template) {
			frm.page.set_indicator(
				frm.doc.disabled ? __("Template (disabled)") : __("Template"),
				frm.doc.disabled ? "gray" : "purple"
			);
		}
		if (frm.doc.is_template && !frm.is_new()) {
			frm.add_custom_button(__("Create Offer"), () =>
				erpnext.commercial_offer.make_from_template(frm.doc.name)
			);
		}
		if (frm.doc.docstatus < 2) {
			frm.add_custom_button(__("Preview PDF"), () => erpnext.commercial_offer.preview_pdf(frm));
		}
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Download PDF"), () => erpnext.commercial_offer.download_pdf(frm));
			return;
		}
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(
				__("Specifications of Product"),
				() => erpnext.commercial_offer.fill_fields(frm),
				__("Fill")
			);
			frm.add_custom_button(
				__("Delivery Set from BOM"),
				() => erpnext.commercial_offer.fill_items(frm),
				__("Fill")
			);
			frm.add_custom_button(__("Refresh Preview"), () => erpnext.commercial_offer.preview(frm));
		}
	},
});

frappe.ui.form.on("Commercial Offer Field", {
	source_item: (frm) => erpnext.commercial_offer.preview_soon(frm),
	source_parameter: (frm) => erpnext.commercial_offer.preview_soon(frm),
	source_field: (frm) => erpnext.commercial_offer.preview_soon(frm),
	value: (frm) => erpnext.commercial_offer.preview_soon(frm),
	custom_value: (frm) => erpnext.commercial_offer.preview_soon(frm),
	label: (frm) => erpnext.commercial_offer.preview_soon(frm),
});

frappe.dom.set_style(
	`
	.co-override-icon { margin-left: 4px; color: var(--orange-500, #f59e0b); cursor: pointer; font-size: 11px; }
	.co-popover { position: absolute; z-index: 1100; min-width: 180px; max-width: 280px; padding: 10px 12px;
		background: var(--card-bg, #fff); border: 1px solid var(--border-color, #ddd); border-radius: 8px;
		box-shadow: var(--shadow-md, 0 4px 12px rgba(0,0,0,.15)); }
	.co-popover-value { margin: 2px 0 8px; font-weight: 600; word-break: break-word; }
	`,
	"commercial-offer-override-style"
);

erpnext.commercial_offer = {
	preview_pdf(frm) {
		const tab = window.open("", "_blank");
		if (tab) tab.document.body.innerText = __("Generating PDF...");
		frappe.call({
			method: "erpnext.crm.doctype.commercial_offer.commercial_offer.preview_pdf",
			args: { doc: frm.doc },
			freeze: true,
			freeze_message: __("Generating PDF..."),
			callback: ({ message }) => {
				const bytes = Uint8Array.from(atob(message), (char) => char.charCodeAt(0));
				const url = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
				if (tab) tab.location.href = url;
				else window.open(url, "_blank");
			},
			error: () => tab && tab.close(),
		});
	},

	make_from_template(template) {
		frappe.call({
			method: "erpnext.crm.doctype.commercial_offer.commercial_offer.make_from_template",
			args: { template },
			callback: ({ message }) => {
				if (!message) return;
				frappe.model.sync(message);
				locals[message.doctype][message.name].__unsaved = 1;
				frappe.set_route("Form", message.doctype, message.name);
			},
		});
	},

	download_pdf(frm) {
		const params = $.param({
			doctype: frm.doc.doctype,
			name: frm.doc.name,
			format: "Commercial Offer",
			no_letterhead: 1,
			_lang: "uk",
		});
		window.open(`/api/method/frappe.utils.print_format.download_pdf?${params}`);
	},

	preview_soon: frappe.utils.debounce((frm) => erpnext.commercial_offer.preview(frm), 400),

	preview(frm) {
		if (frm.doc.docstatus !== 0 || !frm.doc.main_item) return;
		frappe.call({
			method: "erpnext.crm.commercial_offer_fields.preview_fields",
			args: { doc: frm.doc },
			callback: ({ message }) => {
				(message || []).forEach((result) => {
					const row = locals["Commercial Offer Field"][result.name];
					if (!row) return;
					["preview", "default_value", "source_summary", "override"].forEach((key) => {
						row[key] = result[key];
					});
					if (result.unit && !row.unit) row.unit = result.unit;
				});
				frm.refresh_field("spec_fields");
			},
		});
	},

	format_override(value) {
		if (value === null || value === undefined || value === "") return "";
		return `${frappe.utils.escape_html(value)}<i class="fa fa-undo co-override-icon" title="${__(
			"Overridden value"
		)}"></i>`;
	},

	bind_override_popover(frm) {
		const grid = frm.fields_dict.spec_fields.grid;
		if (grid.override_popover_bound) return;
		grid.override_popover_bound = true;
		grid.wrapper[0].addEventListener(
			"click",
			(event) => {
				const icon = event.target.closest(".co-override-icon");
				if (!icon) return;
				event.preventDefault();
				event.stopPropagation();
				const name = $(icon).closest(".grid-row").attr("data-name");
				const row = locals["Commercial Offer Field"][name];
				if (row) erpnext.commercial_offer.show_override_popover(frm, icon, row);
			},
			true
		);
	},

	show_override_popover(frm, icon, row) {
		$(".co-popover").remove();
		const unit = row.unit ? ` ${row.unit}` : "";
		const $popover = $(`
			<div class="co-popover">
				<div class="text-muted small">${__("Default Value")}</div>
				<div class="co-popover-value"></div>
			</div>
		`).appendTo(document.body);
		$popover.find(".co-popover-value").text(`${row.default_value || "—"}${unit}`);
		if (frm.doc.docstatus === 0) {
			$(`<button class="btn btn-xs btn-default">${__("Reset to default")}</button>`)
				.appendTo($popover)
				.on("click", () => {
					$popover.remove();
					frappe.model.set_value(row.doctype, row.name, "custom_value", "");
				});
		}
		const rect = icon.getBoundingClientRect();
		$popover.css({
			top: rect.bottom + window.scrollY + 6,
			left: Math.max(8, rect.left + window.scrollX - 20),
		});
		setTimeout(() => {
			$(document).one("click.coPopover", (event) => {
				if (!$(event.target).closest(".co-popover").length) $popover.remove();
			});
		});
	},

	fill_fields(frm) {
		if (!frm.doc.main_item) {
			frappe.msgprint(__("Select the product first."));
			return;
		}
		frappe.call({
			method: "erpnext.crm.commercial_offer_fields.get_item_parameters",
			args: { item: frm.doc.main_item },
			callback: ({ message }) => {
				const rows = frm.doc.spec_fields || [];
				const existing = new Set(rows.map((row) => row.label));
				rows.filter((row) => (row.source_item || frm.doc.main_item) === frm.doc.main_item).forEach(
					(row) => existing.add(row.source_parameter)
				);
				(message || []).forEach((param) => {
					if (existing.has(param.parameter)) return;
					frm.add_child("spec_fields", {
						section: "Specification",
						label: param.parameter,
						source_item: frm.doc.main_item,
						source_parameter: param.parameter,
						unit: param.uom,
						default_value: param.value,
						preview: param.value,
					});
				});
				frm.refresh_field("spec_fields");
			},
		});
	},

	fill_items(frm) {
		if (!frm.doc.main_item) {
			frappe.msgprint(__("Select the product first."));
			return;
		}
		frappe.call({
			method: "erpnext.crm.commercial_offer_fields.get_delivery_set",
			args: { item: frm.doc.main_item },
			callback: ({ message }) => {
				if (!message?.length) {
					frappe.msgprint(__("The product has no default BOM."));
					return;
				}
				frm.clear_table("items");
				message.forEach((row) => frm.add_child("items", row));
				frm.refresh_field("items");
			},
		});
	},
};
