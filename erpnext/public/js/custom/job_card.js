// Job Card customizations. Loaded through the `doctype_js` hook so that the stock
// job_card.js stays untouched and upstream merges stay conflict-free
// (see CLAUDE.md: prefer a hook over editing a stock file).
frappe.ui.form.on("Job Card", {
	refresh(frm) {
		frm.trigger("make_fields_read_only");

		if (frm.is_new()) return;

		frm.trigger("render_production_data");

		if (frm.doc.serial_no) {
			frm.page.add_menu_item(__("Print Labels"), () => {
				frm.trigger("print_labels");
			});
		}
	},

	render_production_data(frm) {
		frappe.call({
			method: "erpnext.manufacturing.page.workplace_portal.workplace_portal.get_production_data_for_job_card",
			args: { job_card: frm.doc.name },
			callback: (r) => {
				let data = r.message;
				if (!data) return;

				// Remove previous section if re-rendering
				frm.fields_dict.production_data_html &&
					frm.fields_dict.production_data_html.$wrapper.remove();
				$(frm.layout.wrapper).find(".production-data-section").remove();

				let html = `<div class="production-data-section" style="margin:15px 0;padding:15px;border:1px solid var(--border-color);border-radius:var(--border-radius);">
					<h6 style="font-weight:600;margin-bottom:12px;">${__("Production Data")}</h6>
					<div style="display:flex;gap:20px;margin-bottom:10px;font-size:13px;">
						<div><span style="color:var(--text-muted);">${__("Production Log")}:</span>
							<a href="/app/production-log/${encodeURIComponent(data.production_log)}">${data.production_log}</a>
						</div>`;

				if (data.workstation) {
					html += `<div><span style="color:var(--text-muted);">${__("Workstation")}:</span> ${
						data.workstation
					}</div>`;
				}
				if (data.workplace) {
					html += `<div><span style="color:var(--text-muted);">${__("Workplace")}:</span> ${
						data.workplace
					}</div>`;
				}
				if (data.finished_serial_no) {
					html += `<div><span style="color:var(--text-muted);">${__("Serial No")}:</span> ${
						data.finished_serial_no
					}</div>`;
				}
				html += `</div>`;

				if (data.readings && data.readings.length) {
					html += `<div>
						<div style="font-size:12px;color:var(--text-muted);font-weight:600;margin-bottom:4px;">${__("Readings")}</div>
						<table class="table table-bordered table-sm" style="font-size:13px;margin-bottom:0;">
							<thead><tr><th>${__("Field")}</th><th>${__("Value")}</th></tr></thead>
							<tbody>`;
					data.readings.forEach((r) => {
						html += `<tr><td>${frappe.utils.escape_html(
							r.label
						)}</td><td>${frappe.utils.escape_html(r.value || "")}</td></tr>`;
					});
					html += `</tbody></table></div>`;
				}

				html += `</div>`;

				// Insert after the last visible section
				$(frm.layout.wrapper).find(".form-page:first").append(html);
			},
		});
	},

	print_labels(frm) {
		const names = [frm.doc.name];
		const dlg = new frappe.ui.Dialog({
			title: __("Print Labels"),
			fields: [
				{
					fieldname: "label_template",
					fieldtype: "Link",
					label: __("Label Template"),
					options: "Label Template",
					reqd: 1,
					get_query: () => ({
						filters: { source_field: ["is", "set"] },
					}),
					change: () => {
						const tmpl = dlg.get_value("label_template");
						if (!tmpl) {
							dlg.fields_dict.info_html.$wrapper.html("");
							return;
						}
						frappe.call({
							method: "erpnext.devices.doctype.label_printer.label_printer.count_labels",
							args: {
								source_doctype: "Job Card",
								source_names: JSON.stringify(names),
								label_template: tmpl,
							},
							callback: (r) => {
								if (r.message) {
									dlg.fields_dict.info_html.$wrapper.html(
										`<div class="text-muted">${r.message.total} ${__(
											"labels will be created"
										)}</div>`
									);
								}
							},
						});
					},
				},
				{
					fieldname: "printer_name",
					fieldtype: "Link",
					label: __("Printer"),
					options: "Label Printer",
					reqd: 1,
					get_query: () => ({
						filters: { is_enabled: 1 },
					}),
				},
				{
					fieldname: "info_html",
					fieldtype: "HTML",
				},
			],
			primary_action_label: __("Print"),
			primary_action: (values) => {
				dlg.hide();
				frappe.call({
					method: "erpnext.devices.doctype.label_printer.label_printer.print_labels_batch",
					args: {
						source_doctype: "Job Card",
						source_names: JSON.stringify(names),
						label_template: values.label_template,
						printer_name: values.printer_name,
					},
					freeze: true,
					freeze_message: __("Creating print jobs..."),
					callback: (r) => {
						if (r.message) {
							frappe.show_alert({
								message: __("{0} print jobs created", [r.message.count]),
								indicator: "green",
							});
							frappe.set_route("List", "Print Job");
						}
					},
				});
			},
		});

		// Preselect if only one option
		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Label Template",
				filters: { source_field: ["is", "set"] },
				fields: ["name"],
				limit_page_length: 2,
			},
			async: false,
			callback: (r) => {
				if (r.message && r.message.length === 1) {
					dlg.set_value("label_template", r.message[0].name);
				}
			},
		});
		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Label Printer",
				filters: { is_enabled: 1 },
				fields: ["name"],
				limit_page_length: 2,
			},
			async: false,
			callback: (r) => {
				if (r.message && r.message.length === 1) {
					dlg.set_value("printer_name", r.message[0].name);
				}
			},
		});

		dlg.show();
	},

	make_fields_read_only(frm) {
		if (frm.doc.docstatus === 1) {
			frm.set_df_property("employee", "read_only", 1);
			frm.set_df_property("time_logs", "read_only", 1);
		}

		if (frm.doc.is_subcontracted) {
			frm.set_df_property("wip_warehouse", "label", __("Supplier Warehouse"));
		}
	},
});
