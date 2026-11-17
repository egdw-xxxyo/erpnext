frappe.provide("erpnext.label_designer");

const LT_METHOD = "erpnext.devices.doctype.label_template.label_template";

const LT_INPUT_TYPES = {
	Data: "Data",
	"Small Text": "Small Text",
	Int: "Int",
	Float: "Float",
	Date: "Date",
	Select: "Select",
	Check: "Check",
};

erpnext.label_designer.open_print_dialog = async function (label_template, opts = {}) {
	const r = await frappe.call({
		method: `${LT_METHOD}.get_print_dialog_context`,
		args: { label_template },
	});
	const ctx = r.message;
	if (!ctx) return;

	const hooks = { refresh: () => {}, note: () => {} };
	const printers = ctx.printers || [];
	const printer_by_name = Object.fromEntries(printers.map((p) => [p.name, p]));
	const input_fields = (ctx.inputs || []).map((row) => {
		const fieldtype = LT_INPUT_TYPES[row.fieldtype] || "Data";
		const df = {
			fieldname: `in_${row.fieldname}`,
			fieldtype,
			label: row.label || row.fieldname,
			reqd: row.reqd ? 1 : 0,
			default: row.default_value,
			onchange: () => hooks.refresh(),
		};
		if (fieldtype === "Select") df.options = ["", ...(row.options || "").split("\n")].join("\n");
		return df;
	});

	const fields = [
		{
			fieldname: "label_printer",
			fieldtype: "Link",
			label: __("Printer"),
			options: "Label Printer",
			reqd: 1,
			default: opts.label_printer || ctx.default_printer,
			get_query: () => ({ filters: { is_enabled: 1 } }),
			onchange: () => hooks.note(),
		},
		{ fieldname: "printer_note", fieldtype: "HTML" },
		{ fieldname: "copies", fieldtype: "Int", label: __("Quantity"), reqd: 1, default: opts.copies || 1 },
	];
	if (ctx.template_type === "From DocType" && ctx.reference_doctype) {
		fields.push({
			fieldname: "reference_name",
			fieldtype: "Link",
			label: __(ctx.reference_doctype),
			options: ctx.reference_doctype,
			default: opts.reference_name,
			onchange: () => hooks.refresh(),
			description: __("The document whose data goes on the label"),
		});
	}
	if (input_fields.length) {
		fields.push({ fieldtype: "Section Break", label: __("Label data") }, ...input_fields);
	}
	fields.push(
		{ fieldtype: "Section Break", label: __("Preview") },
		{ fieldname: "preview", fieldtype: "HTML" }
	);

	const d = new frappe.ui.Dialog({
		title: __("Print label: {0}", [ctx.template_name]),
		fields,
		primary_action_label: __("Print"),
		primary_action: (values) => {
			const inputs = collect_inputs(values);
			frappe.call({
				method: `${LT_METHOD}.print_from_template`,
				args: {
					label_template,
					label_printer: values.label_printer,
					copies: values.copies,
					inputs: JSON.stringify(inputs),
					reference_name: values.reference_name || null,
				},
				freeze: true,
				freeze_message: __("Sending to printer..."),
				callback: (res) => {
					if (res.message && res.message.success) {
						frappe.show_alert({ message: __("Label sent to printer"), indicator: "green" });
						d.hide();
					}
				},
			});
		},
	});

	const collect_inputs = (values) => {
		const out = {};
		(ctx.inputs || []).forEach((row) => {
			out[row.fieldname] = values[`in_${row.fieldname}`];
		});
		return out;
	};

	const show_printer_note = () => {
		const p = printer_by_name[d.get_value("label_printer")];
		let note = "";
		if (p && p.loaded_label_size && p.loaded_label_size !== ctx.label_size) {
			note = `<div class="alert alert-warning small" style="margin:0 0 8px;">${__(
				"Printer has {0} loaded, the template needs {1}.",
				[frappe.utils.escape_html(p.loaded_label_size), frappe.utils.escape_html(ctx.label_size)]
			)}</div>`;
		} else if (p && p.mock_printing) {
			note = `<div class="text-muted small" style="margin:0 0 8px;">${__(
				"Mock printing: nothing is sent to the device."
			)}</div>`;
		}
		d.fields_dict.printer_note.$wrapper.html(note);
	};

	let timer = null;
	let seq = 0;
	const $preview = d.fields_dict.preview.$wrapper;
	const refresh_preview = () => {
		clearTimeout(timer);
		timer = setTimeout(() => {
			const my = ++seq;
			$preview.find(".lt-dialog-thumb").css("opacity", 0.5);
			frappe
				.call({
					method: `${LT_METHOD}.render_template_preview`,
					args: {
						label_template,
						inputs: JSON.stringify(collect_inputs(d.get_values(true))),
						reference_name: d.get_value("reference_name") || null,
						sample: 0,
					},
				})
				.then((res) => {
					if (my !== seq) return;
					const data = res.message;
					if (!data) {
						$preview.html(`<div class="text-muted small">${__("No preview")}</div>`);
						return;
					}
					$preview.html(`
						<div class="lt-dialog-thumb" style="text-align:center;">
							<span class="lt-thumb" title="${__("Click to enlarge")}">
								<img src="data:image/png;base64,${data.image_base64}" style="max-height:180px;">
							</span>
							<div class="text-muted small" style="margin-top:4px;">${data.width_mm} × ${data.height_mm} ${__("mm")}</div>
						</div>`);
					$preview
						.find(".lt-thumb")
						.on("click", () => erpnext.label_designer.show_big_preview(data, ctx.template_name));
				})
				.catch(() => {
					if (my === seq)
						$preview.html(`<div class="text-danger small">${__("Preview failed")}</div>`);
				});
		}, 400);
	};

	erpnext.label_designer.inject_style();
	d.show();
	hooks.refresh = refresh_preview;
	hooks.note = show_printer_note;
	show_printer_note();
	refresh_preview();
	return d;
};
