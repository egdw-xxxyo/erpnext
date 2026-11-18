(() => {
	if (erpnext.repair_dialog) return;
	const drafts = new WeakMap();
	const active = new WeakMap();
	const copy = (value) => (value == null ? value : JSON.parse(JSON.stringify(value)));

	function delivery_choices(dialog) {
		const field = dialog.fields_dict.delivery_type;
		if (!field) return;
		field.$wrapper.addClass("repair-dialog-delivery");
		const choices = $('<div class="repair-delivery-choices" role="radiogroup"></div>')
			.attr("aria-label", field.df.label)
			.appendTo(field.$wrapper);
		const name = frappe.utils.get_random(10);
		for (const value of field.df.options.split("\n").filter(Boolean)) {
			const card = $('<label class="repair-delivery-choice"></label>').appendTo(choices);
			const radio = $('<input type="radio">').attr({ name, value }).appendTo(card);
			$("<span></span>").text(__(value)).appendTo(card);
			radio.on("change", async () => {
				await dialog.set_value("delivery_type", value);
				dialog.dirty = true;
			});
		}
		const sync = () =>
			choices.find("input").each(function () {
				this.checked = this.value === dialog.get_value("delivery_type");
			});
		field.$input.on("change.repair-dialog select-change.repair-dialog", sync);
		dialog.on_page_show = sync;
	}

	erpnext.repair_dialog = {
		prompt(frm, fields, action, title, label, options = {}) {
			const standard =
				frm._repair_ui_failed ||
				(frm._repair_ui_standard ??
					frappe.get_user_settings(frm.doctype).standard_repair_form === true);
			if (standard) return frappe.prompt(fields, action, title, label);
			const key = `${frm.doc.name}:${title}`;
			if (!drafts.has(frm)) drafts.set(frm, new Map());
			if (!active.has(frm)) active.set(frm, new Map());
			const previous = active.get(frm).get(key);
			if (previous?.pending || previous?.dialog.display) return previous.dialog;
			const draft = drafts.get(frm).get(key) || {};
			const restored = fields.map((field) => {
				const saved = draft[field.fieldname];
				if (!saved || saved.repair_unit !== field.repair_unit) return { ...field };
				let value = copy(saved.value);
				if (field.fieldtype === "MultiCheck") {
					const options = field.options.map((option) => ({
						...option,
						checked: Array.isArray(value) && value.includes(option.value),
					}));
					return { ...field, options };
				}
				if (field.fieldtype === "Table" && Array.isArray(value)) {
					const columns = new Set((field.fields || []).map((column) => column.fieldname));
					const data = value.map((row, index) => ({
						...Object.fromEntries(Object.entries(row).filter(([key]) => columns.has(key))),
						idx: index + 1,
					}));
					return { ...field, data };
				}
				if (field.fieldtype === "Select" && !field.options.split("\n").includes(value)) {
					value = field.default || "";
				}
				return { ...field, default: value };
			});
			const dialog = new frappe.ui.Dialog({ fields: restored, title });
			const state = { dialog, pending: false };
			active.get(frm).set(key, state);
			dialog.$wrapper.addClass("repair-form-ui repair-dialog");
			dialog.$wrapper.toggleClass("repair-dialog-danger", Boolean(options.danger));
			dialog.onhide = () => {
				if (state.finished) return;
				const values = {};
				for (const field of dialog.fields_list) {
					if (field.get_value)
						values[field.df.fieldname] = {
							value: copy(field.get_value()),
							repair_unit: field.df.repair_unit,
						};
				}
				drafts.get(frm).set(key, values);
			};
			dialog.set_secondary_action_label(__("Discard Draft"));
			dialog.set_secondary_action(() => {
				if (state.pending) return;
				state.finished = true;
				drafts.get(frm).delete(key);
				dialog.hide();
			});
			dialog.set_primary_action(label, async (values) => {
				if (state.pending) return;
				state.pending = true;
				const button = dialog.get_primary_btn();
				button.prop("disabled", true).attr("aria-busy", "true").text(__("Working…"));
				dialog.get_secondary_btn().prop("disabled", true);
				dialog.clear_alert();
				try {
					await action(values);
					state.finished = true;
					drafts.get(frm).delete(key);
					dialog.hide();
				} catch {
					dialog.set_alert(
						__("The action could not be completed. Check the details and try again."),
						"danger"
					);
				} finally {
					state.pending = false;
					button.prop("disabled", false).removeAttr("aria-busy").text(label);
					dialog.get_secondary_btn().prop("disabled", false);
				}
			});
			delivery_choices(dialog);
			dialog.show();
			return dialog;
		},
	};
})();
