const API_PRINTER = "erpnext.manufacturing.doctype.label_printer.label_printer";

frappe.listview_settings["Print Job"] = {
	add_fields: ["label_size", "label_printer", "created_by_user", "reference_doctype", "reference_name"],
	filters: [["status", "=", "Queued"]],

	get_indicator: function (doc) {
		const colors = {
			Queued: "blue",
			Printing: "orange",
			Printed: "green",
			Failed: "red",
			Cancelled: "grey",
		};
		return [__(doc.status), colors[doc.status] || "grey", "status,=," + doc.status];
	},

	onload: function (listview) {
		listview.page_length = 500;
		listview.selected_page_count = 500;

		// Print selected jobs
		listview.page.add_action_item(__("Send to Printer"), () => {
			const checked = listview.get_checked_items();
			if (!checked.length) {
				frappe.msgprint(__("Please select at least one Print Job"));
				return;
			}
			const printer = listview._selected_printer;
			if (!printer || printer.last_status !== "Ready") {
				const status = (printer && printer.last_status) || __("Unknown");
				frappe.confirm(
					__("Printer status is '{0}'. Continue anyway?", [status]),
					() => _batch_print_sequential(checked.map((d) => d.name), listview)
				);
				return;
			}
			_batch_print_sequential(checked.map((d) => d.name), listview);
		});

		// Cancel selected jobs
		listview.page.add_action_item(__("Cancel Jobs"), () => {
			const checked = listview.get_checked_items();
			if (!checked.length) {
				frappe.msgprint(__("Please select at least one Print Job"));
				return;
			}
			frappe.confirm(
				__("Cancel {0} print jobs?", [checked.length]),
				() => {
					frappe.call({
						method: API_PRINTER + ".batch_cancel_jobs",
						args: { job_names: JSON.stringify(checked.map((d) => d.name)) },
						freeze: true,
						freeze_message: __("Cancelling..."),
						callback: (r) => {
							if (r.message && r.message.cancelled !== undefined) {
								frappe.show_alert({ message: __("{0} cancelled", [r.message.cancelled]), indicator: "green" });
							}
							listview.refresh();
						},
					});
				}
			);
		});

		// Delete selected jobs
		listview.page.add_action_item(__("Delete Jobs"), () => {
			const checked = listview.get_checked_items();
			if (!checked.length) {
				frappe.msgprint(__("Please select at least one Print Job"));
				return;
			}
			frappe.confirm(
				__("Permanently delete {0} print jobs?", [checked.length]),
				() => {
					frappe.call({
						method: API_PRINTER + ".batch_delete_jobs",
						args: { job_names: JSON.stringify(checked.map((d) => d.name)) },
						freeze: true,
						freeze_message: __("Deleting..."),
						callback: (r) => {
							if (r.message && r.message.deleted !== undefined) {
								frappe.show_alert({ message: __("{0} deleted", [r.message.deleted]), indicator: "green" });
							}
							listview.refresh();
						},
					});
				}
			);
		});

		// Override the primary action after Frappe sets it up
		const orig_set_primary = listview.set_primary_action;
		listview.set_primary_action = function () {
			listview.page.set_primary_action(__("Add to Queue"), () => {
				_show_add_to_queue_dialog(listview);
			}, "add");
		};
		listview.set_primary_action();

		// Printer status banner
		_setup_printer_banner(listview);

		// Hide comments/likes column and view switcher
		listview.$page.append(`<style>
			.list-row .list-row--col.hidden-xs.text-right { display: none !important; }
			.list-row .comment-count, .list-row .like-action { display: none !important; }
			.list-liked-by-me, .list-comment-count { display: none !important; }
			.custom-btn-group, .sidebar-toggle-btn { display: none !important; }
		</style>`);
	},

	formatters: {
		created_by_user: function (value, df, doc) {
			if (!value) return "";
			const full_name = frappe.user.full_name(value);
			return `<span class="filterable ellipsis" data-filter="created_by_user,=,${value}">${full_name}</span>`;
		},
	},
};

