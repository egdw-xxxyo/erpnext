frappe.provide("erpnext.specification");

frappe.ui.form.on("Specification", {
	setup: function (frm) {
		frm.get_field("attributes").grid.editable_fields = [
			{ fieldname: "attribute", columns: 6 },
			{ fieldname: "attribute_value", columns: 6 },
		];

		frm.fields_dict["attributes"].grid.get_field("attribute").get_query = function (doc, cdt, cdn) {
			let row = locals[cdt][cdn];
			let used = (doc.attributes || []).filter((d) => d.name !== row.name).map((d) => d.attribute);
			let filters = { name: ["not in", used] };
			// With an Item template picked, the axes of the catalog come from that Item —
			// plus whatever is already pinned on the template as catalog metadata.
			if (doc.item_template && frm.__item_attributes) {
				let pinned = (doc.attributes || []).filter((d) => d.attribute_value).map((d) => d.attribute);
				let offered = frm.__item_attributes
					.concat(pinned)
					.filter((a) => !used.includes(a) || a === row.attribute);
				filters.name = ["in", offered];
			}
			return { filters: filters };
		};

		frm.set_query("item_template", function () {
			return { filters: { has_variants: 1 } };
		});
	},

	refresh: function (frm) {
		erpnext.specification.toggle_attributes(frm);
		erpnext.specification.load_item_attributes(frm);

		if (frm.doc.has_variants) {
			frm.add_custom_button(
				__("Single Variant"),
				function () {
					erpnext.specification.show_single_variant_dialog(frm);
				},
				__("Create")
			);
			frm.add_custom_button(
				__("Multiple Variants"),
				function () {
					erpnext.specification.show_multiple_variants_dialog(frm);
				},
				__("Create")
			);
			frm.page.set_inner_btn_group_as_primary(__("Create"));
		}

		if (frm.doc.variant_of) {
			frm.add_custom_button(__("Template: {0}", [frm.doc.variant_of]), function () {
				frappe.set_route("Form", "Specification", frm.doc.variant_of);
			});
		}
	},

	has_variants: function (frm) {
		erpnext.specification.toggle_attributes(frm);
	},

	item_template: function (frm) {
		erpnext.specification.load_item_attributes(frm, true);
	},

	variant_of: function (frm) {
		if (!frm.doc.variant_of || (frm.doc.attributes || []).length) return;
		frappe.db.get_doc("Specification", frm.doc.variant_of).then((template) => {
			(template.attributes || []).forEach((row) => {
				frm.add_child("attributes", {
					attribute: row.attribute,
					attribute_value: row.attribute_value,
					numeric_values: row.numeric_values,
					from_range: row.from_range,
					to_range: row.to_range,
					increment: row.increment,
				});
			});
			frm.refresh_field("attributes");
		});
	},
});

erpnext.specification.load_item_attributes = function (frm, add_rows) {
	if (!frm.doc.item_template) {
		frm.__item_attributes = null;
		frm.set_value("item_template_attributes", "");
		return;
	}

	frappe
		.call({
			method: "erpnext.manufacturing.doctype.specification.specification.get_item_template_attributes",
			args: { item_template: frm.doc.item_template },
		})
		.then((r) => {
			frm.__item_attributes = r.message || [];
			frm.set_value("item_template_attributes", frm.__item_attributes.join("\n"));

			if (!add_rows || frm.doc.variant_of) return;

			let present = (frm.doc.attributes || []).map((d) => d.attribute);
			frm.__item_attributes
				.filter((attribute) => !present.includes(attribute))
				.forEach((attribute) => {
					frm.add_child("attributes", { attribute: attribute });
				});
			frm.refresh_field("attributes");
		});
};

erpnext.specification.toggle_attributes = function (frm) {
	if (frm.doc.has_variants || frm.doc.variant_of) {
		frm.toggle_display("section_attributes", true);
		let grid = frm.fields_dict.attributes.grid;

		if (frm.doc.variant_of) {
			grid.set_column_disp("attribute_value", true);
			grid.toggle_enable("attribute_value", false);
			grid.toggle_enable("attribute", false);
			frm.toggle_enable("attributes", false);
		} else {
			// On a template a value means "fixed for every variant of this catalog".
			frm.toggle_enable("attributes", true);
			grid.set_column_disp("attribute_value", true);
			grid.toggle_enable("attribute_value", true);
			grid.toggle_enable("attribute", true);
		}
	} else {
		frm.toggle_display("section_attributes", false);
	}
	frm.layout.refresh_sections();
};

