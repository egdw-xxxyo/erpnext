// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

cur_frm.add_fetch("customer", "customer_name", "customer_name");
cur_frm.add_fetch("supplier", "supplier_name", "supplier_name");

cur_frm.add_fetch("item_code", "item_name", "item_name");
cur_frm.add_fetch("item_code", "description", "description");
cur_frm.add_fetch("item_code", "item_group", "item_group");
cur_frm.add_fetch("item_code", "brand", "brand");

cur_frm.cscript.onload = function () {
	cur_frm.set_query("item_code", function () {
		return erpnext.queries.item({ is_stock_item: 1, has_serial_no: 1 });
	});
};

frappe.ui.form.on("Serial No", "refresh", function (frm) {
	frm.toggle_enable("item_code", frm.doc.__islocal);
});

frappe.ui.form.on("Serial No", {
	refresh(frm) {
		frm.trigger("view_ledgers");
		frm.trigger("add_print_labels_button");
	},

	view_ledgers(frm) {
		frm.add_custom_button(__("View Ledgers"), () => {
			frappe.route_options = {
				item_code: frm.doc.item_code,
				serial_no: frm.doc.name,
				posting_date: frappe.datetime.now_date(),
				posting_time: frappe.datetime.now_time(),
			};
			frappe.set_route("query-report", "Serial No Ledger");
		});
	},

	add_print_labels_button(frm) {
		if (!frm.doc.item_code || frm.doc.__islocal) return;
		frappe.call({
			method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt_utils.get_label_templates_for_items",
			args: { item_codes: JSON.stringify([frm.doc.item_code]) },
			callback: function (r) {
				let templates_by_item = r.message || {};
				if (!templates_by_item[frm.doc.item_code] || !templates_by_item[frm.doc.item_code].length) return;
				frm.page.add_menu_item(__("Print Labels"), function () {
					let by_item = {};
					by_item[frm.doc.item_code] = {
						item_name: frm.doc.item_name || frm.doc.item_code,
						serials: [frm.doc.name],
					};
					erpnext.utils.open_label_print_dialog({
						by_item: by_item,
						templates_by_item: templates_by_item,
						items: [frm.doc.item_code],
					});
				});
			},
		});
	},
});
