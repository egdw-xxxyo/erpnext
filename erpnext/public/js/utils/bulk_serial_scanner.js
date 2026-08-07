erpnext.utils.show_bulk_serial_dialog = function (on_scan) {
	let d = new frappe.ui.Dialog({
		title: __("Bulk Add Serial Numbers"),
		fields: [
			{
				fieldname: "serials",
				fieldtype: "Text",
				label: __("Serial Numbers"),
				description: __("Enter one serial number per line, or separate with spaces"),
			},
		],
		primary_action_label: __("Add"),
		primary_action: function (values) {
			let raw = values.serials || "";
			let serials = raw
				.split(/[\n\r\s]+/)
				.map((s) => s.trim())
				.filter(Boolean);

			if (!serials.length) return;
			d.hide();

			let delay = 0;
			serials.forEach(function (serial) {
				setTimeout(function () {
					on_scan(serial);
				}, delay);
				delay += 200;
			});
		},
	});
	d.show();
};

erpnext.utils.add_bulk_serial_button = function ($wrapper, on_scan) {
	let $btn = $(
		`<span class="bulk-serial-btn link-btn" style="display:inline;" title="${__("Bulk Add Serials")}">
			<a class="btn-open no-decoration" style="cursor:pointer;">
				<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-list"></use></svg>
			</a>
		</span>`
	);
	$btn.on("click", function () {
		erpnext.utils.show_bulk_serial_dialog(on_scan);
	});
	$wrapper.append($btn);
	return $btn;
};
