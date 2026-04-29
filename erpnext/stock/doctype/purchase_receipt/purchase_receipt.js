// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("erpnext.stock");

cur_frm.cscript.tax_table = "Purchase Taxes and Charges";

erpnext.accounts.taxes.setup_tax_filters("Purchase Taxes and Charges");
erpnext.accounts.taxes.setup_tax_validations("Purchase Receipt");
erpnext.buying.setup_buying_controller();

frappe.ui.form.on("Purchase Receipt", {
	setup: (frm) => {
		frm.custom_make_buttons = {
			"Stock Entry": "Return",
			"Purchase Invoice": "Purchase Invoice",
			"Landed Cost Voucher": "Landed Cost Voucher",
		};

		frm.set_query("wip_composite_asset", "items", function () {
			return {
				filters: { is_composite_asset: 1, docstatus: 0 },
			};
		});

		frm.set_query("taxes_and_charges", function () {
			return {
				filters: { company: frm.doc.company },
			};
		});
	},
	onload: function (frm) {
		erpnext.queries.setup_queries(frm, "Warehouse", function () {
			return erpnext.queries.warehouse(frm.doc);
		});

		// Auto-reload if server data is newer (e.g. after QI submit updated quantities)
		if (frm.doc.name && !frm.doc.__islocal) {
			frappe.call({
				method: "frappe.client.get_value",
				args: { doctype: "Purchase Receipt", filters: frm.doc.name, fieldname: "modified" },
				callback: function (r) {
					if (r.message && r.message.modified !== frm.doc.modified) {
						frm.reload_doc();
					}
				},
			});
		}
	},

	after_save: function (frm) {
		if (frm.doc.docstatus !== 0) return;
		let has_unbundled = (frm.doc.items || []).some(item => !item.serial_and_batch_bundle);
		if (!has_unbundled) return;
		frappe.call({
			method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt_utils.generate_serial_numbers_for_pr",
			args: { purchase_receipt_name: frm.doc.name },
			callback: function (r) {
				if (r.message && r.message.length) {
					frm.reload_doc();
				}
			},
		});
	},

	refresh: function (frm) {
		if (frm.doc.company) {
			frm.trigger("toggle_display_account_head");
		}

		if (frm.doc.docstatus === 0) {
			let has_serial_items = (frm.doc.items || []).some(item => item.serial_and_batch_bundle);
			if (has_serial_items) {
				frm.page.add_menu_item(__("Print Labels"), function () {
					frm.events.print_serial_labels(frm);
				});
			}
		}

		if (frm.doc.name && !frm.doc.is_new && frm.doc.docstatus !== 2) {
			frm.add_custom_button(__("Scan Package"), function () {
				frappe.prompt(
					{ label: __("Package or Barcode"), fieldname: "package", fieldtype: "Data", reqd: 1 },
					function (values) {
						frappe.call({
							method: "erpnext.stock.doctype.package.package.add_package_to_purchase_receipt",
							args: { package_name: values.package, purchase_receipt: frm.doc.name },
							callback: function (r) {
								if (r.message) {
									frappe.show_alert({ message: r.message.message, indicator: "green" });
									frm.reload_doc();
								}
							},
						});
					},
					__("Scan Package"),
					__("Add")
				);
			}, __("Create"));
		}

		// Show button to navigate to linked Quality Inspections
		if (frm.doc.name && !frm.doc.name.startsWith("new-")) {
			frappe.call({
				method: "frappe.client.get_list",
				args: {
					doctype: "Quality Inspection",
					filters: { reference_name: frm.doc.name, reference_type: "Purchase Receipt", docstatus: ["!=", 2] },
					fields: ["name", "item_code", "status", "docstatus"],
					order_by: "creation desc",
				},
				callback: function (r) {
					if (r.message && r.message.length) {
						let qis = r.message;
						if (qis.length === 1) {
							let qi = qis[0];
							let indicator = qi.docstatus === 1
								? (qi.status === "Accepted" ? "green" : "red")
								: "orange";
							let label = qi.docstatus === 1
								? __("Quality Inspection") + ": " + __(qi.status)
								: __("Quality Inspection") + " (" + __("Draft") + ")";
							frm.dashboard.add_indicator(label, indicator);
							frm.add_custom_button(
								__("Quality Inspection"),
								function () {
									frappe.set_route("Form", "Quality Inspection", qi.name);
								},
								__("View")
							);
						} else {
							let submitted = qis.filter(q => q.docstatus === 1);
							let draft = qis.filter(q => q.docstatus === 0);
							if (submitted.length) {
								let all_accepted = submitted.every(q => q.status === "Accepted");
								frm.dashboard.add_indicator(
									__("Quality Inspections") + ": " + submitted.length + " " + (all_accepted ? __("Accepted") : __("Mixed")),
									all_accepted ? "green" : "orange"
								);
							}
							if (draft.length) {
								frm.dashboard.add_indicator(
									__("Quality Inspections") + ": " + draft.length + " " + __("Draft"),
									"orange"
								);
							}
							frm.add_custom_button(
								__("Quality Inspections"),
								function () {
									frappe.set_route("List", "Quality Inspection", {
										reference_name: frm.doc.name,
										reference_type: "Purchase Receipt",
									});
								},
								__("View")
							);
						}
					}
				},
			});
		}

		// Create QI button — works on both draft and submitted PRs
		if (frm.doc.name && !frm.doc.__islocal) {
			let items_needing_qi = (frm.doc.items || []).filter(
				item => item.serial_and_batch_bundle && !item.quality_inspection
			);
			if (items_needing_qi.length) {
				frm.add_custom_button(
					__("Quality Inspection"),
					function () {
						if (items_needing_qi.length === 1) {
							let item = items_needing_qi[0];
							frappe.new_doc("Quality Inspection", {
								inspection_type: "Incoming",
								reference_type: "Purchase Receipt",
								reference_name: frm.doc.name,
								item_code: item.item_code,
								item_name: item.item_name,
								sample_size: item.qty,
								company: frm.doc.company,
								child_row_reference: item.name,
							});
						} else {
							// Multiple items — let user pick
							let options = items_needing_qi.map(i => i.item_code);
							frappe.prompt(
								[{
									label: __("Item"),
									fieldname: "item_code",
									fieldtype: "Select",
									options: options.join("\n"),
									reqd: 1,
								}],
								function (values) {
									let item = items_needing_qi.find(i => i.item_code === values.item_code);
									frappe.new_doc("Quality Inspection", {
										inspection_type: "Incoming",
										reference_type: "Purchase Receipt",
										reference_name: frm.doc.name,
										item_code: item.item_code,
										item_name: item.item_name,
										sample_size: item.qty,
										company: frm.doc.company,
										child_row_reference: item.name,
									});
								},
								__("Select Item for Quality Inspection"),
								__("Create")
							);
						}
					},
					__("Create")
				);
			}
		}

		if (frm.doc.docstatus === 1 && frm.doc.is_return === 1 && frm.doc.per_billed !== 100) {
			frm.add_custom_button(
				__("Debit Note"),
				function () {
					frappe.model.open_mapped_doc({
						method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice",
						frm: cur_frm,
					});
				},
				__("Create")
			);
			frm.page.set_inner_btn_group_as_primary(__("Create"));
		}

		if (frm.doc.docstatus === 1 && frm.doc.is_internal_supplier && !frm.doc.inter_company_reference) {
			frm.add_custom_button(
				__("Delivery Note"),
				function () {
					frappe.model.open_mapped_doc({
						method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_inter_company_delivery_note",
						frm: cur_frm,
					});
				},
				__("Create")
			);
		}

		if (frm.doc.docstatus === 0) {
			if (!frm.doc.is_return) {
				frappe.db.get_single_value("Buying Settings", "maintain_same_rate").then((value) => {
					if (value) {
						frm.doc.items.forEach((item) => {
							frm.fields_dict.items.grid.update_docfield_property(
								"rate",
								"read_only",
								item.purchase_order && item.purchase_order_item
							);
						});
					}
				});
			}
		}

		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(
				__("Landed Cost Voucher"),
				() => {
					frm.events.make_lcv(frm);
				},
				__("Create")
			);
		}

		frm.events.add_custom_buttons(frm);
	},

	make_lcv(frm) {
		frappe.call({
			method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_lcv",
			args: {
				doctype: frm.doc.doctype,
				docname: frm.doc.name,
			},
			callback: (r) => {
				if (r.message) {
					var doc = frappe.model.sync(r.message);
					frappe.set_route("Form", doc[0].doctype, doc[0].name);
				}
			},
		});
	},

	add_custom_buttons: function (frm) {
		if (frm.doc.docstatus == 0) {
			frm.add_custom_button(
				__("Purchase Invoice"),
				function () {
					if (!frm.doc.supplier) {
						frappe.throw({
							title: __("Mandatory"),
							message: __("Please Select a Supplier"),
						});
					}
					erpnext.utils.map_current_doc({
						method: "erpnext.accounts.doctype.purchase_invoice.purchase_invoice.make_purchase_receipt",
						source_doctype: "Purchase Invoice",
						target: frm,
						setters: {
							supplier: frm.doc.supplier,
						},
						get_query_filters: {
							docstatus: 1,
							per_received: ["<", 100],
							company: frm.doc.company,
							update_stock: 0,
						},
						allow_child_item_selection: true,
						child_fieldname: "items",
						child_columns: ["item_code", "item_name", "qty", "received_qty"],
					});
				},
				__("Get Items From")
			);
		}
	},

	print_serial_labels: function (frm) {
		frappe.call({
			method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt_utils.get_serial_numbers_for_pr",
			args: { purchase_receipt_name: frm.doc.name },
			callback: function (r) {
				if (!r.message || !r.message.length) {
					frappe.msgprint(__("No serial numbers found"));
					return;
				}
				let by_item = {};
				r.message.forEach(s => {
					if (!by_item[s.item_code]) by_item[s.item_code] = { item_name: s.item_name, serials: [] };
					by_item[s.item_code].serials.push(s.serial_no);
				});
				let item_codes = Object.keys(by_item);
				frappe.call({
					method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt_utils.get_label_templates_for_items",
					args: { item_codes: JSON.stringify(item_codes) },
					callback: function (lr) {
						let templates_by_item = lr.message || {};
						let items = item_codes.filter(c => templates_by_item[c] && templates_by_item[c].length);
						if (!items.length) {
							frappe.msgprint(__("No items have label templates configured"));
							return;
						}
						erpnext.utils.open_label_print_dialog({ by_item, templates_by_item, items });
					},
				});
			},
		});
	},

	company: function (frm) {
		frm.trigger("toggle_display_account_head");
		erpnext.accounts.dimensions.update_dimension(frm, frm.doctype);
	},

	toggle_display_account_head: function (frm) {
		var enabled = erpnext.is_perpetual_inventory_enabled(frm.doc.company);
		frm.fields_dict["items"].grid.set_column_disp(["cost_center"], enabled);
	},
});