function _setup_printer_banner(listview) {
	const $banner = $(`<div class="printer-status-banner" style="
		padding: 10px 15px;
		background: var(--card-bg);
		border-bottom: 1px solid var(--border-color);
		display: flex;
		align-items: center;
		gap: 15px;
		flex-wrap: wrap;
		font-size: 13px;
	"></div>`);

	const $printer_group = $(`<div style="display:flex;align-items:center;gap:6px;">
		<strong style="white-space:nowrap;">${__("Printer")}:</strong>
		<div class="printer-link-wrapper" style="display:inline-block;min-width:180px;"></div>
	</div>`);
	$banner.append($printer_group);

	const $loaded = $(`<div style="display:flex;align-items:center;gap:6px;">
		<strong>${__("Loaded")}:</strong>
		<span class="loaded-badge" style="
			display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600;color:white;background:var(--green-500);
		">${__("Not set")}</span>
	</div>`);
	$banner.append($loaded);

	const $status = $(`<div style="display:flex;align-items:center;gap:6px;">
		<strong>${__("Status")}:</strong>
		<span class="printer-status-badge" style="
			display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600;color:white;background:var(--gray-500);
		">${__("Unknown")}</span>
	</div>`);
	$banner.append($status);

	const $change_btn = $(`<button class="btn btn-xs btn-default" style="margin-left:auto;">${__("Change Labels")}</button>`);
	$banner.append($change_btn);

	listview.$page.find(".frappe-list").prepend($banner);

	const printer_link = frappe.ui.form.make_control({
		df: {
			fieldname: "printer",
			fieldtype: "Link",
			options: "Label Printer",
			get_query: () => ({ filters: { is_enabled: 1 } }),
		},
		parent: $printer_group.find(".printer-link-wrapper"),
		render_input: true,
	});
	printer_link.$wrapper.find(".form-group").css("margin-bottom", "0");
	printer_link.$wrapper.find(".clearfix, .help-box").hide();
	printer_link.$wrapper.css("margin-bottom", "0");

	// Auto-select first enabled printer
	frappe.call({
		method: "erpnext.manufacturing.page.print_queue.print_queue.get_printers",
		callback: (r) => {
			const printers = r.message || [];
			if (printers.length) {
				printer_link.set_value(printers[0].name);
				_update_printer_info(printers[0], $loaded, $status);
				listview._selected_printer = printers[0];
			}
		},
	});

	printer_link.$input.on("change", () => {
		const name = printer_link.get_value();
		if (!name) return;
		frappe.call({
			method: "erpnext.manufacturing.page.print_queue.print_queue.get_printers",
			callback: (r) => {
				const p = (r.message || []).find((p) => p.name === name);
				if (p) {
					_update_printer_info(p, $loaded, $status);
					listview._selected_printer = p;
				}
			},
		});
	});

	$change_btn.on("click", () => {
		const printer = listview._selected_printer;
		if (!printer) return;

		if (printer.is_label_change_in_progress) {
			_show_label_change_confirm(printer, $loaded, $status, listview);
			return;
		}

		const d = new frappe.ui.Dialog({
			title: __("Change Labels"),
			fields: [
				{
					fieldname: "info",
					fieldtype: "HTML",
					options: `<p class="text-muted">${__("This will block all print jobs while you change labels in the printer.")}</p>`,
				},
				{
					fieldname: "new_label_size",
					fieldtype: "Link",
					label: __("New Label Size"),
					options: "Label Size",
					reqd: 1,
				},
			],
			primary_action_label: __("Start Label Change"),
			primary_action: (values) => {
				d.hide();
				frappe.call({
					method: API_PRINTER + ".start_label_change",
					args: {
						printer_name: printer.name,
						new_label_size: values.new_label_size,
						message: __("Changing to {0}", [values.new_label_size]),
					},
					callback: () => {
						printer.is_label_change_in_progress = 1;
						printer.pending_label_size = values.new_label_size;
						_update_printer_info(printer, $loaded, $status);
						_show_label_change_confirm(printer, $loaded, $status, listview);
					},
				});
			},
		});
		d.show();
	});
}

function _update_printer_info(printer, $loaded, $status) {
	const $loaded_badge = $loaded.find(".loaded-badge");
	const $status_badge = $status.find(".printer-status-badge");

	if (printer.is_label_change_in_progress) {
		$loaded_badge
			.text(printer.label_change_message || __("Changing..."))
			.css({ background: "var(--orange-500)", color: "#333", cursor: "pointer" });
		$status_badge.text(__("Blocked")).css("background", "var(--red-500)");
	} else {
		$loaded_badge
			.text(printer.loaded_label_size || __("Not set"))
			.css({ background: "var(--green-500)", color: "white", cursor: "default" });

		// Check live status
		frappe.call({
			method: API_PRINTER + ".check_status",
			args: { printer_name: printer.name },
			error_handlers: { 500: () => {} },
			callback: (r) => {
				const s = (r.message && r.message.status && r.message.status.status) || "Offline";
				$status_badge
					.text(s)
					.css("background", s === "Ready" ? "var(--green-500)" : "var(--red-500)");
			},
			error: () => {
				$status_badge.text("Offline").css("background", "var(--red-500)");
			},
		});
	}
}

