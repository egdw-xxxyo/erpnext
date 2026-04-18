/**
 * Shared label printing dialog.
 *
 * Usage (serial-based):
 *   erpnext.utils.open_label_print_dialog({
 *       by_item: { "ITEM-001": { item_name: "Widget", serials: ["SN-1", "SN-2"] } },
 *       templates_by_item: { "ITEM-001": [{ label_template: "T1", label_printer: "P1" }] },
 *       items: ["ITEM-001"],
 *   });
 *
 * Usage (simple, for any doctype with label_templates child table):
 *   erpnext.utils.open_simple_label_print_dialog({
 *       doctype: "Employee",
 *       doc_name: "HR-EMP-00001",
 *       label_templates: [{ label_template: "T1", label_printer: "P1" }],
 *   });
 */

erpnext.utils.open_label_print_dialog = function ({ by_item, templates_by_item, items }) {
	let _submitting = false;
	const API_PRINTER = "erpnext.manufacturing.doctype.label_printer.label_printer";

	const _print_sequential = (job_names, dialog) => {
		let printed = 0,
			failed = 0;
		const total = job_names.length;

		const _finish = () => {
			frappe.hide_progress();
			_submitting = false;
			let msg = __("{0} printed, {1} failed", [printed, failed]);
			frappe.show_alert({ message: msg, indicator: failed ? "red" : "green" });
			dialog.hide();
		};

		const _print_one = (i) => {
			if (i >= job_names.length) {
				_finish();
				return;
			}
			frappe.show_progress(__("Printing..."), i + 1, total);
			frappe.call({
				method: API_PRINTER + ".print_label",
				args: { print_job_name: job_names[i] },
				callback: (r) => {
					printed++;
					const delay = (r.message && r.message.print_delay_ms) || 1500;
					setTimeout(() => _print_one(i + 1), delay);
				},
				error: () => {
					failed++;
					_print_one(i + 1);
				},
			});
		};
		_print_one(0);
	};

	let _submit = (queue_only) => {
		if (_submitting) return;
		let rows = d.$wrapper.find(".label-item-row");
		let calls = [];
		rows.each(function () {
			let $row = $(this);
			if (!$row.find(".item-check").prop("checked")) return;
			let item_code = $row.data("item");
			let tmpl = $row.find(".tmpl-select").val();
			let printer = $row.find(".printer-select").val();
			let copies = parseInt($row.find(".copies-input").val()) || 1;
			if (!tmpl) return;
			calls.push({ item_code, tmpl, printer, copies });
		});
		if (!calls.length) {
			frappe.msgprint(__("No items selected"));
			return;
		}

		_submitting = true;
		d.$wrapper.find(".btn-primary, .btn-secondary, .btn-default").prop("disabled", true);

		const CHUNK_SIZE = 10;
		let all_jobs = [];
		let chunks = [];
		let total_serials = 0;

		calls.forEach((p) => {
			let serials = by_item[p.item_code].serials;
			total_serials += serials.length;
			for (let i = 0; i < serials.length; i += CHUNK_SIZE) {
				chunks.push({
					serials: serials.slice(i, i + CHUNK_SIZE),
					tmpl: p.tmpl,
					printer: p.printer,
					copies: p.copies,
				});
			}
		});

		let created = 0;
		let chunk_idx = 0;

		const create_next_chunk = () => {
			if (chunk_idx >= chunks.length) {
				frappe.hide_progress();
				if (queue_only || !all_jobs.length) {
					_submitting = false;
					frappe.show_alert({
						message: __("{0} jobs added to queue", [all_jobs.length]),
						indicator: "green",
					});
					d.hide();
					return;
				}
				_print_sequential(all_jobs, d);
				return;
			}

			let chunk = chunks[chunk_idx];
			frappe.show_progress(__("Creating print jobs..."), created, total_serials);

			frappe.call({
				method: API_PRINTER + ".print_labels_batch",
				args: {
					source_doctype: "Serial No",
					source_names: JSON.stringify(chunk.serials),
					label_template: chunk.tmpl,
					printer_name: chunk.printer || "",
					copies: chunk.copies,
				},
				callback: (r) => {
					if (r.message && r.message.jobs) {
						all_jobs.push(...r.message.jobs);
						created += r.message.jobs.length;
					}
					chunk_idx++;
					create_next_chunk();
				},
				error: () => {
					chunk_idx++;
					create_next_chunk();
				},
			});
		};
		create_next_chunk();
	};

	let d = new frappe.ui.Dialog({
		title: __("Print Labels"),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "items_html" }],
		primary_action_label: __("Print Now"),
		primary_action: function () {
			_submit(false);
		},
		secondary_action_label: __("Add to Queue"),
		secondary_action: function () {
			_submit(true);
		},
	});

	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Label Printer",
			filters: { is_enabled: 1 },
			fields: ["name"],
			limit_page_length: 50,
		},
		callback: function (pr) {
			let printers = (pr.message || []).map((p) => p.name);
			let build_printer_opts = (default_printer) => {
				if (printers.length === 1) default_printer = printers[0];
				return (
					(printers.length > 1
						? `<option value="">${__("— select printer —")}</option>`
						: "") +
					printers
						.map(
							(p) =>
								`<option value="${frappe.utils.escape_html(p)}"${p === default_printer ? " selected" : ""}>${frappe.utils.escape_html(p)}</option>`
						)
						.join("")
				);
			};

			let html =
				"<table class='table' style='margin-top:8px'><thead><tr>" +
				`<th style="width:30px"><input type="checkbox" class="check-all" checked></th>` +
				`<th>${__("Item")}</th><th>${__("Qty")}</th><th>${__("Copies")}</th><th>${__("Label Template")}</th><th>${__("Printer")}</th>` +
				"</tr></thead><tbody>";
			items.forEach((item_code) => {
				let info = by_item[item_code];
				let tmpls = templates_by_item[item_code];
				let tmpl_opts = tmpls
					.map(
						(t) =>
							`<option value="${frappe.utils.escape_html(t.label_template)}">${frappe.utils.escape_html(t.label_template)}</option>`
					)
					.join("");
				let printer_opts = build_printer_opts(tmpls[0].label_printer || "");
				html +=
					`<tr class="label-item-row" data-item="${frappe.utils.escape_html(item_code)}">` +
					`<td><input type="checkbox" class="item-check" checked></td>` +
					`<td>${frappe.utils.escape_html(info.item_name || item_code)}</td>` +
					`<td>${info.serials.length}</td>` +
					`<td><input type="number" class="copies-input form-control form-control-sm" value="1" min="1" style="width:60px"></td>` +
					`<td><select class="tmpl-select form-control form-control-sm">${tmpl_opts}</select></td>` +
					`<td><select class="printer-select form-control form-control-sm">${printer_opts}</select></td>` +
					"</tr>";
			});
			html += "</tbody></table>";
			d.fields_dict.items_html.$wrapper.html(html);

			d.$wrapper.find(".check-all").on("change", function () {
				d.$wrapper.find(".item-check").prop("checked", $(this).prop("checked"));
			});

			d.show();
		},
	});
};

