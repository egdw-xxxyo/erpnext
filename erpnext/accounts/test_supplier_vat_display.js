// Run with: node erpnext/accounts/test_supplier_vat_display.js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const handlers = {};
const element = {
	find: () => element,
	attr: () => element,
	css: () => element,
	html: () => element,
	appendTo: () => element,
	remove() {},
	empty() {},
};
let response;
const context = {
	__: (text) => text,
	$: () => element,
	format_currency: String,
	frappe: {
		ui: { form: { on: (doctype, events) => (handlers[doctype] = events) } },
		call: async () => ({ message: response }),
		utils: { escape_html: String, icon: () => "" },
	},
};
vm.createContext(context);
vm.runInContext(
	fs.readFileSync(path.join(__dirname, "../public/js/custom/supplier_vat_display.js"), "utf8"),
	context
);

async function testPriceInput() {
	for (const locked of [false, true]) {
		const fields = { rate: { read_only: locked } };
		const row = { name: "row1", rate: 120, qty: 2, amount: 240 };
		const frm = {
			doctype: "Purchase Invoice",
			doc: { items: [row] },
			get_field: () => ({ $wrapper: element }),
			refresh_field() {},
			fields_dict: {
				items: {
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
		for (const [visible, payer] of [
			[false, false],
			[true, true],
			[true, false],
			[false, false],
		]) {
			response = {
				visible,
				payer,
				currency: "UAH",
				totals: { gross: 240, net: payer ? 200 : 240, vat: payer ? 40 : 0 },
				rows: { row1: { net_rate: payer ? 100 : 120, gross_rate: 120, gross_amount: 240 } },
			};
			await handlers["Purchase Invoice"].supplier(frm);
			assert.equal(fields.rate.in_list_view, 1);
			assert.equal(fields.rate.read_only, locked);
			assert.equal(fields.rate.columns, 1);
			assert.equal(row.rate, 120);
			assert.equal(row.amount, 240);
			assert.equal(fields.custom_vat_gross_rate.label, "Price including VAT (calculated)");
		}
	}
	process.stdout.write("VAT display: input stays visible, accounting values and rate locks preserved.\n");
}
testPriceInput().catch((error) => {
	process.stderr.write(`${error.stack}\n`);
	process.exitCode = 1;
});