erpnext.stock.PurchaseReceiptController = class PurchaseReceiptController extends (
	erpnext.buying.BuyingController
) {
	setup(doc) {
		this.setup_accounting_dimension_triggers();
		this.setup_posting_date_time_check();
		super.setup(doc);

		this.frm.set_query("expense_account", "items", () => {
			return {
				query: "erpnext.controllers.queries.get_expense_account",
				filters: {
					company: this.frm.doc.company,
					disabled: 0,
				},
			};
		});
	}

	refresh() {
		var me = this;
		super.refresh();

		erpnext.accounts.ledger_preview.show_accounting_ledger_preview(this.frm);
		erpnext.accounts.ledger_preview.show_stock_ledger_preview(this.frm);

		if (this.frm.doc.docstatus > 0) {
			this.show_stock_ledger();
			//removed for temporary
			this.show_general_ledger();

			this.frm.add_custom_button(
				__("Asset"),
				function () {
					frappe.route_options = {
						purchase_receipt: me.frm.doc.name,
					};
					frappe.set_route("List", "Asset");
				},
				__("View")
			);

			this.frm.add_custom_button(
				__("Asset Movement"),
				function () {
					frappe.route_options = {
						reference_name: me.frm.doc.name,
					};
					frappe.set_route("List", "Asset Movement");
				},
				__("View")
			);
		}

		if (!this.frm.doc.is_return && this.frm.doc.status != "Closed") {
			if (this.frm.doc.docstatus == 0) {
				this.frm.add_custom_button(
					__("Purchase Order"),
					function () {
						if (!me.frm.doc.supplier) {
							frappe.throw({
								title: __("Mandatory"),
								message: __("Please Select a Supplier"),
							});
						}
						erpnext.utils.map_current_doc({
							method: "erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_receipt",
							source_doctype: "Purchase Order",
							target: me.frm,
							setters: {
								supplier: me.frm.doc.supplier,
								schedule_date: undefined,
							},
							get_query_filters: {
								docstatus: 1,
								status: ["not in", ["Closed", "On Hold"]],
								per_received: ["<", 99.99],
								company: me.frm.doc.company,
							},
							allow_child_item_selection: true,
							child_fieldname: "items",
							child_columns: ["item_code", "item_name", "qty", "received_qty"],
						});
					},
					__("Get Items From")
				);
			}

			if (this.frm.doc.docstatus == 1 && this.frm.doc.status != "Closed") {
				if (this.frm.has_perm("submit")) {
					cur_frm.add_custom_button(__("Close"), this.close_purchase_receipt, __("Status"));
				}

				cur_frm.add_custom_button(__("Purchase Return"), this.make_purchase_return, __("Create"));

				cur_frm.add_custom_button(
					__("Make Stock Entry"),
					cur_frm.cscript["Make Stock Entry"],
					__("Create")
				);

				if (flt(this.frm.doc.per_billed) < 100) {
					cur_frm.add_custom_button(
						__("Purchase Invoice"),
						this.make_purchase_invoice,
						__("Create")
					);
				}
				cur_frm.add_custom_button(
					__("Retention Stock Entry"),
					this.make_retention_stock_entry,
					__("Create")
				);

				cur_frm.page.set_inner_btn_group_as_primary(__("Create"));
			}
		}

		if (this.frm.doc.docstatus == 1 && this.frm.doc.status === "Closed" && this.frm.has_perm("submit")) {
			cur_frm.add_custom_button(__("Reopen"), this.reopen_purchase_receipt, __("Status"));
		}

		this.frm.toggle_reqd("supplier_warehouse", this.frm.doc.is_old_subcontracting_flow);
	}

	make_purchase_invoice() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice",
			frm: cur_frm,
		});
	}

	make_purchase_return() {
		let me = this;

		let has_rejected_items = cur_frm.doc.items.filter((item) => {
			if (item.rejected_qty > 0) {
				return true;
			}
		});

		if (has_rejected_items && has_rejected_items.length > 0) {
			frappe.prompt(
				[
					{
						label: __("Return Qty from Rejected Warehouse"),
						fieldtype: "Check",
						fieldname: "return_for_rejected_warehouse",
						default: 1,
					},
				],
				function (values) {
					if (values.return_for_rejected_warehouse) {
						frappe.call({
							method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_return_against_rejected_warehouse",
							args: {
								source_name: cur_frm.doc.name,
							},
							callback: function (r) {
								if (r.message) {
									frappe.model.sync(r.message);
									frappe.set_route("Form", r.message.doctype, r.message.name);
								}
							},
						});
					} else {
						cur_frm.cscript._make_purchase_return();
					}
				},
				__("Return Qty"),
				__("Make Return Entry")
			);
		} else {
			cur_frm.cscript._make_purchase_return();
		}
	}

	close_purchase_receipt() {
		cur_frm.cscript.update_status("Closed");
	}

	reopen_purchase_receipt() {
		cur_frm.cscript.update_status("Submitted");
	}

	make_retention_stock_entry() {
		frappe.call({
			method: "erpnext.stock.doctype.stock_entry.stock_entry.move_sample_to_retention_warehouse",
			args: {
				company: cur_frm.doc.company,
				items: cur_frm.doc.items,
			},
			callback: function (r) {
				if (r.message) {
					var doc = frappe.model.sync(r.message)[0];
					frappe.set_route("Form", doc.doctype, doc.name);
				} else {
					frappe.msgprint(
						__("Purchase Receipt doesn't have any Item for which Retain Sample is enabled.")
					);
				}
			},
		});
	}

	apply_putaway_rule() {
		if (this.frm.doc.apply_putaway_rule) erpnext.apply_putaway_rule(this.frm);
	}
};

