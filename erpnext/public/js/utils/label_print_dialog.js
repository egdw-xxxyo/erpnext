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
 *
 * Usage (bulk, from list view):
 *   erpnext.utils.open_bulk_label_print_dialog({
 *       doctype: "Employee",
 *       names: ["HR-EMP-00001", "HR-EMP-00002"],
 *   });
 */

erpnext.utils.open_bulk_label_print_dialog = function ({ doctype, names }) {
	const API_PRINTER = "erpnext.devices.doctype.label_printer.label_printer";

	const dlg = new frappe.ui.Dialog({
		title: __("Print Labels"),
		fields: [
			{
				fieldname: "label_template",
				fieldtype: "Select",
				label: __("Label Template"),
				options: [],
				reqd: 1,
				change: () => {
					_update_count(dlg, doctype, names);
					_validate_printer(dlg);
				},
			},
			{
				fieldname: "printer_name",
				fieldtype: "Select",
				label: __("Printer"),
				options: [],
				reqd: 1,
				change: () => _validate_printer(dlg),
			},
			{ fieldname: "copies", fieldtype: "Int", label: __("Copies"), default: 1, reqd: 1 },
			{ fieldname: "info_html", fieldtype: "HTML" },
			{
				fieldname: "validation_status",
				fieldtype: "HTML",
				options: `<div class="printer-validation-status text-muted" style="padding:8px 0;">${__("Select a printer to validate")}</div>`,
			},
		],
		primary_action_label: __("Print Now"),
		primary_action: (values) => {
			if (!dlg._printer_valid) {
				frappe.show_alert({ message: __("Printer is not ready"), indicator: "red" });
				return;
			}
			_create_bulk_jobs(values, true, dlg, doctype, names);
		},
		secondary_action_label: __("Add to Queue"),
		secondary_action: () => {
			const values = dlg.get_values();
			if (values) _create_bulk_jobs(values, false, dlg, doctype, names);
		},
	});

	dlg.show();

	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Label Template",
			filters: { reference_doctype: doctype },
			fields: ["name"],
			limit_page_length: 0,
			order_by: "name asc",
		},
		callback: (r) => {
			const names_list = (r.message || []).map((t) => t.name);
			dlg.set_df_property("label_template", "options", [""].concat(names_list).join("\n"));
			if (names_list.length === 1) dlg.set_value("label_template", names_list[0]);
		},
	});
	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Label Printer",
			filters: { is_enabled: 1 },
			fields: ["name"],
			limit_page_length: 0,
			order_by: "name asc",
		},
		callback: (r) => {
			const names_list = (r.message || []).map((p) => p.name);
			dlg.set_df_property("printer_name", "options", [""].concat(names_list).join("\n"));
			if (names_list.length === 1) dlg.set_value("printer_name", names_list[0]);
			else _validate_printer(dlg);
		},
	});
};

function _update_count(dlg, doctype, names) {
	const API_PRINTER = "erpnext.devices.doctype.label_printer.label_printer";
	const tmpl = dlg.get_value("label_template");
	if (!tmpl) { dlg.fields_dict.info_html.$wrapper.html(""); return; }
	frappe.call({
		method: API_PRINTER + ".count_labels",
		args: { source_doctype: doctype, source_names: JSON.stringify(names), label_template: tmpl },
		callback: (r) => {
			if (r.message) {
				dlg.fields_dict.info_html.$wrapper.html(
					`<div class="text-muted">${__("{0} labels from {1} records", [r.message.total, names.length])}</div>`
				);
			}
		},
	});
}

function _transform_to_go_to_queue(dialog, job_count) {
	dialog.$wrapper.find(".modal-footer .btn-secondary").hide();
	dialog.set_primary_action(__("Go to Queue"), () => {
		dialog.hide();
		frappe.set_route("List", "Print Job", { status: "Queued" });
	});
	dialog.$wrapper.find(".modal-footer .btn-primary")
		.prop("disabled", false)
		.removeClass("disabled");
	dialog.enable_primary_action();
	frappe.show_alert({
		message: __("{0} jobs added to queue", [job_count]),
		indicator: "green",
	});
}

