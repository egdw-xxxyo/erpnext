/**
 * BarcodeField — reusable barcode preview + print button component.
 *
 * Usage:
 *   const bf = new erpnext.BarcodeField({
 *       frm,
 *       fieldname: "attendance_device_id",  // the Data field whose value is the barcode
 *       barcode_type: "CODE128",            // used to look up matching Label Templates
 *       format: "CODE128",                  // JsBarcode format for preview rendering
 *   });
 *
 *   // QR code:
 *   const qr = new erpnext.BarcodeField({
 *       frm,
 *       fieldname: "api_key",
 *       barcode_type: "QR",
 *       format: "QR",                       // renders QR code via server-side pyqrcode
 *   });
 *
 *   // Call on refresh and whenever the field value changes:
 *   bf.refresh();
 *
 * The component appends a barcode preview SVG and a small print icon button below
 * the field. Clicking the print button opens the standard label print dialog
 * (same as Purchase Receipt → Print Labels).
 */

frappe.provide("erpnext");

erpnext.BarcodeField = class BarcodeField {
	constructor({ frm, fieldname, barcode_type = "CODE128", format = "CODE128" }) {
		this.frm = frm;
		this.fieldname = fieldname;
		this.barcode_type = barcode_type;
		this.format = format;
	}

	get $wrapper() {
		return this.frm.fields_dict[this.fieldname]?.$wrapper;
	}

	get value() {
		return this.frm.doc[this.fieldname];
	}

	refresh() {
		this._render_preview();
	}

	_render_preview() {
		const $wrapper = this.$wrapper;
		if (!$wrapper) return;

		$wrapper.find(".barcode-field-preview").remove();

		if (!this.value) return;

		if (this.format === "QR") {
			this._render_qr($wrapper);
		} else {
			this._render_1d($wrapper);
		}
	}

	_make_container() {
		return $(`
			<div class="barcode-field-preview" style="margin-top:8px; display:flex; align-items:flex-end; gap:8px;">
				<div class="barcode-visual"></div>
				<button class="btn btn-xs btn-default btn-print-barcode" title="${__("Print Label")}" style="margin-bottom:4px;">
					<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24"
						fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16
							a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>
					</svg>
				</button>
			</div>
		`);
	}

	_render_qr($wrapper) {
		const $container = this._make_container();
		$wrapper.append($container);
		$container.find(".btn-print-barcode").on("click", () => this._open_print_dialog());

		frappe.call({
			method: "erpnext.manufacturing.doctype.scanner.scanner.render_qr_svg",
			args: { data: this.value },
			callback: (r) => {
				if (r.message) {
					$container.find(".barcode-visual").html(r.message);
				} else {
					$container.find(".barcode-visual").html(
						`<code>${frappe.utils.escape_html(this.value)}</code>`
					);
				}
			},
		});
	}

	_render_1d($wrapper) {
		const $container = this._make_container();
		$container.find(".barcode-visual").html('<svg class="barcode-svg"></svg>');
		$wrapper.append($container);
		$container.find(".btn-print-barcode").on("click", () => this._open_print_dialog());

		const draw = () => {
			try {
				JsBarcode($container.find(".barcode-svg")[0], this.value, {
					format: this.format,
					height: 50,
					displayValue: true,
					fontSize: 14,
					margin: 5,
				});
			} catch (e) {
				$container.find(".barcode-svg").replaceWith(`<code>${frappe.utils.escape_html(this.value)}</code>`);
			}
		};

		if (window.JsBarcode) {
			draw();
		} else {
			frappe.require("/assets/frappe/node_modules/jsbarcode/dist/JsBarcode.all.min.js", draw);
		}
	}

	_open_print_dialog() {
		frappe.call({
			method: "erpnext.manufacturing.doctype.label_template.label_template.get_templates_for_barcode_type",
			args: { barcode_type: this.barcode_type },
			callback: (r) => {
				const templates = r.message || [];
				if (!templates.length) {
					frappe.msgprint(__("No Label Templates configured for barcode type: {0}", [this.barcode_type]));
					return;
				}
				this._show_print_dialog(templates);
			},
		});
	}

	_show_print_dialog(templates) {
		const API_PRINTER = "erpnext.manufacturing.doctype.label_printer.label_printer";
		let _submitting = false;

		const _print_sequential = (job_names, dialog) => {
			let printed = 0, failed = 0;
			const total = job_names.length;

			const _finish = () => {
				frappe.hide_progress();
				_submitting = false;
				frappe.show_alert({
					message: __("{0} printed, {1} failed", [printed, failed]),
					indicator: failed ? "red" : "green",
				});
				dialog.hide();
			};

			const _print_one = (i) => {
				if (i >= job_names.length) { _finish(); return; }
				frappe.show_progress(__("Printing..."), i + 1, total);
				frappe.call({
					method: API_PRINTER + ".print_label",
					args: { print_job_name: job_names[i] },
					callback: (r) => {
						printed++;
						const delay = (r.message && r.message.print_delay_ms) || 1500;
						setTimeout(() => _print_one(i + 1), delay);
					},
					error: () => { failed++; _print_one(i + 1); },
				});
			};
			_print_one(0);
		};

		const _submit = (queue_only, dialog) => {
			if (_submitting) return;
			const tmpl = dialog.get_value("label_template");
			const printer = dialog.get_value("label_printer");
			const copies = dialog.get_value("copies") || 1;
			if (!tmpl) { frappe.msgprint(__("Please select a Label Template")); return; }

			_submitting = true;
			dialog.$wrapper.find(".btn-primary, .btn-secondary, .btn-default").prop("disabled", true);

			frappe.call({
				method: API_PRINTER + ".print_raw_label_batch",
				args: {
					value: this.value,
					label_template: tmpl,
					printer_name: printer || "",
					copies: copies,
				},
				callback: (r) => {
					const jobs = (r.message && r.message.jobs) || [];
					if (queue_only || !jobs.length) {
						_submitting = false;
						frappe.show_alert({ message: __("{0} jobs added to queue", [jobs.length]), indicator: "green" });
						dialog.hide();
						return;
					}
					_print_sequential(jobs, dialog);
				},
				error: () => {
					_submitting = false;
					dialog.$wrapper.find(".btn-primary, .btn-secondary, .btn-default").prop("disabled", false);
				},
			});
		};

		frappe.call({
			method: "frappe.client.get_list",
			args: { doctype: "Label Printer", filters: { is_enabled: 1 }, fields: ["name"], limit_page_length: 50 },
			callback: (pr) => {
				const printers = (pr.message || []).map(p => p.name);
				const tmpl_opts = templates.map(t => t.label_template);
				const default_printer = printers.length === 1 ? printers[0] : "";

				const dialog = new frappe.ui.Dialog({
					title: __("Print Label"),
					fields: [
						{
							fieldtype: "Select",
							fieldname: "label_template",
							label: __("Label Template"),
							options: tmpl_opts.join("\n"),
							default: tmpl_opts[0],
							reqd: 1,
						},
						{
							fieldtype: "Select",
							fieldname: "label_printer",
							label: __("Printer"),
							options: ["", ...printers].join("\n"),
							default: default_printer,
						},
						{
							fieldtype: "Int",
							fieldname: "copies",
							label: __("Copies"),
							default: 1,
						},
					],
					primary_action_label: __("Print Now"),
					primary_action: function () { _submit(false, dialog); },
					secondary_action_label: __("Add to Queue"),
					secondary_action: function () { _submit(true, dialog); },
				});

				dialog.show();
			},
		});
	}
};