function _show_label_change_confirm(printer, $loaded, $status, listview) {
	const size = printer.pending_label_size || printer.loaded_label_size || "";

	let fields = [];
	if (size) {
		fields.push({
			fieldname: "info",
			fieldtype: "HTML",
			options: `<div class="text-center" style="padding:20px;">
				<p style="font-size:16px;">${__("Please change labels in the printer to:")}</p>
				<p style="font-size:24px;font-weight:bold;">${size}</p>
				<p class="text-muted">${__("Click 'Done' when labels are loaded.")}</p>
			</div>`,
		});
	} else {
		fields.push({
			fieldname: "new_label_size",
			fieldtype: "Link",
			label: __("Label Size"),
			options: "Label Size",
			reqd: 1,
			description: __("Select the label size you have loaded"),
		});
	}

	const d = new frappe.ui.Dialog({
		title: __("Label Change In Progress"),
		fields: fields,
		primary_action_label: __("Done"),
		primary_action: (values) => {
			const final_size = size || values.new_label_size;
			if (!final_size) return;
			d.hide();
			frappe.call({
				method: API_PRINTER + ".complete_label_change",
				args: { printer_name: printer.name, new_label_size: final_size },
				callback: (r) => {
					let msg = __("Labels changed to {0}", [final_size]);
					if (r.message && r.message.cancelled_jobs) {
						msg += ". " + __("{0} mismatched jobs cancelled", [r.message.cancelled_jobs]);
					}
					frappe.show_alert({ message: msg, indicator: "green" });
					printer.is_label_change_in_progress = 0;
					printer.loaded_label_size = final_size;
					_update_printer_info(printer, $loaded, $status);
					listview.refresh();
				},
			});
		},
	});

	d.$wrapper.find(".modal-footer").prepend(
		$(`<button class="btn btn-default btn-sm">${__("Cancel Change")}</button>`).on("click", () => {
			d.hide();
			frappe.call({
				method: API_PRINTER + ".cancel_label_change",
				args: { printer_name: printer.name },
				callback: () => {
					frappe.show_alert({ message: __("Label change cancelled"), indicator: "blue" });
					printer.is_label_change_in_progress = 0;
					_update_printer_info(printer, $loaded, $status);
				},
			});
		})
	);

	d.show();
}

