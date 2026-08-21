// Month-only presentation for a plain Date field.
// The value stays a real Date in the DB (first day of the month), so sorting and
// filtering keep working; only the input text and the datepicker view change.

frappe.provide("erpnext.utils.month_field");

const MONTH_KEYS = [
	"January",
	"February",
	"March",
	"April",
	"May",
	"June",
	"July",
	"August",
	"September",
	"October",
	"November",
	"December",
];

function month_names() {
	return MONTH_KEYS.map((key) => __(key));
}

function month_options() {
	// Select keeps the numeric value (autoname and sorting rely on it), only the label is readable.
	return MONTH_KEYS.map((key, index) => ({ value: String(index + 1), label: __(key) }));
}

function month_start(value) {
	const date = value ? frappe.datetime.str_to_obj(value) : new Date();
	return frappe.datetime.obj_to_str(new Date(date.getFullYear(), date.getMonth(), 1)).slice(0, 10);
}

function apply_period(frm, date_field = "effective_from") {
	// The period is one Date field shown as a month; `year` and `month` stay in the doc
	// (autoname and sorting read them) and are filled by the server on validate.
	apply(frm, date_field);

	if (frm.is_new() && !frm.doc[date_field]) {
		frm.set_value(date_field, month_start());
	}
}

function format_month(value) {
	if (!value) return "";
	const date = frappe.datetime.str_to_obj(value);
	if (!date || isNaN(date.getTime())) return "";
	return `${month_names()[date.getMonth()]} ${date.getFullYear()}`;
}

function parse_month(value) {
	if (!value) return "";

	const text = String(value).trim();
	const year_match = text.match(/\d{4}/);

	if (year_match) {
		const name = text
			.replace(year_match[0], "")
			.replace(/[^\p{L}]/gu, "")
			.toLowerCase();
		if (name) {
			const candidates = month_names().concat(MONTH_KEYS);
			const index = candidates.findIndex((month) => month.toLowerCase().startsWith(name.slice(0, 3)));
			if (index !== -1) {
				const month = String((index % 12) + 1).padStart(2, "0");
				return `${year_match[0]}-${month}-01`;
			}
		}
	}

	// Someone typed a full date (or pasted an ISO one) — keep it, snapped to the 1st.
	const parsed = frappe.datetime.user_to_str(text);
	if (parsed && frappe.datetime.validate(parsed)) {
		return parsed.slice(0, 7) + "-01";
	}

	return "";
}

function picker_language() {
	// Stock date.js only looks at User.language, so a user who never picked one gets
	// the English calendar even on a Ukrainian site — fall back to the site language.
	const lang = (frappe.boot.user && frappe.boot.user.language) || frappe.boot.lang;
	return $.fn.datepicker.language[lang] ? lang : "en";
}

function apply(frm, fieldname) {
	apply_control(frm.get_field(fieldname));
}

// Works on a form field and on a page filter alike — both are Control instances.
function apply_control(control) {
	if (!control || !control.$input || control.month_field_applied) return;

	control.month_field_applied = true;
	control.format_for_input = (value) => format_month(value);
	control.parse = (value) => parse_month(value);
	control.$input.attr("placeholder", __("Unknown"));

	// `view` / `minView` are read once at datepicker init, so rebuild the picker
	// instead of calling update() on the existing one.
	const set_date_options = control.set_date_options.bind(control);
	control.set_date_options = function () {
		set_date_options();
		Object.assign(this.datepicker_options, {
			view: "months",
			minView: "months",
			dateFormat: "MM yyyy",
			language: picker_language(),
		});
	};

	if (control.datepicker) {
		control.datepicker.destroy();
		control.datepicker = null;
	}
	control.make_picker();
	control.refresh();
}

Object.assign(erpnext.utils.month_field, {
	format_month,
	parse_month,
	apply,
	apply_control,
	month_options,
	month_start,
	apply_period,
});