function _create_bulk_jobs(values, print_immediately, dialog, doctype, names) {
	const API_PRINTER = "erpnext.devices.doctype.label_printer.label_printer";
	if (print_immediately) dialog.hide();
	frappe.call({
		method: API_PRINTER + ".print_labels_batch",
		args: {
			source_doctype: doctype,
			source_names: JSON.stringify(names),
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
			const job_names = r.message.jobs;
			if (!print_immediately) {
				_transform_to_go_to_queue(dialog, job_names.length);
				return;
			}
			let printed = 0, failed = 0;
			const total = job_names.length;
			const _finish = () => {
				frappe.hide_progress();
				frappe.show_alert({
					message: __("{0} printed, {1} failed", [printed, failed]),
					indicator: failed ? "red" : "green",
				});
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
}

erpnext.utils.open_label_print_dialog = function ({ by_item, templates_by_item, items }) {
	let _submitting = false;
	const API_PRINTER = "erpnext.devices.doctype.label_printer.label_printer";

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
		let invalid_row = false;
		rows.each(function () {
			let $row = $(this);
			if (!$row.find(".item-check").prop("checked")) return;
			let item_code = $row.data("item");
			let tmpl = $row.find(".tmpl-select").val();
			let printer = $row.find(".printer-select").val();
			let copies = parseInt($row.find(".copies-input").val()) || 1;
			if (!tmpl) return;
			if (!queue_only && $row.data("valid") !== true) invalid_row = true;
			calls.push({ item_code, tmpl, printer, copies });
		});
		if (!calls.length) {
			frappe.msgprint(__("No items selected"));
			return;
		}
		if (invalid_row) {
			frappe.show_alert({ message: __("One or more printers are not ready"), indicator: "red" });
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
					if (!all_jobs.length) {
						frappe.show_alert({ message: __("No print jobs created"), indicator: "orange" });
						d.hide();
						return;
					}
					_transform_to_go_to_queue(d, all_jobs.length);
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
		size: "extra-large",
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
				`<th>${__("Item")}</th><th>${__("Qty")}</th><th>${__("Copies")}</th><th>${__("Label Template")}</th><th>${__("Printer")}</th><th>${__("Status")}</th>` +
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
					`<td><span class="row-status text-muted" style="font-size:12px;">—</span></td>` +
					"</tr>";
			});
			html += "</tbody></table>";
			d.fields_dict.items_html.$wrapper.html(html);

			d.$wrapper.find(".check-all").on("change", function () {
				d.$wrapper.find(".item-check").prop("checked", $(this).prop("checked"));
				_validate_all_rows(d);
			});
			d.$wrapper.on("change", ".item-check, .tmpl-select, .printer-select", function () {
				const $row = $(this).closest(".label-item-row");
				_validate_row(d, $row);
			});

			d.show();
			_validate_all_rows(d);
		},
	});
};