function _show_add_to_queue_dialog(listview) {
	const printer = listview._selected_printer;
	if (!printer) {
		frappe.msgprint(__("Please select a printer first"));
		return;
	}

	const d = new frappe.ui.Dialog({
		title: __("Add to Print Queue"),
		size: "large",
		fields: [
			{
				fieldname: "input_mode",
				fieldtype: "Select",
				label: __("Input Mode"),
				options: "Document\nData",
				default: "Document",
				reqd: 1,
				change: () => {
					const mode = d.get_value("input_mode");
					const is_doc = mode === "Document";
					d.set_df_property("reference_doctype", "hidden", !is_doc);
					d.set_df_property("reference_doctype", "reqd", is_doc ? 1 : 0);
					d.set_value("label_template", "");
					d.set_df_property("reference_name", "hidden", 1);
					d.set_df_property("scan_input", "hidden", 1);
					d.set_df_property("data_scan_input", "hidden", is_doc);
					d.set_df_property("data_input", "hidden", is_doc);
				},
			},
			{
				fieldname: "reference_doctype",
				fieldtype: "Link",
				label: __("DocType"),
				options: "DocType",
				reqd: 1,
				get_query: () => {
					return {
						query: "erpnext.manufacturing.page.print_queue.print_queue.get_template_doctypes",
					};
				},
				change: () => {
					d.set_value("label_template", "");
					d.set_df_property("reference_name", "hidden", 1);
					d.set_df_property("scan_input", "hidden", 1);
				},
			},
			{
				fieldname: "label_template",
				fieldtype: "Link",
				label: __("Label Template"),
				options: "Label Template",
				reqd: 1,
				get_query: () => {
					const mode = d.get_value("input_mode");
					if (mode === "Document") {
						const dt = d.get_value("reference_doctype");
						return dt ? { filters: { reference_doctype: dt } } : {};
					}
					return { filters: { reference_doctype: ["in", ["", null]] } };
				},
				change: () => {
					const tmpl = d.get_value("label_template");
					const mode = d.get_value("input_mode");
					if (mode === "Data") {
						d.set_df_property("reference_name", "hidden", 1);
						d.set_df_property("scan_input", "hidden", 1);
						d.set_df_property("data_scan_input", "hidden", !tmpl);
						d.set_df_property("data_input", "hidden", !tmpl);
						return;
					}
					d.set_df_property("data_input", "hidden", 1);
					d.set_df_property("data_scan_input", "hidden", 1);
					if (!tmpl) {
						d.set_df_property("reference_name", "hidden", 1);
						d.set_df_property("scan_input", "hidden", 1);
						return;
					}
					const ref_dt = d.get_value("reference_doctype");
					if (ref_dt) {
						d._ref_doctype = ref_dt;
						d.set_df_property("reference_name", "hidden", 0);
						d.set_df_property("reference_name", "options", ref_dt);
						d.set_df_property("reference_name", "label", __("Select {0}", [__(ref_dt)]));
						d.set_df_property("scan_input", "hidden", 0);
					}
				},
			},
			{
				fieldname: "copies",
				fieldtype: "Int",
				label: __("Copies"),
				default: 1,
				reqd: 1,
			},
			{
				fieldname: "scan_input",
				fieldtype: "Data",
				label: __("Scan Barcode"),
				options: "Barcode",
				hidden: 1,
				description: __("Scan or type a serial number / name and press Enter"),
			},
			{
				fieldname: "reference_name",
				fieldtype: "MultiSelectPills",
				label: __("Select Document"),
				options: "",
				hidden: 1,
				get_data: function (txt) {
					const ref_dt = d._ref_doctype;
					if (!ref_dt) return [];
					return frappe.call({
						method: "frappe.client.get_list",
						args: {
							doctype: ref_dt,
							filters: { name: ["like", `%${txt}%`] },
							fields: ["name"],
							limit_page_length: 20,
						},
					}).then((r) => (r.message || []).map((v) => ({ value: v.name, description: v.name })));
				},
			},
			{
				fieldname: "data_scan_input",
				fieldtype: "Data",
				label: __("Scan Barcode"),
				options: "Barcode",
				hidden: 1,
				description: __("Scan or type a value and press Enter to add to the list"),
			},
			{
				fieldname: "data_input",
				fieldtype: "Small Text",
				label: __("Data (one item per line)"),
				hidden: 1,
				description: __("Enter reference names, one per line. Or paste CSV data."),
			},
		],
		primary_action_label: __("Add to Queue"),
		primary_action: (values) => {
			_create_jobs(d, values, printer, false, listview);
		},
		secondary_action_label: __("Print Now"),
		secondary_action: () => {
			const values = d.get_values();
			if (values) _create_jobs(d, values, printer, true, listview);
		},
	});

	d.$wrapper.find(".btn-secondary").removeClass("btn-secondary").addClass("btn-success").text(__("Print Now"));

	// Use event delegation on the dialog wrapper since scan_input is hidden
	// and its $input doesn't exist until the field is shown
	let _scan_timeout;

	const _process_scan = () => {
		const $input = d.$wrapper.find('[data-fieldname="scan_input"] input');
		if (!$input.length) return;
		const val = ($input.val() || "").trim();
		if (!val) return;
		$input.val("").focus();

		const ref_dt = d._ref_doctype;
		if (!ref_dt) return;
		const pills = d.fields_dict.reference_name;

		frappe.call({
			method: "erpnext.manufacturing.page.print_queue.print_queue.resolve_scan",
			args: { doctype: ref_dt, value: val },
			callback: (r) => {
				if (r.message) {
					let current = pills.get_value() || [];
					if (!Array.isArray(current)) current = current ? [current] : [];
					if (!current.includes(r.message)) {
						current.push(r.message);
						pills.set_value(current);
					}
					frappe.utils.play_sound("submit");
				} else {
					frappe.show_alert({
						message: __("No {0} found for '{1}'", [__(ref_dt), val]),
						indicator: "orange",
					});
				}
			},
		});
	};

	// Delegated keydown — Enter to submit scan
	d.$wrapper.on("keydown", '[data-fieldname="scan_input"] input', (e) => {
		if (e.key === "Enter" || e.which === 13) {
			e.preventDefault();
			e.stopPropagation();
			e.stopImmediatePropagation();
			clearTimeout(_scan_timeout);
			_process_scan();
			return false;
		}
	});

	// Delegated keydown — Enter on data_scan_input appends to data_input textarea
	d.$wrapper.on("keydown", '[data-fieldname="data_scan_input"] input', (e) => {
		if (e.key === "Enter" || e.which === 13) {
			e.preventDefault();
			e.stopPropagation();
			e.stopImmediatePropagation();
			const $input = d.$wrapper.find('[data-fieldname="data_scan_input"] input');
			const val = ($input.val() || "").trim();
			if (!val) return false;
			$input.val("").focus();

			const existing = (d.get_value("data_input") || "").trim();
			const new_val = existing ? existing + "\n" + val : val;
			d.set_value("data_input", new_val);
			frappe.utils.play_sound("submit");
			return false;
		}
	});

	d.show();
}

