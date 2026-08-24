// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.query_reports["Stock Ledger"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "warehouse",
			label: __("Warehouses"),
			fieldtype: "MultiSelectList",
			options: "Warehouse",
			get_data: function (txt) {
				const company = frappe.query_report.get_filter_value("company");

				return frappe.db.get_link_options("Warehouse", txt, {
					company: company,
				});
			},
		},
		{
			fieldname: "item_code",
			label: __("Items"),
			fieldtype: "MultiSelectList",
			options: "Item",
			get_data: async function (txt) {
				let { message: data } = await frappe.call({
					method: "erpnext.controllers.queries.item_query",
					args: {
						doctype: "Item",
						txt: txt,
						searchfield: "name",
						start: 0,
						page_len: 10,
						filters: {},
						as_dict: 1,
					},
				});
				data = data.map(({ name, ...rest }) => {
					return {
						value: name,
						description: Object.values(rest),
					};
				});

				return data || [];
			},
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{
			fieldname: "batch_no",
			label: __("Batch No"),
			fieldtype: "Link",
			options: "Batch",
			on_change() {
				const batch_no = frappe.query_report.get_filter_value("batch_no");
				if (batch_no) {
					frappe.query_report.set_filter_value("segregate_serial_batch_bundle", 1);
				} else {
					frappe.query_report.set_filter_value("segregate_serial_batch_bundle", 0);
				}
			},
		},
		{
			fieldname: "brand",
			label: __("Brand"),
			fieldtype: "Link",
			options: "Brand",
		},
		{
			fieldname: "voucher_no",
			label: __("Voucher #"),
			fieldtype: "Data",
		},
		{
			fieldname: "project",
			label: __("Project"),
			fieldtype: "Link",
			options: "Project",
		},
		{
			fieldname: "include_uom",
			label: __("Include UOM"),
			fieldtype: "Link",
			options: "UOM",
		},
		{
			fieldname: "valuation_field_type",
			label: __("Valuation Field Type"),
			fieldtype: "Select",
			width: "80",
			options: "Currency\nFloat",
			default: "Currency",
		},
		{
			fieldname: "segregate_serial_batch_bundle",
			label: __("Segregate Serial / Batch Bundle"),
			fieldtype: "Check",
			default: 0,
		},
	],
	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname == "out_qty" && data && data.out_qty < 0) {
			value = "<span style='color:red'>" + value + "</span>";
		} else if (column.fieldname == "in_qty" && data && data.in_qty > 0) {
			value = "<span style='color:green'>" + value + "</span>";
		}

		return value;
	},

	after_datatable_render: function () {
		const report = frappe.query_report;
		report.$summary && report.$summary.empty().hide();
		report.stock_ledger_totals_shown = false;
		erpnext.stock_ledger_watch_datatable(report);
	},

	onload: function (report) {
		report.page.add_inner_button(__("View Stock Balance"), function () {
			var filters = report.get_values();
			frappe.set_route("query-report", "Stock Balance", filters);
		});

		report.page.add_inner_button(__("Calculate Totals"), function () {
			erpnext.stock_ledger_watch_datatable(report);
			erpnext.stock_ledger_totals(report);
		});
	},
};

erpnext.stock_ledger_visible_rows = function (report) {
	const data = report.data || [];
	const datatable = report.datatable;

	if (!datatable || !datatable.datamanager || !datatable.datamanager.rowViewOrder) {
		return data.filter((row) => row && row.voucher_no);
	}

	const visible_indices = (datatable.bodyRenderer || {}).visibleRowIndices;

	return datatable.datamanager.rowViewOrder
		.filter((index) => !visible_indices || visible_indices.includes(index))
		.map((index) => data[index])
		.filter((row) => row && row.voucher_no);
};

erpnext.stock_ledger_totals = function (report, silent) {
	const rows = erpnext.stock_ledger_visible_rows(report);
	const total_rows = (report.data || []).filter((row) => row && row.voucher_no).length;

	if (!rows.length) {
		if (!silent) {
			frappe.msgprint(__("No rows to calculate."));
		}
		return;
	}

	let in_qty = 0;
	let out_qty = 0;
	let value_change = 0;

	rows.forEach((row) => {
		in_qty += flt(row.in_qty);
		out_qty += flt(row.out_qty);
		value_change += flt(row.stock_value_difference);
	});

	const currency = erpnext.get_currency(report.get_filter_value("company"));
	const rows_label = rows.length < total_rows ? __("Rows (filtered)") : __("Rows");

	const summary = [
		{ label: __("In Qty"), value: in_qty, datatype: "Float", indicator: "Green" },
		{ label: __("Out Qty"), value: out_qty, datatype: "Float", indicator: "Red" },
		{ label: __("Qty Change"), value: in_qty + out_qty, datatype: "Float" },
		{ label: __("Value Change"), value: value_change, datatype: "Currency", currency: currency },
		{ label: rows_label, value: rows.length, datatype: "Int" },
	];

	report.$summary.empty();
	summary.forEach((item) => frappe.utils.build_summary_item(item).appendTo(report.$summary));
	report.$summary.show();
	report.stock_ledger_totals_shown = true;
};

erpnext.stock_ledger_watch_datatable = function (report) {
	const datamanager = report.datatable && report.datatable.datamanager;
	if (!datamanager || datamanager._stock_ledger_totals_patched) {
		return;
	}
	datamanager._stock_ledger_totals_patched = true;

	const recalculate = frappe.utils.debounce(() => {
		if (report.stock_ledger_totals_shown) {
			erpnext.stock_ledger_totals(report, true);
		}
	}, 200);

	["filterRows", "sortRows", "sortColumn"].forEach((method) => {
		const original = datamanager[method];
		if (typeof original !== "function") {
			return;
		}
		datamanager[method] = function (...args) {
			const out = original.apply(this, args);
			Promise.resolve(out).then(recalculate, recalculate);
			return out;
		};
	});
};

erpnext.utils.add_inventory_dimensions("Stock Ledger", 10);