erpnext.utils.open_simple_label_print_dialog = function ({ doctype, doc_name, label_templates, default_copies }) {
	const API_PRINTER = "erpnext.devices.doctype.label_printer.label_printer";

	let tmpl_options = label_templates.map((t) => t.label_template);
	let default_printer = label_templates[0].label_printer || "";
	let copies_default = parseInt(default_copies) > 0 ? parseInt(default_copies) : 1;

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
					_validate_printer(dlg);
				},
			},
			{
				fieldname: "printer_name",
				fieldtype: "Select",
				label: __("Printer"),
				options: [],
				reqd: 1,
				change: () => _validate_printer(dlg),
			},
			{
				fieldname: "copies",
				fieldtype: "Int",
				label: __("Copies"),
				default: copies_default,
				reqd: 1,
			},
			{
				fieldname: "validation_status",
				fieldtype: "HTML",
				options: `<div class="printer-validation-status text-muted" style="padding:8px 0;">${__("Select a printer to validate")}</div>`,
			},
		],
		primary_action_label: __("Print Now"),
		primary_action: (values) => {
			if (!dlg._printer_valid) {
				frappe.show_alert({ message: __("Printer is not ready"), indicator: "red" });
				return;
			}
			_create_simple_jobs(values, true, dlg);
		},
		secondary_action_label: __("Add to Queue"),
		secondary_action: () => {
			const values = dlg.get_values();
			if (values) _create_simple_jobs(values, false, dlg);
		},
	});

	function _create_simple_jobs(values, print_immediately, dialog) {
		if (print_immediately) dialog.hide();
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
				const job_names = r.message.jobs;
				if (!print_immediately) {
					_transform_to_go_to_queue(dialog, job_names.length);
					return;
				}

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
	}

	dlg.show();

	frappe.call({
		method: "frappe.client.get_list",
		args: { doctype: "Label Printer", filters: { is_enabled: 1 }, fields: ["name"], limit_page_length: 0, order_by: "name asc" },
		callback: (r) => {
			const names = (r.message || []).map((p) => p.name);
			const options = [""].concat(names).join("\n");
			dlg.set_df_property("printer_name", "options", options);
			let to_select = "";
			if (default_printer && names.includes(default_printer)) to_select = default_printer;
			else if (names.length === 1) to_select = names[0];
			if (to_select) dlg.set_value("printer_name", to_select);
			else _validate_printer(dlg);
		},
	});
};

function _set_validation_message(dlg, html) {
	dlg.$wrapper.find(".printer-validation-status").html(html);
}

function _validate_printer(dlg) {
	const API_PRINTER = "erpnext.devices.doctype.label_printer.label_printer";
	const printer = dlg.get_value("printer_name");
	const template = dlg.get_value("label_template");

	dlg._printer_valid = false;
	dlg.disable_primary_action();

	if (!printer || !template) {
		_set_validation_message(dlg, `<div class="text-muted">${__("Select printer and template to validate")}</div>`);
		return;
	}

	const token = (dlg._validation_token || 0) + 1;
	dlg._validation_token = token;

	_set_validation_message(dlg, `<div class="text-muted"><i class="fa fa-spinner fa-spin"></i> ${__("Validating printer...")}</div>`);

	const _fail = (msg) => {
		if (dlg._validation_token !== token) return;
		dlg._printer_valid = false;
		_set_validation_message(dlg, `<div style="color:var(--red-500);font-weight:600;">✗ ${msg}</div>`);
		dlg.disable_primary_action();
	};
	const _ok = (msg) => {
		if (dlg._validation_token !== token) return;
		dlg._printer_valid = true;
		_set_validation_message(dlg, `<div style="color:var(--green-600);font-weight:600;">✓ ${msg}</div>`);
		dlg.enable_primary_action();
	};

	frappe.db.get_value("Label Template", template, "label_size").then((r1) => {
		if (dlg._validation_token !== token) return;
		const required_size = r1.message && r1.message.label_size;
		if (!required_size) { _fail(__("Template has no label size")); return; }

		frappe.db.get_value("Label Printer", printer,
			["loaded_label_size", "is_label_change_in_progress", "mock_printing"]
		).then((r2) => {
			if (dlg._validation_token !== token) return;
			const p = r2.message || {};
			if (p.is_label_change_in_progress) {
				_fail(__("Printer is in label-change mode")); return;
			}
			if (p.loaded_label_size && p.loaded_label_size !== required_size) {
				_fail(__("Loaded label size '{0}' does not match template '{1}'", [p.loaded_label_size, required_size]));
				return;
			}
			if (p.mock_printing) {
				_ok(__("Mock printing — Label: {0}", [required_size]));
				return;
			}

			frappe.call({
				method: API_PRINTER + ".check_status",
				args: { printer_name: printer },
				error_handlers: { 500: () => {} },
				callback: (r3) => {
					const status = (r3.message && r3.message.status && r3.message.status.status) || "Offline";
					if (status !== "Ready") { _fail(__("Printer status: {0}", [status])); return; }
					const loaded = p.loaded_label_size || __("Not set");
					if (!p.loaded_label_size) {
						_fail(__("Printer has no loaded label size set; expected '{0}'", [required_size])); return;
					}
					_ok(__("Ready — Label: {0}", [loaded]));
				},
				error: () => _fail(__("Printer offline")),
			});
		});
	});
}

