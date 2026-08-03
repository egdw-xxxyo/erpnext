// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

cur_frm.cscript.refresh = cur_frm.cscript.inspection_type;

frappe.ui.form.on("Quality Inspection", {
	onload(frm) {
		frm.trigger("set_default_company");
	},

	set_default_company(frm) {
		if (frm.doc.docstatus === 0 && !frm.doc.company) {
			frm.set_value("company", frappe.defaults.get_default("company"));
		}
	},

	setup: function (frm) {
		frm.set_query("reference_name", function (doc) {
			let filters = { docstatus: ["!=", 2] };

			if (doc.company) {
				filters["company"] = doc.company;
			}

			return {
				filters: filters,
			};
		});

		frm.set_query("batch_no", function () {
			return {
				filters: {
					item: frm.doc.item_code,
				},
			};
		});

		// Serial No based on item_code
		frm.set_query("item_serial_no", function () {
			let filters = {};
			if (frm.doc.item_code) {
				filters = {
					item_code: frm.doc.item_code,
				};
			}
			return { filters: filters };
		});

		// item code based on GRN/DN
		frm.set_query("item_code", function (doc) {
			let doctype = doc.reference_type;

			if (doc.reference_type !== "Job Card") {
				doctype =
					doc.reference_type == "Stock Entry" ? "Stock Entry Detail" : doc.reference_type + " Item";
			}

			if (doc.reference_type && doc.reference_name) {
				let filters = {
					from: doctype,
					inspection_type: doc.inspection_type,
				};

				if (doc.reference_type == doctype) filters["reference_name"] = doc.reference_name;
				else filters["parent"] = doc.reference_name;

				return {
					query: "erpnext.stock.doctype.quality_inspection.quality_inspection.item_query",
					filters: filters,
				};
			}
		});
	},

	refresh: function (frm) {
		// Ignore cancellation of reference doctype on cancel all.
		frm.ignore_doctypes_on_cancel_all = [frm.doc.reference_type, "Serial and Batch Bundle"];

		let has_serial = frm.doc.serial_inspections && frm.doc.serial_inspections.length;

		if (has_serial && frm.doc.item_code) {
			frm.events.show_spec_summary(frm);
		} else {
			// Restore readings grid visibility and remove summary
			let $rw = frm.fields_dict.readings.$wrapper;
			$rw.find(".qi-spec-summary").remove();
			$rw.find(".form-grid-container, .grid-footer, .clearfix, .small.form-clickable-section").show();
			let grid = frm.fields_dict.readings;
			if (grid && grid.grid) {
				let has_numeric = (frm.doc.readings || []).some(
					(r) => r.numeric && !r.formula_based_criteria
				);
				if (has_numeric) {
					let fm = grid.grid.fields_map;
					if (fm.min_value) fm.min_value.in_list_view = 1;
					if (fm.max_value) fm.max_value.in_list_view = 1;
					grid.grid.refresh();
				}
			}
		}

		// Add barcode scanner for serial_inspections
		if (has_serial) {
			frm.events.setup_serial_scanner(frm);
		}
	},

	show_spec_summary: function (frm) {
		let $wrapper = frm.fields_dict.readings.$wrapper;
		$wrapper.find(".qi-spec-summary").remove();

		// Hide the readings grid entirely
		$wrapper.find(".form-grid-container, .grid-footer, .clearfix, .small.form-clickable-section").hide();

		frappe.call({
			method: "erpnext.stock.doctype.item_specification.item_specification.get_spec_for_item",
			args: { item_code: frm.doc.item_code },
			callback: function (r) {
				if (!r.message) return;
				let spec = r.message;
				let params = Object.keys(spec)
					.map((key) => ({ parameter: key, ...spec[key] }))
					.filter((p) => p.calculated_value || p.value);
				if (!params.length) {
					return;
				}
				let rows = params
					.map((p) => {
						let val = "";
						if (p.calculated_value) {
							val = `${parseFloat(p.calculated_value)}`;
						} else if (p.value) {
							val = p.value;
						}
						if (val && p.uom) val += ` ${p.uom}`;
						return (
							`<tr><td style="padding:6px 12px;border-bottom:1px solid var(--border-color)">${frappe.utils.escape_html(
								p.parameter
							)}</td>` +
							`<td style="padding:6px 12px;border-bottom:1px solid var(--border-color);font-weight:500">${frappe.utils.escape_html(
								val
							)}</td></tr>`
						);
					})
					.join("");

				if (!rows) return;

				let html =
					`<div class="qi-spec-summary" style="margin-bottom:15px">` +
					`<table class="table table-bordered" style="max-width:500px;margin:0">` +
					`<thead><tr>` +
					`<th style="padding:6px 12px;background:var(--bg-light-gray)">${__("Parameter")}</th>` +
					`<th style="padding:6px 12px;background:var(--bg-light-gray)">${__("Value")}</th>` +
					`</tr></thead>` +
					`<tbody>${rows}</tbody></table></div>`;

				$wrapper.append(html);
			},
		});
	},

	setup_serial_scanner: function (frm) {
		if (frm._serial_scanner_added) return;
		frm._serial_scanner_added = true;

		let wrapper = frm.fields_dict.serial_inspections.wrapper;
		let $container = $(
			'<div class="serial-scanner-wrapper" style="margin-bottom: 15px;"></div>'
		).prependTo(wrapper);

		let scan_field = frappe.ui.form.make_control({
			df: {
				label: __("Scan Serial No"),
				fieldtype: "Data",
				options: "Barcode",
				placeholder: __("Scan serial number barcode..."),
			},
			parent: $container,
			render_input: true,
		});
		scan_field.$wrapper.css("max-width", "400px");

		scan_field.$input.on("input", () => {
			clearTimeout(frm._serial_scan_timeout);
			frm._serial_scan_timeout = setTimeout(() => {
				let value = scan_field.get_value();
				if (value) {
					frm.events.highlight_serial(frm, value);
					scan_field.set_value("");
				}
			}, 300);
		});

		if (!document.getElementById("serial-scanner-style")) {
			$(
				"<style id='serial-scanner-style'>" +
					".highlight-serial { background-color: #fef3cd !important; " +
					"box-shadow: 0 0 0 2px #ffc107; border-radius: 4px; transition: all 0.3s; }" +
					"</style>"
			).appendTo("head");
		}
	},

	highlight_serial: function (frm, value) {
		value = value.trim();
		let wrapper = frm.fields_dict.serial_inspections.wrapper;
		$(wrapper).find(".highlight-serial").removeClass("highlight-serial");

		let rows = frm.doc.serial_inspections || [];
		for (let i = 0; i < rows.length; i++) {
			if (rows[i].serial_no && rows[i].serial_no.toLowerCase() === value.toLowerCase()) {
				let grid = frm.fields_dict.serial_inspections.grid;
				let $row = $(grid.grid_rows[i].row);
				$row.addClass("highlight-serial");
				$row[0].scrollIntoView({ behavior: "smooth", block: "center" });

				// Mark as scanned without opening dialog (only if editable)
				if (!rows[i].scanned && frm.doc.docstatus === 0) {
					frappe.model.set_value(rows[i].doctype, rows[i].name, "scanned", 1);
					frm.dirty();
				}

				frappe.utils.play_sound("click");
				frappe.show_alert({
					message: __("Scanned: {0}", [value]),
					indicator: "green",
				});
				return;
			}
		}
		frappe.show_alert({ message: __("Serial No {0} not found", [value]), indicator: "red" });
	},

	item_code: function (frm) {
		if (frm.doc.item_code && !frm.doc.quality_inspection_template) {
			return frm.call({
				method: "get_quality_inspection_template",
				doc: frm.doc,
				callback: function () {
					refresh_field(["quality_inspection_template", "readings"]);
				},
			});
		}
	},

	quality_inspection_template: function (frm) {
		if (frm.doc.quality_inspection_template) {
			return frm.call({
				method: "get_item_specification_details",
				doc: frm.doc,
				callback: function () {
					refresh_field("readings");
				},
			});
		}
	},
});