function _parse_items(values, data_fields) {
	if (values.input_mode === "Document") {
		let selected = values.reference_name;
		if (!selected) return [];
		if (!Array.isArray(selected)) selected = [selected];
		return selected.map((name) => ({ reference_name: name }));
	}

	const text = (values.data_input || "").trim();
	if (!text) return [];
	const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
	if (!lines.length) return [];

	let fields = (data_fields || "").split(",").map((f) => f.trim()).filter(Boolean);
	if (!fields.length) {
		return lines.map((line) => ({ reference_name: line, raw_data: { name: line } }));
	}

	let start = 0;
	const first_cols = lines[0].split(",").map((c) => c.trim());
	if (first_cols.length === fields.length && first_cols.every((c) => fields.includes(c))) {
		fields = first_cols;
		start = 1;
	}

	const items = [];
	for (let i = start; i < lines.length; i++) {
		const cols = lines[i].split(",").map((c) => c.trim());
		const data = {};
		fields.forEach((f, idx) => { data[f] = cols[idx] || ""; });
		items.push({ reference_name: cols[0] || "", raw_data: data });
	}
	return items;
}

function _create_jobs(d, values, printer, print_immediately, listview) {
	const tmpl = values.label_template;
	const do_create = (data_fields) => {
		const items = _parse_items(values, data_fields);
		if (!items.length) {
			frappe.show_alert({ message: __("No items specified"), indicator: "orange" });
			return;
		}

		d.hide();
		const created_jobs = [];
		const total = items.length;
		frappe.show_progress(__("Creating print jobs..."), 0, total);

		const create_next = (i) => {
			if (i >= items.length) {
				// Close all modals and backdrops
				frappe.hide_progress();
				$(".modal.show").modal("hide");
				$(".modal-backdrop").remove();
				$("body").removeClass("modal-open");

				setTimeout(() => {
					if (print_immediately && created_jobs.length) {
						frappe.show_alert({ message: __("{0} jobs created, printing...", [created_jobs.length]), indicator: "blue" });
						_batch_print_sequential(created_jobs, listview);
					} else {
						frappe.show_alert({ message: __("{0} jobs added to queue", [created_jobs.length]), indicator: "green" });
					}
					listview.refresh();
				}, 300);
				return;
			}

			frappe.show_progress(__("Creating print jobs..."), i, total);
			const args = {
				label_template: values.label_template,
				printer_name: printer.name,
				reference_name: items[i].reference_name,
				copies: values.copies || 1,
			};
			if (items[i].raw_data) args.raw_data = JSON.stringify(items[i].raw_data);

			frappe.call({
				method: API_PRINTER + ".create_print_job",
				args: args,
				callback: (r) => {
					if (r.message && r.message.print_job) created_jobs.push(r.message.print_job);
					create_next(i + 1);
				},
				error: () => create_next(i + 1),
			});
		};
		create_next(0);
	};

	if (values.input_mode === "Data" && tmpl) {
		frappe.db.get_value("Label Template", tmpl, "data_fields").then((r) => {
			do_create((r.message && r.message.data_fields) || "");
		});
	} else {
		do_create("");
	}
}

function _batch_print_sequential(job_names, listview) {
	let printed = 0, failed = 0;
	const total = job_names.length;

	const print_next = (i) => {
		if (i >= job_names.length) {
			frappe.show_alert({
				message: __("{0} printed, {1} failed", [printed, failed]),
				indicator: failed ? "orange" : "green",
			});
			if (listview) listview.refresh();
			return;
		}

		frappe.show_progress(__("Printing..."), i + 1, total);

		frappe.call({
			method: API_PRINTER + ".print_label",
			args: { print_job_name: job_names[i] },
			callback: () => { printed++; print_next(i + 1); },
			error: () => { failed++; print_next(i + 1); },
		});
	};

	print_next(0);
}
