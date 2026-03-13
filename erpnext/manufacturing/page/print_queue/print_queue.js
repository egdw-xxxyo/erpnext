const API_QUEUE = "erpnext.manufacturing.page.print_queue.print_queue";
const API_PRINTER = "erpnext.manufacturing.doctype.label_printer.label_printer";

frappe.pages["print-queue"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Print Queue"),
		single_column: true,
	});

	new PrintQueue({
		wrapper: $(wrapper).find(".layout-main-section"),
		page: page,
	});
};

class PrintQueue {
	constructor({ wrapper, page }) {
		this.$wrapper = wrapper;
		this.page = page;
		this.selected_printer = null;
		this.printer_data = null;
		this.status_filter = "All";

		this.$toolbar = $('<div class="print-queue-toolbar"></div>');
		this.$wrapper.append(this.$toolbar);

		this.$content = $('<div class="print-queue-content"></div>');
		this.$wrapper.append(this.$content);

		this.setup();
	}

	setup() {
		frappe.call({
			method: API_QUEUE + ".get_printers",
			callback: (r) => {
				let printers = r.message || [];
				if (!printers.length) {
					this.$content.html(
						'<div class="text-muted text-center" style="padding:40px;">' +
						__("No enabled printers found. Create a Label Printer first.") +
						"</div>"
					);
					return;
				}
				this.render_toolbar(printers);
				this.select_printer(printers[0]);
			},
		});
	}

	render_toolbar(printers) {
		this.$toolbar.empty();
		let $row = $(`<div class="print-queue-toolbar-row"></div>`);

		let $printer_group = $(`<div class="toolbar-group">
			<label class="toolbar-label">${__("Printer")}:</label>
			<div class="printer-link-wrapper" style="display:inline-block;min-width:200px;"></div>
		</div>`);
		$row.append($printer_group);

		this._printer_link = frappe.ui.form.make_control({
			df: {
				fieldname: "printer",
				fieldtype: "Link",
				options: "Label Printer",
				get_query: () => ({ filters: { is_enabled: 1 } }),
			},
			parent: $printer_group.find(".printer-link-wrapper"),
			render_input: true,
		});
		this._printer_link.set_value(printers[0].name);
		this._printer_link.$input.on("change", () => {
			let name = this._printer_link.get_value();
			let printer = printers.find((p) => p.name === name);
			if (printer) {
				this.select_printer(printer);
			} else if (name) {
				// Printer not in initial list, fetch it
				frappe.call({
					method: API_QUEUE + ".get_printers",
					callback: (r) => {
						let p = (r.message || []).find((p) => p.name === name);
						if (p) this.select_printer(p);
					},
				});
			}
		});

		this.$label_badge = $('<span class="label-badge"></span>');
		$row.append(
			$('<div class="toolbar-group"></div>')
				.append(`<label class="toolbar-label">${__("Loaded")}:</label>`)
				.append(this.$label_badge)
		);

		this.$status_badge = $('<span class="status-badge"></span>');
		$row.append(
			$('<div class="toolbar-group"></div>')
				.append(`<label class="toolbar-label">${__("Status")}:</label>`)
				.append(this.$status_badge)
		);

		let $filter_group = $(`<div class="toolbar-group">
			<label class="toolbar-label">${__("Filter")}:</label>
		</div>`);
		let $filter = $('<select class="form-control input-sm status-filter"></select>');
		["All", "Queued", "Printing", "Printed", "Failed", "Cancelled"].forEach((s) => {
			$filter.append(`<option value="${s}">${__(s)}</option>`);
		});
		$filter.on("change", () => {
			this.status_filter = $filter.val();
			this.load_queue();
		});
		$filter_group.append($filter);
		$row.append($filter_group);

		let $actions = $('<div class="toolbar-group toolbar-actions"></div>');

		$actions.append(
			$(`<button class="btn btn-xs btn-primary">${__("Add to Queue")}</button>`).on("click", () =>
				this.add_to_queue_dialog()
			)
		);
		$actions.append(
			$(`<button class="btn btn-xs btn-default">${__("Change Labels")}</button>`).on("click", () =>
				this.change_labels_dialog()
			)
		);
		$actions.append(
			$(`<button class="btn btn-xs btn-default">${__("Refresh")}</button>`).on("click", () =>
				this.refresh()
			)
		);
		$row.append($actions);

		this.$toolbar.append($row);
	}

