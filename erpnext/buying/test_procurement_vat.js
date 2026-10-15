// Run with: node erpnext/buying/test_procurement_vat.js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const handlers = {};
const context = {
	erpnext: { procurement_vat: {} },
	frappe: {
		provide() {},
		ui: {
			form: {
				on(doctype, events) {
					handlers[doctype] = events;
				},
			},
		},
	},
	flt: (value, precision) => {
		const number = Number(value) || 0;
		return precision == null ? number : Number(number.toFixed(precision));
	},
	cint: (value) => parseInt(value, 10) || 0,
};
vm.createContext(context);
vm.runInContext(
	fs.readFileSync(path.join(__dirname, "../public/js/custom/procurement_vat.js"), "utf8"),
	context
);
const calculate = context.erpnext.procurement_vat.calculate;
const suppliers = { payer: { custom_is_vat_payer: 1 }, other: { custom_is_vat_payer: "0" } };
let result = calculate(
	[
		{ supplier: "payer", qty: 5, rate: 207.6 },
		{ supplier: "other", qty: 2, rate: 100 },
	],
	suppliers
);
assert.equal(result.gross, 1238);
assert.equal(result.net, 1065);
assert.equal(result.vat, 173);
assert.equal(result.groups.other.vat, 0);
result = calculate([{ supplier: "payer", qty: 1, rate: 8496 }], suppliers);
assert.equal(result.net, 7080);
assert.equal(result.vat, 1416);
assert.equal(calculate([], suppliers).gross, 0);
result = calculate([{ supplier: "payer", qty: 1, rate: 0.01 }], suppliers);
assert.equal(result.net + result.vat, result.gross);
assert.equal(calculate([{ supplier: "__proto__", qty: 1, rate: 10 }], {}).gross, 10);
process.stdout.write("VAT totals: mixed suppliers, PDF 804 totals, empty rows and rounding passed.\n");

async function testEditing() {
	const doctype = "Consolidated Purchase Order Item";
	const row = { name: "row1", supplier: "payer", qty: 2, rate: 120, custom_rate_excluding_vat: 100 };
	context.locals = { [doctype]: { row1: row } };
	context.__ = (text) => text;
	context.format_currency = (value) => String(value);
	context.erpnext.entity = { html: ({ name }) => name };
	context.frappe.utils = { escape_html: (value) => String(value), icon: () => "<svg></svg>" };
	const element = {
		find: () => element,
		attr: () => element,
		css: () => element,
		html: () => element,
		appendTo: () => element,
		remove() {},
	};
	context.$ = () => element;
	context.frappe.meta = { get_field_precision: () => 2, get_docfield: () => ({}) };
	context.frappe.db = {
		get_list: async () => Object.entries(suppliers).map(([name, data]) => ({ name, ...data })),
	};
	context.frappe.model = {
		set_value: async (dt, name, field, value) => {
			row[field] = value;
		},
	};
	const visibility = [];
	const frm = {
		doc: { items: [row], currency: "UAH" },
		fields_dict: {
			custom_vat_totals: { $wrapper: { html() {} } },
			items: {
				grid: {
					update_docfield_property(field, property, value) {
						if (field === "custom_rate_excluding_vat" && property === "hidden")
							visibility.push(value);
					},
					reset_grid() {},
					wrapper: { find: () => element },
				},
			},
		},
		refresh_field() {},
		set_df_property() {},
		get_docfield: () => ({}),
		async set_value(field, value) {
			this.doc[field] = value;
		},
	};
	await handlers[doctype].custom_rate_excluding_vat(frm, doctype, "row1");
	assert.equal(row.rate, 120);
	row.rate = 240;
	await handlers[doctype].rate(frm);
	assert.equal(row.custom_rate_excluding_vat, 200);
	row.supplier = "other";
	await handlers[doctype].supplier(frm);
	assert.equal(row.custom_rate_excluding_vat, 240);
	assert.deepEqual(visibility, [0, 1]);
	row.custom_rate_excluding_vat = 75;
	await handlers[doctype].custom_rate_excluding_vat(frm, doctype, "row1");
	assert.equal(row.rate, 75);
	frm.doc.items = [];
	await handlers[doctype].items_remove(frm);
	assert.equal(frm.doc.grand_total, 0);
	assert.equal(frm.doc.total_qty, 0);
	process.stdout.write(
		"VAT editing: both directions, supplier changes, column visibility and removal passed.\n"
	);
}
testEditing().catch((error) => {
	process.stderr.write(String(error));
	process.exitCode = 1;
});