// for backward compatibility: combine new and previous states
extend_cscript(cur_frm.cscript, new erpnext.stock.PurchaseReceiptController({ frm: cur_frm }));

cur_frm.cscript.update_status = function (status) {
	frappe.ui.form.is_saving = true;
	frappe.call({
		method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.update_purchase_receipt_status",
		args: { docname: cur_frm.doc.name, status: status },
		callback: function (r) {
			if (!r.exc) cur_frm.reload_doc();
		},
		always: function () {
			frappe.ui.form.is_saving = false;
		},
	});
};

cur_frm.fields_dict["items"].grid.get_field("project").get_query = function (doc, cdt, cdn) {
	return {
		filters: [["Project", "status", "not in", "Completed, Cancelled"]],
	};
};

cur_frm.fields_dict["select_print_heading"].get_query = function (doc, cdt, cdn) {
	return {
		filters: [["Print Heading", "docstatus", "!=", "2"]],
	};
};

cur_frm.fields_dict["items"].grid.get_field("bom").get_query = function (doc, cdt, cdn) {
	var d = locals[cdt][cdn];
	return {
		filters: [
			["BOM", "item", "=", d.item_code],
			["BOM", "is_active", "=", "1"],
			["BOM", "docstatus", "=", "1"],
		],
	};
};