	select_printer(printer) {
		this.selected_printer = printer.name;
		this.printer_data = printer;
		this.update_badges();
		this.load_queue();

		frappe.call({
			method: API_PRINTER + ".check_status",
			args: { printer_name: printer.name },
			error_handlers: { 500: () => {} },
			callback: (r) => {
				if (r.message && r.message.status) {
					this.printer_data.last_status = r.message.status.status || "Unknown";
				} else {
					this.printer_data.last_status = "Offline";
				}
				this.update_badges();
			},
			error: () => {
				this.printer_data.last_status = "Offline";
				this.update_badges();
			},
		});
	}

	update_badges() {
		let p = this.printer_data;
		if (!p) return;

		let label_text = p.loaded_label_size || __("Not set");
		if (p.is_label_change_in_progress) {
			this.$label_badge
				.text(p.label_change_message || __("Changing..."))
				.attr("class", "label-badge badge-warning")
				.css("cursor", "pointer")
				.off("click").on("click", () => {
					this.show_label_change_confirm(p.pending_label_size || p.loaded_label_size || "");
				});
			this.$status_badge.text(__("Blocked")).attr("class", "status-badge badge-danger");
		} else {
			this.$label_badge.text(label_text).attr("class", "label-badge badge-success")
				.css("cursor", "default").off("click");
			let status = p.last_status || __("Unknown");
			let cls = status === "Ready" ? "badge-success" : "badge-danger";
			this.$status_badge.text(status).attr("class", "status-badge " + cls);
		}
	}

	load_queue() {
		frappe.call({
			method: API_QUEUE + ".get_queue",
			args: {
				printer_name: this.selected_printer,
				status: this.status_filter,
			},
			callback: (r) => {
				this.render_queue(r.message || []);
			},
		});
	}

	render_queue(jobs) {
		this._jobs = jobs;

		if (!jobs.length) {
			this.$content.html(
				'<div class="text-muted text-center" style="padding:40px;">' +
				__("No print jobs found.") +
				"</div>"
			);
			return;
		}

		let html = `<table class="table table-bordered print-queue-table">
			<thead><tr>
				<th style="width:30px;"><input type="checkbox" class="select-all"></th>
				<th>${__("Job")}</th>
				<th>${__("Template")}</th>
				<th>${__("Reference")}</th>
				<th>${__("Label Size")}</th>
				<th>${__("Copies")}</th>
				<th>${__("Status")}</th>
				<th>${__("Created")}</th>
			</tr></thead><tbody>`;

		let current_user = frappe.session.user;
		let loaded_size = this.printer_data && this.printer_data.loaded_label_size;

		jobs.forEach((job) => {
			let status_color = {
				Queued: "blue",
				Printing: "orange",
				Printed: "green",
				Failed: "red",
				Cancelled: "gray",
			}[job.status] || "gray";

			let ref_link = "";
			if (job.reference_doctype && job.reference_name) {
				ref_link = `<a href="/app/${frappe.router.slug(job.reference_doctype)}/${job.reference_name}">${job.reference_name}</a>`;
			} else if (job.reference_name) {
				ref_link = job.reference_name;
			}

			let is_mine = job.created_by_user === current_user;
			let row_style = is_mine ? "background:#f0f4ff;" : "";
			let user_badge = is_mine
				? ` <span class="indicator-pill blue" style="font-size:10px;">${__("Mine")}</span>`
				: job.created_by_user
					? ` <span class="text-muted" style="font-size:10px;">${frappe.user.full_name(job.created_by_user)}</span>`
					: "";

			html += `<tr style="${row_style}">
				<td><input type="checkbox" class="select-job" data-job="${job.name}"></td>
				<td><a href="/app/print-job/${job.name}">${job.name}</a>${user_badge}</td>
				<td>${job.label_template ? `<a href="/app/label-template/${encodeURIComponent(job.label_template)}">${job.label_template}</a>` : ""}</td>
				<td>${ref_link}</td>
				<td>${job.label_size
				? (loaded_size && job.label_size !== loaded_size
					? `<span style="color:var(--red-500);font-weight:bold;">${job.label_size}</span>`
					: job.label_size)
				: ""}</td>
				<td>${job.copies}</td>
				<td><span class="indicator-pill ${status_color}">${__(job.status)}</span></td>
				<td>${frappe.datetime.prettyDate(job.creation)}</td>
			</tr>`;
		});

		html += "</tbody></table>";

		let $table_wrapper = $(`<div>${html}</div>`);

		let self = this;
		$table_wrapper.find(".select-all").on("change", function () {
			$table_wrapper.find(".select-job").prop("checked", $(this).prop("checked"));
			self._update_batch_actions();
		});

		$table_wrapper.find(".select-job").on("change", () => {
			self._update_batch_actions();
		});

		this.$batch_bar = $(`<div class="batch-actions" style="display:none;padding:8px 12px;background:#f7f7f7;border:1px solid #d1d8dd;border-radius:4px;margin-bottom:10px;">
			<span class="batch-count text-muted" style="margin-right:12px;"></span>
			<button class="btn btn-xs btn-primary btn-batch-print" style="margin-right:6px;">${__("Print")}</button>
			<button class="btn btn-xs btn-default btn-batch-cancel" style="margin-right:6px;">${__("Cancel")}</button>
			<button class="btn btn-xs btn-danger btn-batch-delete">${__("Delete")}</button>
		</div>`);

		this.$batch_bar.find(".btn-batch-print").on("click", () => this._batch_action("print"));
		this.$batch_bar.find(".btn-batch-cancel").on("click", () => this._batch_action("cancel"));
		this.$batch_bar.find(".btn-batch-delete").on("click", () => this._batch_action("delete"));

		this.$content.empty().append(this.$batch_bar).append($table_wrapper);
	}

