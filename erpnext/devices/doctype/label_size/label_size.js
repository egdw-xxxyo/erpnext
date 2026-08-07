frappe.ui.form.on("Label Size", {
	width_mm: function (frm) {
		calculate_print_delay(frm);
	},
	height_mm: function (frm) {
		calculate_print_delay(frm);
	},
});

function calculate_print_delay(frm) {
	const w = flt(frm.doc.width_mm);
	const h = flt(frm.doc.height_mm);
	if (w > 0 && h > 0) {
		frm.set_value("print_delay_ms", Math.round(w * h * 0.4));
	}
}