frappe.provide("erpnext.buying");

frappe.ui.form.on("Purchase Receipt", "is_subcontracted", function (frm) {
	if (frm.doc.is_old_subcontracting_flow) {
		erpnext.buying.get_default_bom(frm);
	}

	frm.toggle_reqd("supplier_warehouse", frm.doc.is_old_subcontracting_flow);
});

frappe.ui.form.on("Purchase Receipt Item", {
	item_code: function (frm, cdt, cdn) {
		var d = locals[cdt][cdn];
		frappe.db.get_value("Item", { name: d.item_code }, "sample_quantity", (r) => {
			frappe.model.set_value(cdt, cdn, "sample_quantity", r.sample_quantity);
			validate_sample_quantity(frm, cdt, cdn);
		});
	},
	qty: function (frm, cdt, cdn) {
		validate_sample_quantity(frm, cdt, cdn);
	},
	sample_quantity: function (frm, cdt, cdn) {
		validate_sample_quantity(frm, cdt, cdn);
	},
	batch_no: function (frm, cdt, cdn) {
		validate_sample_quantity(frm, cdt, cdn);
	},
});

cur_frm.cscript._make_purchase_return = function () {
	frappe.model.open_mapped_doc({
		method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_return",
		frm: cur_frm,
	});
};

cur_frm.cscript["Make Stock Entry"] = function () {
	frappe.model.open_mapped_doc({
		method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_stock_entry",
		frm: cur_frm,
	});
};

var validate_sample_quantity = function (frm, cdt, cdn) {
	var d = locals[cdt][cdn];
	if (d.sample_quantity && d.qty) {
		frappe.call({
			method: "erpnext.stock.doctype.stock_entry.stock_entry.validate_sample_quantity",
			args: {
				batch_no: d.batch_no,
				item_code: d.item_code,
				sample_quantity: d.sample_quantity,
				qty: d.qty,
			},
			callback: (r) => {
				frappe.model.set_value(cdt, cdn, "sample_quantity", r.message);
			},
		});
	}
};