	_get_selected_jobs() {
		let jobs = [];
		this.$content.find(".select-job:checked").each(function () {
			jobs.push($(this).data("job"));
		});
		return jobs;
	}

	_update_batch_actions() {
		let selected = this._get_selected_jobs();
		if (!selected.length) {
			this.$batch_bar.hide();
			return;
		}

		this.$batch_bar.show();
		this.$batch_bar.find(".batch-count").text(__("{0} selected", [selected.length]));

		let $print_btn = this.$batch_bar.find(".btn-batch-print");
		let is_changing = this.printer_data && this.printer_data.is_label_change_in_progress;

		if (is_changing) {
			$print_btn.prop("disabled", true);
			$print_btn.attr("title", __("Label change in progress"));
		} else {
			let loaded_size = this.printer_data && this.printer_data.loaded_label_size;
			if (loaded_size) {
				let mismatched = [];
				for (let name of selected) {
					let job = (this._jobs || []).find((j) => j.name === name);
					if (job && job.label_size && job.label_size !== loaded_size) {
						mismatched.push(job.name);
					}
				}
				if (mismatched.length) {
					$print_btn.prop("disabled", true);
					$print_btn.attr("title",
						__("{0} job(s) require a different label size than loaded ({1})", [mismatched.length, loaded_size])
					);
				} else {
					$print_btn.prop("disabled", false);
					$print_btn.attr("title", "");
				}
			} else {
				$print_btn.prop("disabled", false);
				$print_btn.attr("title", "");
			}
		}
	}

	_batch_action(action) {
		let jobs = this._get_selected_jobs();
		if (!jobs.length) return;

		if (action === "print") {
			this._batch_print_sequential(jobs);
			return;
		}

		let method, confirm_msg;
		if (action === "cancel") {
			method = API_PRINTER + ".batch_cancel_jobs";
			confirm_msg = __("Cancel {0} print jobs?", [jobs.length]);
		} else if (action === "delete") {
			method = API_PRINTER + ".batch_delete_jobs";
			confirm_msg = __("Permanently delete {0} print jobs?", [jobs.length]);
		}

		let do_action = () => {
			frappe.call({
				method: method,
				args: { job_names: JSON.stringify(jobs) },
				freeze: true,
				freeze_message: __("Processing..."),
				callback: (r) => {
					if (r.message) {
						let msg = JSON.stringify(r.message);
						if (r.message.cancelled !== undefined) msg = __("{0} cancelled", [r.message.cancelled]);
						if (r.message.deleted !== undefined) msg = __("{0} deleted", [r.message.deleted]);
						frappe.show_alert({ message: msg, indicator: "green" });
					}
					this.load_queue();
				},
			});
		};

		if (confirm_msg) {
			frappe.confirm(confirm_msg, do_action);
		} else {
			do_action();
		}
	}

