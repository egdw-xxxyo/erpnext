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

	const hooks = { refresh: () => {}, printer: () => {} };
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
			onchange: () => hooks.printer(),
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
			const state = label_state(printer_by_name[values.label_printer]);
			if (state === "changing" || state === "mismatch") {
				frappe.show_alert({
					message: __("Wrong label size in the printer — change the label first."),
					indicator: "red",
				});
				return;
			}
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

	const PRINTER_API = "erpnext.devices.doctype.label_printer.label_printer";
	const esc = frappe.utils.escape_html;

	const reload_printer = (name) =>
		frappe.db
			.get_value("Label Printer", name, [
				"name",
				"loaded_label_size",
				"is_label_change_in_progress",
				"pending_label_size",
				"mock_printing",
			])
			.then((res) => {
				if (res.message) printer_by_name[name] = { ...printer_by_name[name], ...res.message, name };
				show_printer_note();
			});

	const label_state = (p) => {
		if (!p) return "none";
		if (p.is_label_change_in_progress) return "changing";
		if (!p.loaded_label_size) return "unknown";
		return p.loaded_label_size === ctx.label_size ? "ok" : "mismatch";
	};

	const show_printer_note = () => {
		const name = d.get_value("label_printer");
		const p = printer_by_name[name];
		const state = label_state(p);
		const box = (color, html, buttons = "") =>
			`<div class="alert alert-${color} small" style="margin:0 0 8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
				<span style="flex:1;min-width:200px;">${html}</span>${buttons}</div>`;
		const button = (action, label, primary) =>
			`<button class="btn btn-xs ${primary ? "btn-primary" : "btn-default"}" data-label-action="${action}">${label}</button>`;
		const change = button("start", __("Change Label to {0}", [esc(ctx.label_size)]), true);
		let note = "";

		if (state === "changing") {
			note = box(
				"warning",
				__("Printer is changing labels to {0}. Load the labels, then confirm.", [
					`<b>${esc(p.pending_label_size || ctx.label_size)}</b>`,
				]),
				button("complete", __("Labels Loaded"), true) + button("cancel", __("Cancel Change"))
			);
		} else if (state === "mismatch") {
			note = box(
				"danger",
				__("Printer has {0} loaded, the template needs {1}.", [
					`<b>${esc(p.loaded_label_size)}</b>`,
					`<b>${esc(ctx.label_size)}</b>`,
				]),
				change
			);
		} else if (state === "unknown") {
			note = box(
				"warning",
				__("Printer has no loaded label size set; the template needs {0}.", [
					`<b>${esc(ctx.label_size)}</b>`,
				]),
				change
			);
		} else if (state === "ok") {
			note = `<div class="small" style="margin:0 0 8px;color:var(--green-600);">
				<i class="fa fa-check"></i> ${__("Loaded label: {0} — matches the template.", [
					esc(p.loaded_label_size),
				])}</div>`;
		}

		if (p && p.mock_printing) {
			note += `<div class="text-muted small" style="margin:0 0 8px;">${__(
				"Mock printing: nothing is sent to the device."
			)}</div>`;
		}

		d.fields_dict.printer_note.$wrapper.html(note);

		if (state === "changing" || state === "mismatch") d.disable_primary_action();
		else d.enable_primary_action();
	};

	const label_action = (action) => {
		const name = d.get_value("label_printer");
		const p = printer_by_name[name];
		if (!name || !p) return;

		const calls = {
			start: () =>
				frappe.call({
					method: `${PRINTER_API}.start_label_change`,
					args: {
						printer_name: name,
						new_label_size: ctx.label_size,
						message: __("Changing to {0}", [ctx.label_size]),
					},
				}),
			complete: () => {
				const size = p.pending_label_size || ctx.label_size;
				return frappe
					.call({
						method: `${PRINTER_API}.complete_label_change`,
						args: { printer_name: name, new_label_size: size },
					})
					.then((res) => {
						let message = __("Labels changed to {0}", [size]);
						const cancelled = res.message && res.message.cancelled_jobs;
						if (cancelled) message += ". " + __("{0} mismatched jobs cancelled", [cancelled]);
						frappe.show_alert({ message, indicator: "green" });
					});
			},
			cancel: () =>
				frappe
					.call({ method: `${PRINTER_API}.cancel_label_change`, args: { printer_name: name } })
					.then(() => frappe.show_alert({ message: __("Label change cancelled"), indicator: "blue" })),
		};

		calls[action]().then(() => reload_printer(name));
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
	hooks.printer = () => {
		const name = d.get_value("label_printer");
		if (name) reload_printer(name);
		else show_printer_note();
	};
	d.fields_dict.printer_note.$wrapper.on("click", "[data-label-action]", (event) =>
		label_action($(event.currentTarget).data("label-action"))
	);
	hooks.printer();
	refresh_preview();
	return d;
};
