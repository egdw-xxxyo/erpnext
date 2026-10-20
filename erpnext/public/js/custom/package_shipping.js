// A packed box leaves stock whole: picking a box adds all its serials, and scanning one serial of a
// box offers the whole box instead. The server refuses a part of a box on submit.
frappe.provide("erpnext.package_shipping");

erpnext.package_shipping.moves_out = function (frm) {
	const doc = frm.doc;
	if (frm.doctype === "Stock Entry") {
		return ["Material Issue", "Send to Subcontractor", "Subcontracting Delivery"].includes(doc.purpose);
	}
	if (frm.doctype === "Sales Invoice" && !doc.update_stock) return false;
	return !doc.is_return;
};

erpnext.package_shipping.add_package = function (frm, package_name) {
	const scanner = frm.cscript.barcode_scanner;
	if (!scanner) return Promise.resolve();
	return frappe
		.call({
			method: "erpnext.stock.package_shipping.package_contents",
			args: { package: package_name },
		})
		.then((r) => r.message && scanner.add_package_items(r.message));
};

if (!erpnext.utils.BarcodeScanner.prototype.package_shipping_wrapped) {
	const proto = erpnext.utils.BarcodeScanner.prototype;
	const base_scan_api_call = proto.scan_api_call;
	proto.package_shipping_wrapped = true;
	proto.scan_api_call = function (input, callback) {
		base_scan_api_call.call(this, input, (r) => {
			const data = r && r.message;
			const watched = ["Delivery Note", "Sales Invoice", "Stock Entry"].includes(this.frm.doctype);
			if (!data || !data.serial_no || !watched || !erpnext.package_shipping.moves_out(this.frm)) {
				callback(r);
				return;
			}
			frappe
				.call({
					method: "erpnext.stock.package_shipping.package_of_serial",
					args: { serial_no: data.serial_no },
				})
				.then((p) => {
					const box = p.message;
					if (!box) {
						callback(r);
						return;
					}
					frappe.confirm(
						__("Serial No {0} is in package {1} ({2} pcs). Add the whole package?", [
							data.serial_no,
							box.package_name,
							box.package_items.length,
						]),
						() => callback({ message: box }),
						() => {
							frappe.show_alert({
								message: __("Serial No {0} not added: a package is shipped only whole", [
									data.serial_no,
								]),
								indicator: "orange",
							});
							this.clean_up();
						}
					);
				});
		});
	};
}

frappe.ui.form.on("Delivery Note Package", {
	package(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.package && erpnext.package_shipping.moves_out(frm)) {
			erpnext.package_shipping.add_package(frm, row.package);
		}
	},
});