function _refresh_print_now_state(d) {
	const $rows = d.$wrapper.find(".label-item-row");
	let any_checked = false;
	let all_valid = true;
	$rows.each(function () {
		const $row = $(this);
		if (!$row.find(".item-check").prop("checked")) return;
		any_checked = true;
		if ($row.data("valid") !== true) all_valid = false;
	});
	const enable = any_checked && all_valid;
	const $btn = d.$wrapper.find(".modal-footer .btn-primary");
	if (enable) $btn.prop("disabled", false).removeClass("disabled");
	else $btn.prop("disabled", true).addClass("disabled");
}

function _validate_all_rows(d) {
	d.$wrapper.find(".label-item-row").each(function () {
		_validate_row(d, $(this));
	});
	_refresh_print_now_state(d);
}

function _validate_row(d, $row) {
	const API_PRINTER = "erpnext.devices.doctype.label_printer.label_printer";
	const $status = $row.find(".row-status");
	const checked = $row.find(".item-check").prop("checked");
	const tmpl = $row.find(".tmpl-select").val();
	const printer = $row.find(".printer-select").val();

	$row.data("valid", false);

	if (!checked) {
		$status.html(`<span class="text-muted">—</span>`);
		_refresh_print_now_state(d);
		return;
	}
	if (!tmpl || !printer) {
		$status.html(`<span style="color:var(--red-500);">✗ ${__("Select template & printer")}</span>`);
		_refresh_print_now_state(d);
		return;
	}

	const token = ($row.data("token") || 0) + 1;
	$row.data("token", token);
	$status.html(`<span class="text-muted"><i class="fa fa-spinner fa-spin"></i></span>`);

	const _fail = (msg) => {
		if ($row.data("token") !== token) return;
		$row.data("valid", false);
		$status.html(`<span style="color:var(--red-500);" title="${frappe.utils.escape_html(msg)}">✗ ${msg}</span>`);
		_refresh_print_now_state(d);
	};
	const _ok = (msg) => {
		if ($row.data("token") !== token) return;
		$row.data("valid", true);
		$status.html(`<span style="color:var(--green-600);">✓ ${msg}</span>`);
		_refresh_print_now_state(d);
	};

	frappe.db.get_value("Label Template", tmpl, "label_size").then((r1) => {
		if ($row.data("token") !== token) return;
		const required_size = r1.message && r1.message.label_size;
		if (!required_size) { _fail(__("No label size")); return; }

		frappe.db.get_value("Label Printer", printer,
			["loaded_label_size", "is_label_change_in_progress", "mock_printing"]
		).then((r2) => {
			if ($row.data("token") !== token) return;
			const p = r2.message || {};
			if (p.is_label_change_in_progress) { _fail(__("Label change in progress")); return; }
			if (p.loaded_label_size && p.loaded_label_size !== required_size) {
				_fail(__("Loaded '{0}' ≠ '{1}'", [p.loaded_label_size, required_size])); return;
			}
			if (p.mock_printing) { _ok(__("Mock — {0}", [required_size])); return; }

			frappe.call({
				method: API_PRINTER + ".check_status",
				args: { printer_name: printer },
				error_handlers: { 500: () => {} },
				callback: (r3) => {
					const status = (r3.message && r3.message.status && r3.message.status.status) || "Offline";
					if (status !== "Ready") { _fail(__("Printer: {0}", [status])); return; }
					if (!p.loaded_label_size) { _fail(__("No loaded size; expected '{0}'", [required_size])); return; }
					_ok(__("Ready — {0}", [p.loaded_label_size]));
				},
				error: () => _fail(__("Offline")),
			});
		});
	});
}