	_batch_print_sequential(jobs) {
		let total = jobs.length;
		let printed = 0, failed = 0;

		this.$batch_bar.find(".batch-count").text(__("Printing {0}/{1}...", [0, total]));
		this.$batch_bar.find(".btn-batch-print").prop("disabled", true);
		this.$batch_bar.find(".btn-batch-cancel").prop("disabled", true);
		this.$batch_bar.find(".btn-batch-delete").prop("disabled", true);

		let print_next = (i) => {
			if (i >= jobs.length) {
				frappe.show_alert({
					message: __("{0} printed, {1} failed", [printed, failed]),
					indicator: failed ? "orange" : "green",
				});
				this.$batch_bar.find(".btn-batch-print").prop("disabled", false);
				this.$batch_bar.find(".btn-batch-cancel").prop("disabled", false);
				this.$batch_bar.find(".btn-batch-delete").prop("disabled", false);
				this.load_queue();
				return;
			}

			this.$batch_bar.find(".batch-count").text(__("Printing {0}/{1}...", [i + 1, total]));

			let $row = this.$content.find(`.select-job[data-job="${jobs[i]}"]`).closest("tr");
			$row.css("background", "#fffde7");

			frappe.call({
				method: API_PRINTER + ".print_label",
				args: { print_job_name: jobs[i] },
				callback: () => {
					printed++;
					$row.find(".indicator-pill")
						.attr("class", "indicator-pill green").text(__("Printed"));
					$row.css("background", "");
					print_next(i + 1);
				},
				error: () => {
					failed++;
					$row.find(".indicator-pill")
						.attr("class", "indicator-pill red").text(__("Failed"));
					$row.css("background", "");
					print_next(i + 1);
				},
			});
		};

		print_next(0);
	}

	add_to_queue_dialog() {
		if (!this.selected_printer) return;

		let d = new frappe.ui.Dialog({
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
						let mode = d.get_value("input_mode");
						let is_doc = mode === "Document";

						d.set_df_property("reference_doctype", "hidden", !is_doc);
						d.set_df_property("reference_doctype", "reqd", is_doc ? 1 : 0);
						d.set_df_property("label_template", "get_query", () => {
							if (is_doc) {
								let dt = d.get_value("reference_doctype");
								return dt ? { filters: { reference_doctype: dt } } : {};
							} else {
								return { filters: { reference_doctype: ["in", ["", null]] } };
							}
						});

						// Clear dependent fields
						d.set_value("label_template", "");
						d.set_df_property("reference_name", "hidden", 1);
						d.set_df_property("scan_input", "hidden", 1);
						d.set_df_property("data_input", "hidden", is_doc);
					},
				},
				{
					fieldname: "reference_doctype",
					fieldtype: "Link",
					label: __("DocType"),
					options: "DocType",
					reqd: 1,
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
						let mode = d.get_value("input_mode");
						if (mode === "Document") {
							let dt = d.get_value("reference_doctype");
							return dt ? { filters: { reference_doctype: dt } } : {};
						} else {
							return { filters: { reference_doctype: ["in", ["", null]] } };
						}
					},
					change: () => {
						let tmpl = d.get_value("label_template");
						let mode = d.get_value("input_mode");

						if (mode === "Data") {
							d.set_df_property("reference_name", "hidden", 1);
							d.set_df_property("scan_input", "hidden", 1);
							d.set_df_property("data_input", "hidden", !tmpl);
							return;
						}

						// Document mode
						d.set_df_property("data_input", "hidden", 1);
						if (!tmpl) {
							d.set_df_property("reference_name", "hidden", 1);
							d.set_df_property("scan_input", "hidden", 1);
							return;
						}
						let ref_dt = d.get_value("reference_doctype");
						if (ref_dt) {
							d._ref_doctype = ref_dt;
							d.set_df_property("reference_name", "hidden", 0);
							d.set_df_property("reference_name", "options", ref_dt);
							d.set_df_property("reference_name", "label",
								__("Select {0}", [__(ref_dt)]));
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
					hidden: 1,
					description: __("Scan or type a name and press Enter to add"),
				},
				{
					fieldname: "reference_name",
					fieldtype: "MultiSelectPills",
					label: __("Select Document"),
					options: "",
					hidden: 1,
					get_data: function(txt) {
						let ref_dt = d._ref_doctype;
						if (!ref_dt) return [];
						return frappe.call({
							method: "frappe.client.get_list",
							args: {
								doctype: ref_dt,
								filters: { name: ["like", `%${txt}%`] },
								fields: ["name"],
								limit_page_length: 20,
							},
						}).then((r) => {
							return (r.message || []).map((v) => ({
								value: v.name,
								description: v.name,
							}));
						});
					},
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
				this._create_jobs_from_dialog(d, values, false);
			},
			secondary_action_label: __("Print Now"),
			secondary_action: () => {
				let values = d.get_values();
				if (values) {
					this._create_jobs_from_dialog(d, values, true);
				}
			},
		});

