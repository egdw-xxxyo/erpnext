frappe.ui.form.on("Serial and Batch Bundle", {
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.fields_dict.scan_serial_no?.$input?.focus();
		}
	},

	scan_serial_no(frm) {
		const value = (frm.doc.scan_serial_no || "").trim();
		if (!value) {
			return;
		}

		const clear = () => {
			frm.set_value("scan_serial_no", "");
			setTimeout(() => frm.fields_dict.scan_serial_no?.$input?.focus(), 100);
		};

		if (!frm.doc.item_code) {
			frappe.utils.play_sound("error");
			frappe.msgprint(__("Please select an Item Code first"));
			clear();
			return;
		}

		if (frm.doc.has_serial_no) {
			const duplicate = (frm.doc.entries || []).some((row) => row.serial_no === value);
			if (duplicate) {
				frappe.utils.play_sound("error");
				frappe.show_alert({
					message: __("Serial No {0} is already added", [value]),
					indicator: "orange",
				});
				clear();
				return;
			}
		}

		frappe.call({
			method: "erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle.is_serial_batch_no_exists",
			args: {
				item_code: frm.doc.item_code,
				type_of_transaction: frm.doc.type_of_transaction,
				serial_no: frm.doc.has_serial_no ? value : null,
				batch_no: frm.doc.has_serial_no ? null : value,
			},
			callback: () => {
				frm.events.add_scanned_entry(frm, value);
				clear();
			},
			error: () => clear(),
		});
	},

	add_scanned_entry(frm, value) {
		const row = frm.add_child("entries");

		if (frm.doc.has_serial_no) {
			row.serial_no = value;
		} else {
			row.batch_no = value;
		}

		row.qty = 1;

		if (frm.doc.warehouse) {
			row.warehouse = frm.doc.warehouse;
		}

		frm.refresh_field("entries");
		frappe.utils.play_sound("submit");
		frappe.show_alert({
			message: __("Added {0}", [value]),
			indicator: "green",
		});
	},
});
