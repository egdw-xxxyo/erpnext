// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// The subtype filter offers every subtype of every product, so a list already narrowed to
// БпЛА still offers «Літієва». A subtype means nothing without its type, so until a type is
// filtered on, the subtype filter asks for the subtypes of no type at all — it opens empty —
// and its own input is disabled with a line saying what to do first. A subtype already
// filtered on keeps the input enabled whatever the type says: the filter has to stay
// removable, and clearing it here would quietly change the list someone opened by link.
//
// Two controls have to be told about the query: the one the standard filter row built from
// its own copy of the docfield before this script ran, and the docfield itself, which is what
// a filter added later is built from. The form is unaffected — it sets the query on its own
// control, and that wins. The modification list carries the same rule: a list script is loaded
// only for its own list, so the two cannot share one copy without a bundled module, and a
// bundled module would need an asset build to reach the desk.

frappe.listview_settings["Technical Document"] = {
	onload(listview) {
		restrict_subtype_filter(listview);
	},

	before_render() {
		restrict_subtype_filter(cur_list);
	},
};

function restrict_subtype_filter(listview) {
	if (!listview) return;

	const chosen_type = () => {
		const row = (listview.filter_area.get() || []).find(
			([doctype, fieldname, operator]) =>
				doctype === listview.doctype && fieldname === "product_type" && operator === "="
		);

		return row ? row[3] : null;
	};

	const query = () => ({ filters: { active: 1, product_type: chosen_type() || "" } });

	const field = frappe.meta.get_docfield(listview.doctype, "product_subtype");
	if (field) field.get_query = query;

	const control = listview.page.fields_dict && listview.page.fields_dict.product_subtype;
	if (!control) return;

	control.get_query = query;

	const locked = !chosen_type() && !control.get_value();
	control.$input.prop("disabled", locked);
	control.$input.attr("placeholder", locked ? __("Pick a product type first") : "");
}
