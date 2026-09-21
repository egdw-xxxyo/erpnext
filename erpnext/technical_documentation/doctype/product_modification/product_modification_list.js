// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// Attributes are rows of a child table, and the stock filter row can only ask about one of
// those rows: it joins the table once, so "optical" and "915 MHz" would have to be true of
// the same row and a modification carrying them in two rows matches nothing. So the dialog
// collects conditions instead of filters — the type answers which attributes exist, the
// attribute answers which values it allows, and the server intersects the conditions and
// hands back the modifications that satisfy all of them.

const ATTRIBUTE_TABLE = "Product Modification Attribute";
const EQUALS = "=";
const CONTAINS = "like";
const STARTS = "starts";
const AT_LEAST = ">=";
const AT_MOST = "<=";
const BETWEEN = "between";
const NUMERIC_MATCHES = [AT_LEAST, AT_MOST, BETWEEN];
const NOTHING = "no-such-modification";

frappe.listview_settings["Product Modification"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Search by Attribute"), () => open_search(listview));
		restrict_subtype_filter(listview);
	},

	before_render() {
		restrict_subtype_filter(cur_list);
	},
};

// The filter row offers every subtype of every product, so a list already narrowed to БпЛА
// still offers «Літієва». A subtype means nothing without its type, so until a type is
// filtered on, the subtype filter asks for the subtypes of no type at all — it opens empty —
// and its own input is disabled with a line saying what to do first. A subtype already
// filtered on keeps the input enabled whatever the type says: the filter has to stay
// removable, and clearing it here would quietly change the list someone opened by link.
//
// Two controls have to be told about the query: the one the standard filter row built from
// its own copy of the docfield before this script ran, and the docfield itself, which is what
// a filter added later is built from. The form is unaffected — it sets the query on its own
// control, and that wins — and the dialog below asks for the type before it offers a subtype.
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

function open_search(listview) {
	const dialog = new frappe.ui.Dialog({
		title: __("Search by Attribute"),
		fields: [
			{
				fieldname: "product_type",
				fieldtype: "Link",
				label: __("Product Type"),
				options: "Product Type",
				onchange: () => {
					dialog.set_value("product_subtype", null);
					load_attributes(dialog);
				},
			},
			{
				fieldname: "product_subtype",
				fieldtype: "Link",
				label: __("Subtype"),
				options: "Product Subtype",
				depends_on: "product_type",
				get_query: () => ({
					filters: { active: 1, product_type: dialog.get_value("product_type") },
				}),
				onchange: () => load_attributes(dialog),
			},
			{
				fieldname: "attribute",
				fieldtype: "Select",
				label: __("Attribute"),
				options: [],
				onchange: () => load_values(dialog),
			},
			{ fieldname: "has_condition", fieldtype: "Check", hidden: 1 },
			{
				fieldname: "match",
				fieldtype: "Select",
				label: __("Condition"),
				default: EQUALS,
				depends_on: "has_condition",
				options: text_matches(),
			},
			{
				fieldname: "attribute_value",
				fieldtype: "Autocomplete",
				label: __("Value"),
				options: [],
			},
			{
				fieldname: "attribute_value_to",
				fieldtype: "Data",
				label: __("Up To"),
				depends_on: `eval: doc.match === "${BETWEEN}"`,
			},
			{
				fieldname: "add_condition",
				fieldtype: "Button",
				label: __("Add Condition"),
				click: () => add_condition(dialog),
			},
			{ fieldtype: "Section Break", label: __("Conditions") },
			{ fieldname: "conditions_html", fieldtype: "HTML" },
			{ fieldname: "conditions_count", fieldtype: "HTML" },
		],
		primary_action_label: __("Search"),
		primary_action: () => {
			add_condition(dialog, { silent: true });
			dialog.hide();
			apply_search(listview, dialog);
		},
	});

	dialog.__conditions = [];
	dialog.show();
	render_conditions(dialog);
}

function load_attributes(dialog) {
	const product_type = dialog.get_value("product_type");
	const product_subtype = dialog.get_value("product_subtype");

	dialog.set_value("attribute", "");
	dialog.fields_dict.attribute_value.set_data([]);
	refresh_count(dialog);

	if (!product_type && !product_subtype) {
		dialog.set_df_property("attribute", "options", []);
		return;
	}

	frappe
		.xcall("erpnext.technical_documentation.attributes.get_attributes", {
			product_type,
			product_subtype,
		})
		.then((rows) => {
			dialog.__attributes = rows || [];
			dialog.set_df_property(
				"attribute",
				"options",
				[""].concat(dialog.__attributes.map((row) => row.attribute))
			);
		});
}