erpnext.utils.open_simple_label_print_dialog = function ({ doctype, doc_name, label_templates }) {
	const API_PRINTER = "erpnext.manufacturing.doctype.label_printer.label_printer";

	let tmpl_options = label_templates.map((t) => t.label_template);
	let default_printer = label_templates[0].label_printer || "";

	const dlg = new frappe.ui.Dialog({
		title: __("Print Labels"),
		fields: [
			{
				fieldname: "label_template",
				fieldtype: "Select",
				label: __("Label Template"),
				options: tmpl_options,
				default: tmpl_options[0],
				reqd: 1,
				change: () => {
					let selected = dlg.get_value("label_template");
					let match = label_templates.find((t) => t.label_template === selected);
					if (match && match.label_printer) {
						dlg.set_value("printer_name", match.label_printer);
					}
				},
			},
			{
				fieldname: "printer_name",
				fieldtype: "Link",
				label: __("Printer"),
				options: "Label Printer",
				reqd: 1,
				get_query: () => ({ filters: { is_enabled: 1 } }),
			},
			{
				fieldname: "copies",
				fieldtype: "Int",
				label: __("Copies"),
				default: 1,
				reqd: 1,
			},
		],
		primary_action_label: __("Print"),
		primary_action: (values) => {
			dlg.hide();
			frappe.call({
				method: API_PRINTER + ".print_labels_batch",
				args: {
					source_doctype: doctype,
					source_names: JSON.stringify([doc_name]),
					label_template: values.label_template,
					printer_name: values.printer_name,
					copies: values.copies,
				},
				freeze: true,
				freeze_message: __("Creating print jobs..."),
				callback: (r) => {
					if (!r.message || !r.message.jobs || !r.message.jobs.length) {
						frappe.show_alert({ message: __("No print jobs created"), indicator: "orange" });
						return;
					}
					let job_names = r.message.jobs;
					let printed = 0, failed = 0;
					const total = job_names.length;

					const _finish = () => {
						frappe.hide_progress();
						let msg = __("{0} printed, {1} failed", [printed, failed]);
						frappe.show_alert({ message: msg, indicator: failed ? "red" : "green" });
					};

					const _print_one = (i) => {
						if (i >= job_names.length) { _finish(); return; }
						frappe.show_progress(__("Printing..."), i + 1, total);
						frappe.call({
							method: API_PRINTER + ".print_label",
							args: { print_job_name: job_names[i] },
							callback: (r2) => {
								printed++;
								const delay = (r2.message && r2.message.print_delay_ms) || 1500;
								setTimeout(() => _print_one(i + 1), delay);
							},
							error: () => { failed++; _print_one(i + 1); },
						});
					};
					_print_one(0);
				},
			});
		},
	});

	if (default_printer) {
		dlg.set_value("printer_name", default_printer);
	} else {
		frappe.call({
			method: "frappe.client.get_list",
			args: { doctype: "Label Printer", filters: { is_enabled: 1 }, fields: ["name"], limit_page_length: 2 },
			async: false,
			callback: (r) => {
				if (r.message && r.message.length === 1) dlg.set_value("printer_name", r.message[0].name);
			},
		});
	}

	dlg.show();
};
