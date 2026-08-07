frappe.ui.form.on("Vehicle Trip", {
	refresh: function (frm) {
		if (!frm.is_new() && frm.doc.docstatus === 0) {
			// Lock start fields after initial save
			frm.set_df_property("vehicle", "read_only", 1);
			frm.set_df_property("employee", "read_only", 1);
			frm.set_df_property("odometer_start", "read_only", 1);
			frm.set_df_property("destination", "read_only", 1);

			if (frm.doc.status === "En Route") {
				frm.page.set_primary_action(__("Complete Trip"), function () {
					frm.scroll_to_field("odometer_end");
					frm.fields_dict.odometer_end.$input.focus();
				});
			}
		}
	},

	vehicle: function (frm) {
		if (frm.doc.vehicle) {
			frappe.db.get_value(
				"Vehicle",
				frm.doc.vehicle,
				["last_odometer", "make", "model", "fuel_type", "uom"],
				function (r) {
					if (r) {
						frm.set_value("last_odometer", r.last_odometer);
						frm.set_value("vehicle_make_model", r.make + " " + r.model);
						frm.set_value("fuel_type", r.fuel_type);
						frm.set_value("fuel_uom", r.uom);
						frm.set_value("odometer_start", r.last_odometer);
					}
				}
			);
		}
	},

	odometer_end: function (frm) {
		if (frm.doc.odometer_end && frm.doc.odometer_start) {
			frm.set_value("distance", frm.doc.odometer_end - frm.doc.odometer_start);
		}
	},
});