function load_values(dialog) {
	const chosen = (dialog.__attributes || []).find((row) => row.attribute === dialog.get_value("attribute"));

	dialog.set_value("attribute_value", "");
	dialog.set_value("attribute_value_to", "");
	dialog.fields_dict.attribute_value.set_data(chosen ? chosen.values : []);

	// An attribute has three kinds and each is offered exactly the conditions that mean
	// something for it. A numeric one compares numbers; a free-text one can be searched by a
	// part of what was typed into it; a dictionary one has no third state between its own
	// values — «починається з Опт» over a closed list of «Оптика» and «Радіо» is a longer way
	// of writing the value, so the picker is not shown at all and the condition is the exact
	// match. The condition goes back to the exact one on every change of attribute: one left
	// over from the previous attribute would be a rule the person did not choose here.
	//
	// The picker is shown through `depends_on` rather than by hiding the control: a Select
	// built hidden never renders its own options.
	const from_dictionary = Boolean(chosen && chosen.values && chosen.values.length);

	dialog.set_df_property(
		"match",
		"options",
		chosen && chosen.numeric_values ? numeric_matches() : text_matches()
	);
	dialog.set_value("match", EQUALS);
	dialog.set_value("has_condition", chosen && !from_dictionary ? 1 : 0);
	dialog.set_df_property("attribute_value", "description", value_hint(chosen, from_dictionary));
}

function value_hint(chosen, from_dictionary) {
	if (!chosen) return "";
	if (from_dictionary) return __("Pick one of the values this attribute allows");
	if (chosen.numeric_values) return __("Type a number and choose a condition above");

	return __("Type a value and choose a condition above");
}

function text_matches() {
	return [
		{ label: __("is exactly"), value: EQUALS },
		{ label: __("starts with"), value: STARTS },
		{ label: __("contains the text"), value: CONTAINS },
	];
}

function numeric_matches() {
	return [
		{ label: __("is exactly"), value: EQUALS },
		{ label: __("is at least"), value: AT_LEAST },
		{ label: __("is at most"), value: AT_MOST },
		{ label: __("is between"), value: BETWEEN },
	];
}

// The values a modification carries are the ones its attribute allows, so the list is
// normally the whole answer. It stops being the whole answer as soon as a value is written
// out in full — «Оптика, 2 канали» — and someone is looking for the word rather than the
// value. That is what the condition picker is for, and it is a field the person sets, not a
// rule guessed from what they typed: a search that silently changed its own meaning between
// «Радіо» and «Ра» would be impossible to trust.
function condition_text(condition) {
	const attribute = frappe.utils.escape_html(condition.attribute);
	const value = frappe.utils.escape_html(condition.value);

	if (condition.match === BETWEEN) {
		return `${attribute} ${__("is between")} ${value} — ${frappe.utils.escape_html(condition.value_to)}`;
	}

	return `${attribute} ${match_label(condition.match)} ${value}`;
}

function match_label(match) {
	if (match === CONTAINS) return __("contains the text");
	if (match === STARTS) return __("starts with");
	if (match === AT_LEAST) return __("is at least");
	if (match === AT_MOST) return __("is at most");

	return __("is exactly");
}

// The list filter row knows «like» and the wildcard position is what separates the two
// loose conditions from one another; the exact one stays «=» so a filter someone edits by
// hand afterwards still reads as the value itself.
function filter_condition(condition) {
	const text = escape_wildcards(condition.value);

	if (condition.match === CONTAINS) return ["like", `%${text}%`];
	if (condition.match === STARTS) return ["like", `${text}%`];

	return ["=", condition.value];
}

// Escaped the same way the server escapes the multi-condition search, so one condition and
// two conditions mean the same thing: `%` is a character someone is looking for, never a
// wildcard they did not ask for.
function escape_wildcards(value) {
	return (value || "").replace(/\\/g, "\\\\").replace(/%/g, "\\%").replace(/_/g, "\\_");
}

// Searching with a pair still in the pickers means that pair, so the primary action adds it
// too instead of silently dropping it — quietly, because a search with nothing picked is a
// search by type alone and not a mistake.
function add_condition(dialog, { silent = false } = {}) {
	const attribute = dialog.get_value("attribute");
	const value = dialog.get_value("attribute_value");
	const match = dialog.get_value("match") || EQUALS;
	const value_to = match === BETWEEN ? dialog.get_value("attribute_value_to") : null;

	if (!attribute || !value || (match === BETWEEN && !value_to)) {
		if (!silent) {
			frappe.show_alert({ message: __("Pick an attribute and a value"), indicator: "orange" });
		}
		return;
	}

	const exists = dialog.__conditions.some(
		(row) =>
			row.attribute === attribute &&
			row.value === value &&
			row.match === match &&
			row.value_to === value_to
	);
	if (!exists) dialog.__conditions.push({ attribute, value, match, value_to });

	dialog.set_value("attribute", "");
	dialog.set_value("attribute_value", "");
	dialog.set_value("attribute_value_to", "");
	render_conditions(dialog);
}

