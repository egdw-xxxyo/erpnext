// Run with: node erpnext/buying/test_recurring_purchase.js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const handlers = {};
const element = { find: () => element, attr: () => element, append() {}, html() {} };
let payer = 1;
const context = {
	__: (text) => text,
	flt: (value, digits = 6) => Number(Number(value || 0).toFixed(digits)),
	cint: (value) => Number(value || 0),
	precision: () => 2,
	format_currency: String,
	locals: { "Recurring Purchase Item": {} },
	frappe: {
		ui: { form: { on: (doctype, events) => (handlers[doctype] = events) } },
		listview_settings: {},
		db: { get_value: async () => ({ message: { custom_is_vat_payer: payer } }) },
		meta: { get_field_precision: () => 2 },
		utils: { escape_html: String, icon: () => "" },
		datetime: { get_today: () => "2026-10-19", str_to_user: String },
	},
};
vm.createContext(context);
for (const file of ["recurring_purchase.js", "recurring_purchase_list.js"]) {
	vm.runInContext(
		fs.readFileSync(path.join(__dirname, "doctype/recurring_purchase", file), "utf8"),
		context
	);
}

async function run() {
	const format = context.frappe.listview_settings["Recurring Purchase"].formatters.valid_until;
	for (const [start, end, expected] of [
		["2026-10-20", "2026-10-31", "Not yet effective"],
		["2026-10-19", "2026-10-31", "Effective"],
		["2026-10-01", "2026-10-19", "Effective"],
		["2026-10-01", "2026-10-18", "Validity expired"],
	]) {
		assert.ok(format(end, {}, { valid_from: start }).includes(`>${expected}</span>`));
	}
	const fields = {};
	const row = { name: "row1", qty: 3, rate: 120 };
	context.locals["Recurring Purchase Item"].row1 = row;
	const frm = {
		doc: { supplier: "Supplier A", currency: "UAH", items: [row], workflow_state: "Чернетка" },
		is_new: () => true,
		refresh_field() {},
		refresh_fields() {},
		get_docfield: () => ({}),
		fields_dict: {
			vat_totals_html: { $wrapper: element },
			items: {
				df: { read_only: false },
				grid: {
					wrapper: element,
					reset_grid() {},
					update_docfield_property(name, property, value) {
						(fields[name] ||= {})[property] = value;
					},
				},
			},
		},
	};
	await handlers["Recurring Purchase"].supplier(frm);
	assert.equal(row.rate_excluding_vat, 100);
	assert.equal(frm.doc.grand_total, 360);
	assert.equal(frm.doc.net_total, 300);
	context.frappe.model = { set_value: async (cdt, cdn, field, value) => (row[field] = value) };
	row.rate_excluding_vat = 150;
	await handlers["Recurring Purchase Item"].rate_excluding_vat(frm, "Recurring Purchase Item", "row1");
	await handlers["Recurring Purchase Item"].rate(frm, "Recurring Purchase Item", "row1");
	assert.equal(row.rate, 180);
	assert.equal(frm.doc.grand_total, 540);
	assert.equal(frm.doc.net_total, 450);
	payer = 0;
	await handlers["Recurring Purchase"].supplier(frm);
	assert.equal(frm.doc.net_total, 540);
	assert.equal(fields.rate_excluding_vat.hidden, true);
	frm.doc.docstatus = 1;
	frm.doc.workflow_state = "Проведено";
	frm.doc.supplier_vat_pricing = 1;
	frm.fields_dict.items.df.read_only = true;
	frm.doc.net_total = 450;
	await handlers["Recurring Purchase"].supplier(frm);
	assert.equal(frm.doc.net_total, 450, "Approved totals must stay frozen");
	assert.equal(fields.rate_excluding_vat.read_only, true);
	process.stdout.write(
		"Recurring purchase: validity boundaries, VAT inputs, supplier switch and locked totals passed.\n"
	);
}
run().catch((error) => {
	process.stderr.write(`${error.stack}\n`);
	process.exitCode = 1;
});