		// Style the secondary action as a print button
		d.$wrapper.find(".btn-secondary").removeClass("btn-secondary")
			.addClass("btn-success").text(__("Print Now"));

		// Barcode scanner input — Enter adds to pills
		let $scan = d.fields_dict.scan_input && d.fields_dict.scan_input.$input;
		if ($scan) {
			$scan.on("keydown", (e) => {
				if (e.key === "Enter") {
					e.preventDefault();
					let val = $scan.val().trim();
					if (!val) return;

					let pills_field = d.fields_dict.reference_name;
					let current = pills_field.get_value() || [];
					if (!Array.isArray(current)) current = current ? [current] : [];
					if (!current.includes(val)) {
						current.push(val);
						pills_field.set_value(current);
					}
					$scan.val("");
				}
			});
		}

		d.show();
	}

	_parse_data_input(values, data_fields) {
		let mode = values.input_mode;

		if (mode === "Document") {
			let selected = values.reference_name;
			if (!selected) return [];
			if (!Array.isArray(selected)) selected = [selected];
			return selected.map((name) => ({ reference_name: name }));
		}

		// Data mode
		let text = (values.data_input || "").trim();
		if (!text) return [];

		let lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
		if (!lines.length) return [];

		let fields = (data_fields || "").split(",").map((f) => f.trim()).filter(Boolean);

		if (!fields.length) {
			// Single-value mode: each line = one label with doc.name
			return lines.map((line) => ({ reference_name: line, raw_data: { name: line } }));
		}

		// CSV mode: first line may be header
		let start = 0;
		let first_cols = lines[0].split(",").map((c) => c.trim());
		if (first_cols.length === fields.length &&
			first_cols.every((c) => fields.includes(c))) {
			// First line is a header, reorder fields to match
			fields = first_cols;
			start = 1;
		}

		let items = [];
		for (let i = start; i < lines.length; i++) {
			let cols = lines[i].split(",").map((c) => c.trim());
			let data = {};
			fields.forEach((f, idx) => {
				data[f] = cols[idx] || "";
			});
			// Use first field as reference_name for display
			items.push({ reference_name: cols[0] || "", raw_data: data });
		}
		return items;
	}

	_create_jobs_from_dialog(d, values, print_immediately) {
		// Fetch data_fields from template
		let tmpl = values.label_template;
		let do_create = (data_fields) => {
			let items = this._parse_data_input(values, data_fields);
			if (!items.length) {
				frappe.show_alert({ message: __("No items specified"), indicator: "orange" });
				return;
			}

			d.hide();
			let created_jobs = [];
			let total = items.length;

			frappe.show_progress(__("Creating print jobs..."), 0, total);

			let create_next = (i) => {
				if (i >= items.length) {
					frappe.hide_progress();
					$(".modal.show .progress").closest(".modal").modal("hide");
					if (print_immediately && created_jobs.length) {
						frappe.show_alert({
							message: __("{0} jobs created, printing...", [created_jobs.length]),
							indicator: "blue",
						});
						this.load_queue();
						this._batch_print_sequential(created_jobs);
					} else {
						frappe.show_alert({
							message: __("{0} jobs added to queue", [created_jobs.length]),
							indicator: "green",
						});
						this.load_queue();
					}
					return;
				}

				frappe.show_progress(__("Creating print jobs..."), i, total);

				let args = {
					label_template: values.label_template,
					printer_name: this.selected_printer,
					reference_name: items[i].reference_name,
					copies: values.copies || 1,
				};
				if (items[i].raw_data) {
					args.raw_data = JSON.stringify(items[i].raw_data);
				}

				frappe.call({
					method: API_PRINTER + ".create_print_job",
					args: args,
					callback: (r) => {
						if (r.message && r.message.print_job) {
							created_jobs.push(r.message.print_job);
						}
						create_next(i + 1);
					},
					error: () => {
						create_next(i + 1);
					},
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

	change_labels_dialog() {
		if (!this.selected_printer) return;

		if (this.printer_data && this.printer_data.is_label_change_in_progress) {
			let pending = this.printer_data.pending_label_size;
			if (pending) {
				this.show_label_change_confirm(pending);
			} else {
				this.show_label_change_confirm(this.printer_data.loaded_label_size || "");
			}
			return;
		}

		let d = new frappe.ui.Dialog({
			title: __("Change Labels"),
			fields: [
				{
					fieldname: "info",
					fieldtype: "HTML",
					options: `<p class="text-muted">${__(
						"This will block all print jobs while you change labels in the printer."
					)}</p>`,
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
						printer_name: this.selected_printer,
						new_label_size: values.new_label_size,
						message: __("Changing to {0}", [values.new_label_size]),
					},
					callback: () => {
						this.printer_data.is_label_change_in_progress = 1;
						this.printer_data.pending_label_size = values.new_label_size;
						this.update_badges();
						this.show_label_change_confirm(values.new_label_size);
					},
				});
			},
		});
		d.show();
	}

	show_label_change_confirm(new_label_size) {
		let fields = [];
		if (new_label_size) {
			fields.push({
				fieldname: "info",
				fieldtype: "HTML",
				options: `<div class="text-center" style="padding:20px;">
					<p style="font-size:16px;">${__("Please change labels in the printer to:")}</p>
					<p style="font-size:24px;font-weight:bold;">${new_label_size}</p>
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

		let d = new frappe.ui.Dialog({
			title: __("Label Change In Progress"),
			fields: fields,
			primary_action_label: __("Done"),
			primary_action: (values) => {
				let size = new_label_size || values.new_label_size;
				if (!size) return;
				d.hide();
				frappe.call({
					method: API_PRINTER + ".complete_label_change",
					args: {
						printer_name: this.selected_printer,
						new_label_size: size,
					},
					callback: (r) => {
						let msg = __("Labels changed to {0}", [size]);
						if (r.message && r.message.cancelled_jobs) {
							msg += ". " + __("{0} mismatched jobs cancelled", [r.message.cancelled_jobs]);
						}
						frappe.show_alert({ message: msg, indicator: "green" });
						this.refresh();
					},
				});
			},
		});

		d.$wrapper.find(".modal-footer").prepend(
			$(`<button class="btn btn-default btn-sm">${__("Cancel Change")}</button>`)
				.on("click", () => {
					d.hide();
					frappe.call({
						method: API_PRINTER + ".cancel_label_change",
						args: { printer_name: this.selected_printer },
						callback: () => {
							frappe.show_alert({
								message: __("Label change cancelled"),
								indicator: "blue",
							});
							this.refresh();
						},
					});
				})
		);

		d.show();
	}

	refresh() {
		frappe.call({
			method: API_QUEUE + ".get_printers",
			callback: (r) => {
				let printers = r.message || [];
				let current = printers.find((p) => p.name === this.selected_printer);
				if (current) {
					this.printer_data = current;
					this.update_badges();
				}
				this.load_queue();
			},
		});
	}
}