function render_conditions(dialog) {
	const wrapper = dialog.fields_dict.conditions_html.$wrapper;

	refresh_count(dialog);

	if (!dialog.__conditions.length) {
		wrapper.html(`<div class="text-muted">${__("No conditions yet")}</div>`);
		return;
	}

	const pills = dialog.__conditions
		.map(
			(row, index) => `<div class="mb-2">
				<span class="indicator-pill blue">${condition_text(row)}</span>
				<a href="#" class="ml-2 text-muted" data-remove-condition="${index}">${__("Remove")}</a>
			</div>`
		)
		.join("");

	wrapper.html(pills);
	wrapper.find("[data-remove-condition]").on("click", (event) => {
		event.preventDefault();
		dialog.__conditions.splice(Number($(event.currentTarget).attr("data-remove-condition")), 1);
		render_conditions(dialog);
	});
}

// What a condition did to the answer is the thing worth knowing about it, and the only
// place it can be shown is here: once the search runs the dialog is gone and the conditions
// with it, so «nothing found» would leave nobody able to tell which of the four conditions
// was the one too many. The count is the search, run on what has been gathered so far and
// narrowed by the same type and subtype, rather than a second rule that could disagree
// with it.
//
// Answers are matched to the request that asked for them: the counts come back in whatever
// order the server finishes them, and a stale one overwriting a fresh one would show a
// number for conditions that are no longer on screen.
function refresh_count(dialog) {
	const wrapper = dialog.fields_dict.conditions_count.$wrapper;

	if (!(dialog.__conditions || []).length) {
		wrapper.empty();
		return;
	}

	const token = (dialog.__count_token = (dialog.__count_token || 0) + 1);
	wrapper.html(`<div class="text-muted">${__("Counting…")}</div>`);

	frappe
		.xcall("erpnext.technical_documentation.attributes.count_modifications", {
			conditions: dialog.__conditions,
			product_type: dialog.get_value("product_type"),
			product_subtype: dialog.get_value("product_subtype"),
		})
		.then((count) => {
			if (token !== dialog.__count_token) return;

			wrapper.html(
				`<div class="${count ? "text-muted" : "text-danger"}">
					${__("Matching modifications: {0}", [count])}
				</div>`
			);
		});
}

function apply_search(listview, dialog) {
	const filters = [];

	if (dialog.get_value("product_type")) {
		filters.push(["Product Modification", "product_type", "=", dialog.get_value("product_type")]);
	}
	if (dialog.get_value("product_subtype")) {
		filters.push(["Product Modification", "product_subtype", "=", dialog.get_value("product_subtype")]);
	}

	if (!dialog.__conditions.length) {
		set_filters(listview, filters);
		return;
	}

	// A single text condition is left to the filter row: it is one child-table join, it reads
	// as what it is, and it keeps working when the person edits it by hand afterwards. A
	// numeric one cannot go there whatever its count: the value is stored as text, and the
	// filter row would compare it as text, where «9» is larger than «10».
	if (dialog.__conditions.length === 1 && !NUMERIC_MATCHES.includes(dialog.__conditions[0].match)) {
		const [condition] = dialog.__conditions;
		filters.push([ATTRIBUTE_TABLE, "attribute", "=", condition.attribute]);
		filters.push([ATTRIBUTE_TABLE, "attribute_value", ...filter_condition(condition)]);
		set_filters(listview, filters);
		return;
	}

	frappe
		.xcall("erpnext.technical_documentation.attributes.search_modifications", {
			conditions: dialog.__conditions,
		})
		.then((names) => {
			// An empty answer has to stay an answer. Filtering on an empty list is dropped by
			// the filter area as an unset value, which leaves the list showing everything the
			// other filters allow — «nothing matches» would read as «everything matches», and
			// several conditions would look like they were joined by OR.
			if (!names.length) {
				frappe.show_alert({
					message: __("No modification matches these conditions"),
					indicator: "orange",
				});
			}

			filters.push(["Product Modification", "name", "in", names.length ? names : [NOTHING]]);
			set_filters(listview, filters);
		});
}

function set_filters(listview, filters) {
	listview.filter_area.clear(false).then(() => listview.filter_area.add(filters));
}
