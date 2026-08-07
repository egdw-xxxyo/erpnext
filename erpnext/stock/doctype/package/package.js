frappe.ui.form.on("Package", {
	setup: function (frm) {
		frm.set_query("bpak", function () {
			return {
				filters: { docstatus: 1, status: ["!=", "Cancelled"] },
			};
		});
		frm.set_query("packing_template", function () {
			return { filters: { is_active: 1 } };
		});
	},

	bpak: function (frm) {
		frm._bpak_allowed_items = null;
	},

	refresh: function (frm) {
		setup_package_barcode(frm);
		setup_package_print_labels(frm);
		frm.events.setup_scanner(frm);

		if (frm.doc.docstatus === 1 && frm.doc.items) {
			let count = frm.doc.items.reduce((sum, r) => sum + (r.qty || 1), 0);
			frm.dashboard.add_indicator(__("{0} items packed", [count]), "blue");
		}

		if (frm.doc.shipment) {
			frm.dashboard.add_indicator(__("Shipment: {0}", [frm.doc.shipment]), "green");
		}

		if (frm.is_new() && frm.doc.bpak && frappe.route_options && frappe.route_options.bpak) {
			frm.set_df_property("bpak", "read_only", 1);
		}
		if (frm.doc.shipment) {
			frm.set_df_property("bpak", "read_only", 1);
		}
	},

	packing_template: function (frm) {
		if (!frm.doc.packing_template) return;

		frappe.model.with_doc("Packing Template", frm.doc.packing_template, function () {
			let tmpl = frappe.model.get_doc("Packing Template", frm.doc.packing_template);

			frm.set_value("box_template", tmpl.box_template);

			frm.doc.items = [];
			if (tmpl.items && tmpl.items.length) {
				tmpl.items.forEach(function (tmpl_row) {
					for (let i = 0; i < (tmpl_row.qty || 1); i++) {
						let row = frappe.model.add_child(frm.doc, "Package Item", "items");
						row.item_code = tmpl_row.item_code;
						row.item_name = tmpl_row.item_name;
						row.serial_no = "";
						row.qty = 1;
					}
				});
			}

			frm.refresh_fields("items");
			frm.dirty();
		});
	},

	box_barcode: function (frm) {
		frm._barcode_field && frm._barcode_field.refresh();
	},

	setup_scanner: function (frm) {
		if (frm.doc.docstatus !== 0) return;
		if (frm._scanner_added) return;
		frm._scanner_added = true;

		let wrapper = frm.fields_dict.items.wrapper;
		let $container = $(
			'<div class="packing-scanner-wrapper" style="margin-bottom: 15px;"></div>'
		).prependTo(wrapper);

		let scan_field = frappe.ui.form.make_control({
			df: {
				label: __("Scan Barcode"),
				fieldtype: "Data",
				options: "Barcode",
				placeholder: __("Scan serial number or box type barcode..."),
			},
			parent: $container,
			render_input: true,
		});
		scan_field.$wrapper.css("max-width", "400px");
		erpnext.utils.add_bulk_serial_button(scan_field.$wrapper.find(".control-input"), function (serial) {
			frm.events.process_scan(frm, serial);
		});

		scan_field.$input.on("input", function () {
			clearTimeout(frm._scan_timeout);
			frm._scan_timeout = setTimeout(function () {
				let value = scan_field.get_value();
				if (value) {
					frm.events.process_scan(frm, value);
					scan_field.set_value("");
				}
			}, 300);
		});
	},

	process_scan: function (frm, value) {
		value = value.trim();

		let bpak_name = null;
		frappe.call({
			method: "frappe.client.get_value",
			args: {
				doctype: "BpAK",
				filters: { serial_no: value, docstatus: 1 },
				fieldname: "name",
			},
			async: false,
			callback: function (r) {
				if (r.message && r.message.name) bpak_name = r.message.name;
			},
		});
		if (bpak_name) {
			if (frm.doc.bpak === bpak_name) {
				frappe.show_alert({
					message: __("BpAK already set: {0}", [bpak_name]),
					indicator: "orange",
				});
			} else if (frm.doc.bpak) {
				frappe.show_alert({
					message: __("BpAK already set to {0}", [frm.doc.bpak]),
					indicator: "orange",
				});
			} else {
				frm.set_value("bpak", bpak_name);
				frappe.show_alert({
					message: __("BpAK set: {0}", [bpak_name]),
					indicator: "green",
				});
				frappe.utils.play_sound("click");
			}
			return;
		}

		frappe.call({
			method: "frappe.client.get_value",
			args: {
				doctype: "Shipment Parcel Template",
				filters: { barcode: value },
				fieldname: "name",
			},
			async: false,
			callback: function (r) {
				if (r.message && r.message.name) {
					if (!frm.doc.box_template) {
						frm.set_value("box_template", r.message.name);
						frappe.show_alert({
							message: __("Box type set: {0}", [r.message.name]),
							indicator: "green",
						});
						frappe.utils.play_sound("click");
					} else {
						frappe.show_alert({
							message: __("Box type already set to {0}", [frm.doc.box_template]),
							indicator: "orange",
						});
					}
					return;
				}

				frappe.call({
					method: "erpnext.stock.utils.scan_barcode",
					args: { search_value: value },
					callback: function (r) {
						if (!r.message || !r.message.item_code) {
							frappe.show_alert({
								message: __("Not found: {0}", [value]),
								indicator: "red",
							});
							return;
						}

						let data = r.message;

						let tmpl_requires_bpak = false;
						if (frm.doc.packing_template) {
							let tmpl = frappe.get_doc("Packing Template", frm.doc.packing_template);
							tmpl_requires_bpak = !!(tmpl && tmpl.bpak_required);
						}
						if (tmpl_requires_bpak && !frm.doc.bpak) {
							frappe.show_alert({
								message: __("Select BpAK before scanning items."),
								indicator: "red",
							});
							return;
						}
						if (frm.doc.bpak) {
							let allowed = frm._bpak_allowed_items;
							if (!allowed) {
								let bpak_doc = null;
								frappe.call({
									method: "frappe.client.get",
									args: { doctype: "BpAK", name: frm.doc.bpak },
									async: false,
									callback: function (rr) {
										bpak_doc = rr.message;
									},
								});
								allowed = new Set(
									((bpak_doc && bpak_doc.planned_items) || []).map((r) => r.item_code)
								);
								frm._bpak_allowed_items = allowed;
							}
							if (allowed.size && !allowed.has(data.item_code)) {
								frappe.show_alert({
									message: __("Item {0} is not in BpAK {1}", [
										data.item_code,
										frm.doc.bpak,
									]),
									indicator: "red",
								});
								return;
							}
						}

						if (data.serial_no) {
							let exists = (frm.doc.items || []).some(
								(row) => row.serial_no === data.serial_no
							);
							if (exists) {
								frappe.show_alert({
									message: __("Serial No {0} already in this box", [data.serial_no]),
									indicator: "orange",
								});
								return;
							}
						}

						if (data.serial_no) {
							let empty_row = (frm.doc.items || []).find(
								(row) =>
									row.item_code === data.item_code && !row.serial_no && (row.qty || 1) <= 1
							);
							if (empty_row) {
								frappe.model.set_value(
									empty_row.doctype,
									empty_row.name,
									"serial_no",
									data.serial_no
								);
							} else {
								let row = frappe.model.add_child(frm.doc, "Package Item", "items");
								row.item_code = data.item_code;
								row.serial_no = data.serial_no;
								row.batch_no = data.batch_no || "";
								row.qty = 1;

								frappe.db.get_value("Item", data.item_code, "item_name", function (r) {
									if (r) row.item_name = r.item_name;
									frm.refresh_field("items");
								});
							}
						} else {
							let stack_row = (frm.doc.items || []).find(
								(row) => row.item_code === data.item_code && !row.serial_no
							);
							if (stack_row) {
								frappe.model.set_value(
									stack_row.doctype,
									stack_row.name,
									"qty",
									(stack_row.qty || 0) + 1
								);
							} else {
								let row = frappe.model.add_child(frm.doc, "Package Item", "items");
								row.item_code = data.item_code;
								row.serial_no = "";
								row.batch_no = data.batch_no || "";
								row.qty = 1;

								frappe.db.get_value("Item", data.item_code, "item_name", function (r) {
									if (r) row.item_name = r.item_name;
									frm.refresh_field("items");
								});
							}
						}

						frappe.show_alert({
							message: __("Added {0} ({1})", [data.item_code, data.serial_no || "no serial"]),
							indicator: "green",
						});
						frappe.utils.play_sound("click");

						frm.dirty();
						frm.refresh_field("items");
					},
				});
			},
		});
	},
});

function setup_package_print_labels(frm) {
	if (frm.is_new() || !frm.doc.packing_template) return;
	frappe.model.with_doc("Packing Template", frm.doc.packing_template, function () {
		let tmpl = frappe.model.get_doc("Packing Template", frm.doc.packing_template);
		if (!tmpl.label_template) return;
		frm.page.add_menu_item(__("Print Labels"), function () {
			erpnext.utils.open_simple_label_print_dialog({
				doctype: "Package",
				doc_name: frm.doc.name,
				label_templates: [{ label_template: tmpl.label_template, label_printer: tmpl.label_printer }],
				default_copies: tmpl.label_copies,
			});
		});
	});
}

function setup_package_barcode(frm) {
	if (!frm.fields_dict.box_barcode) return;

	if (!frm._barcode_field) {
		frm._barcode_field = new erpnext.BarcodeField({
			frm,
			fieldname: "box_barcode",
			barcode_type: "CODE128",
			format: "CODE128",
		});
	}
	frm._barcode_field.refresh();
}
