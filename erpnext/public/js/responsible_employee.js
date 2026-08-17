// Prefill the "Responsible Employee" inventory dimension with the Employee of the current
// user on every row that points at the R&D warehouse. The server does the same in
// `erpnext.stock.responsible_employee.validate_responsible_employee`; this only makes the
// value visible while the row is being entered. An existing value is never overwritten.
frappe.provide("erpnext.responsible_employee");

erpnext.responsible_employee.fields = {
	"Stock Entry Detail": [
		["s_warehouse", "responsible_employee"],
		["t_warehouse", "to_responsible_employee"],
	],
	"Purchase Receipt Item": [
		["warehouse", "responsible_employee"],
		["rejected_warehouse", "rejected_responsible_employee"],
		["from_warehouse", "from_responsible_employee"],
	],
	"Purchase Invoice Item": [
		["warehouse", "responsible_employee"],
		["rejected_warehouse", "rejected_responsible_employee"],
		["from_warehouse", "from_responsible_employee"],
	],
	"Delivery Note Item": [
		["warehouse", "responsible_employee"],
		["target_warehouse", "to_responsible_employee"],
	],
	"Sales Invoice Item": [
		["warehouse", "responsible_employee"],
		["target_warehouse", "to_responsible_employee"],
	],
	"Stock Reconciliation Item": [["warehouse", "responsible_employee"]],
};

erpnext.responsible_employee.defaults = function (company) {
	erpnext.responsible_employee._cache = erpnext.responsible_employee._cache || {};
	const cache = erpnext.responsible_employee._cache;

	if (!cache[company]) {
		cache[company] = frappe
			.call({
				method: "erpnext.stock.responsible_employee.get_responsible_defaults",
				args: { company: company },
			})
			.then((r) => r.message || {});
	}

	return cache[company];
};

erpnext.responsible_employee.apply = function (frm, cdt, cdn) {
	const row = locals[cdt] && locals[cdt][cdn];
	const pairs = row && erpnext.responsible_employee.fields[cdt];
	if (!pairs || !frm.doc.company) return;

	erpnext.responsible_employee.defaults(frm.doc.company).then((defaults) => {
		if (!defaults.warehouse || !defaults.employee) return;

		for (const [warehouse_field, dimension_field] of pairs) {
			if (row[warehouse_field] !== defaults.warehouse) continue;
			if (row[dimension_field]) continue;
			if (!frappe.meta.has_field(cdt, dimension_field)) continue;

			frappe.model.set_value(cdt, cdn, dimension_field, defaults.employee);
		}
	});
};

// child-table handlers are global, so register them once no matter how many parent
// doctypes pull this file in
if (!erpnext.responsible_employee.bound) {
	erpnext.responsible_employee.bound = true;

	for (const [child_doctype, pairs] of Object.entries(erpnext.responsible_employee.fields)) {
		const handlers = {};
		for (const [warehouse_field] of pairs) {
			handlers[warehouse_field] = erpnext.responsible_employee.apply;
		}
		frappe.ui.form.on(child_doctype, handlers);
	}

	for (const parent of [
		"Stock Entry",
		"Purchase Receipt",
		"Purchase Invoice",
		"Delivery Note",
		"Sales Invoice",
		"Stock Reconciliation",
	]) {
		frappe.ui.form.on(parent, {
			items_add: erpnext.responsible_employee.apply,
		});
	}
}