erpnext.specification.show_single_variant_dialog = function (frm) {
	// Attributes fixed on the template are not asked for — every variant carries them.
	let rows = frm.doc.attributes.filter((r) => !r.disabled && !r.attribute_value);
	let promises = rows.map((row) => {
		if (row.numeric_values) {
			return Promise.resolve({ row: row, options: null });
		}
		return frappe
			.call({
				method: "frappe.client.get_list",
				args: {
					doctype: "Item Attribute Value",
					filters: [["parent", "=", row.attribute]],
					fields: ["attribute_value"],
					parent: "Item Attribute",
					order_by: "idx",
					limit_page_length: 0,
				},
			})
			.then((r) => ({ row: row, options: (r.message || []).map((v) => v.attribute_value) }));
	});

	Promise.all(promises).then((attrs) => {
		let fields = attrs.map(({ row, options }) => {
			if (row.numeric_values) {
				return {
					label: row.attribute,
					fieldname: row.attribute,
					fieldtype: "Float",
					reqd: 1,
					description: __("Min: {0}, Max: {1}, Increment: {2}", [
						row.from_range,
						row.to_range,
						row.increment,
					]),
				};
			}
			return {
				label: row.attribute,
				fieldname: row.attribute,
				fieldtype: "Autocomplete",
				options: options,
				reqd: 1,
			};
		});

		let d = new frappe.ui.Dialog({ title: __("Create Variant"), fields: fields });

		d.set_primary_action(__("Create"), function () {
			let args = d.get_values();
			if (!args) return;
			frappe.call({
				method: "erpnext.manufacturing.specification_variant.get_variant",
				btn: d.get_primary_btn(),
				args: { template: frm.doc.name, args: args },
				callback: function (r) {
					if (r.message) {
						let variant = r.message;
						frappe.msgprint(
							__("Specification Variant {0} already exists with same attributes", [
								`<a href="/app/specification/${encodeURIComponent(variant)}">${variant}</a>`,
							])
						);
					} else {
						d.hide();
						frappe.call({
							method: "erpnext.manufacturing.specification_variant.create_variant",
							args: { spec: frm.doc.name, args: args },
							callback: function (r) {
								let doclist = frappe.model.sync(r.message);
								frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
							},
						});
					}
				},
			});
		});

		d.show();
	});
};

erpnext.specification.show_multiple_variants_dialog = function (frm) {
	let me = {};
	let promises = [];
	let attr_val_fields = {};

	function make_fields_from_attribute_values(attr_dict) {
		let fields = [];
		Object.keys(attr_dict).forEach((name, i) => {
			if (i % 3 === 0) fields.push({ fieldtype: "Section Break" });
			fields.push({ fieldtype: "Column Break", label: name });
			attr_dict[name].forEach((value) => {
				fields.push({
					fieldtype: "Check",
					label: value,
					fieldname: value,
					default: 0,
					onchange: function () {
						let selected = get_selected_attributes();
						let lengths = Object.keys(selected).map((k) => selected[k].length);
						if (lengths.includes(0)) {
							me.dialog.get_primary_btn().html(__("Create Variants"));
							me.dialog.disable_primary_action();
						} else {
							let n = lengths.reduce((a, b) => a * b, 1);
							me.dialog
								.get_primary_btn()
								.html(n === 1 ? __("Make 1 Variant") : __("Make {0} Variants", [n]));
							me.dialog.enable_primary_action();
						}
					},
				});
			});
		});
		return fields;
	}

	function get_selected_attributes() {
		let selected = {};
		me.dialog.$wrapper.find(".form-column").each((i, col) => {
			if (i === 0) return;
			let name = $(col).find(".column-label").html().trim();
			selected[name] = [];
			$(col)
				.find(".checkbox input")
				.each((j, opt) => {
					if ($(opt).is(":checked")) selected[name].push($(opt).attr("data-fieldname"));
				});
		});
		return selected;
	}

	function make_and_show_dialog(fields) {
		me.dialog = new frappe.ui.Dialog({
			title: __("Select Attribute Values"),
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "help",
					options: `<label class="control-label">${__(
						"Select at least one value from each attribute."
					)}</label>`,
				},
			].concat(fields),
		});

		me.dialog.set_primary_action(__("Create Variants"), () => {
			let selected = get_selected_attributes();
			me.dialog.hide();
			frappe.call({
				method: "erpnext.manufacturing.specification_variant.enqueue_multiple_variant_creation",
				args: { spec: frm.doc.name, args: selected },
				callback: function (r) {
					if (r.message === "queued") {
						frappe.show_alert({
							message: __("Variant creation has been queued."),
							indicator: "orange",
						});
					} else {
						frappe.show_alert({
							message: __("{0} variants created.", [r.message]),
							indicator: "green",
						});
					}
				},
			});
		});

		me.dialog.disable_primary_action();
		me.dialog.clear();
		me.dialog.show();
	}

	frm.doc.attributes.forEach(function (d) {
		if (d.disabled || d.attribute_value) return;
		let p = new Promise((resolve) => {
			if (!d.numeric_values) {
				frappe
					.call({
						method: "frappe.client.get_list",
						args: {
							doctype: "Item Attribute Value",
							filters: [["parent", "=", d.attribute]],
							fields: ["attribute_value"],
							limit_page_length: 0,
							parent: "Item Attribute",
							order_by: "idx",
						},
					})
					.then((r) => {
						attr_val_fields[d.attribute] = (r.message || []).map((v) => v.attribute_value);
						resolve();
					});
			} else {
				let values = [];
				for (let i = d.from_range; i <= d.to_range; i = flt(i + d.increment, 6)) values.push(i);
				attr_val_fields[d.attribute] = values;
				resolve();
			}
		});
		promises.push(p);
	});

	Promise.all(promises).then(() => {
		make_and_show_dialog(make_fields_from_attribute_values(attr_val_fields));
	});
};
