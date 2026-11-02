// A serial number is one unit: a box scanned twice into a row's serial field is shown as soon as
// the field is left, before the save that the server refuses (serial_duplicate_guard.py).
frappe.provide("erpnext.serial_duplicates");

erpnext.serial_duplicates.CHILD_DOCTYPES = [
	"Delivery Note Item",
	"Sales Invoice Item",
	"Purchase Receipt Item",
	"Purchase Invoice Item",
	"Stock Entry Detail",
];
erpnext.serial_duplicates.FIELDS = ["serial_no", "rejected_serial_no"];

erpnext.serial_duplicates.split = function (value) {
	return (value || "")
		.split("\n")
		.map((s) => s.trim())
		.filter(Boolean);
};

erpnext.serial_duplicates.direction = function (row) {
	if (row.s_warehouse && row.t_warehouse) return "transfer";
	return row.s_warehouse ? "out" : row.t_warehouse ? "in" : "";
};

erpnext.serial_duplicates.check = function (frm, cdt, cdn) {
	const me = erpnext.serial_duplicates;
	const row = locals[cdt][cdn];
	const typed = (r) => me.FIELDS.flatMap((f) => me.split(r[f]));
	const messages = [];

	const own = typed(row);
	const repeated = [...new Set(own.filter((s, i) => own.indexOf(s) !== i))];
	if (repeated.length) {
		messages.push(
			__("Row {0}: serial numbers entered more than once: {1}", ["#" + row.idx, repeated.join(", ")])
		);
	}

	const side = me.direction(row);
	for (const serial of new Set(own)) {
		const rows = (frm.doc[row.parentfield] || [])
			.filter((r) => r.name !== row.name && me.direction(r) === side && typed(r).includes(serial))
			.map((r) => "#" + r.idx);
		if (rows.length) {
			messages.push(__("Serial No {0} is in rows {1}", [serial, ["#" + row.idx, ...rows].join(", ")]));
		}
	}

	if (messages.length) {
		frappe.msgprint({
			title: __("Duplicate serial numbers"),
			message: messages.join("<br>"),
			indicator: "orange",
		});
	}
};

if (!erpnext.serial_duplicates.registered) {
	erpnext.serial_duplicates.registered = true;
	const handlers = {};
	for (const field of erpnext.serial_duplicates.FIELDS) {
		handlers[field] = erpnext.serial_duplicates.check;
	}
	for (const child of erpnext.serial_duplicates.CHILD_DOCTYPES) {
		frappe.ui.form.on(child, handlers);
	}
}
