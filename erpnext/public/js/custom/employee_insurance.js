// Страховий стаж до прийняття — один рядок «… років … місяців» замість двох полів одне під одним.
// Самі поля `custom_insurance_years` / `custom_insurance_months` сховані, цей рядок пише в них.

frappe.ui.form.on("Employee", {
	refresh: render_insurance_tenure,
	custom_insurance_years: sync_insurance_tenure,
	custom_insurance_months: sync_insurance_tenure,
});

const TENURE_PARTS = [
	{ fieldname: "custom_insurance_years", label: () => __("years"), max: 70 },
	{ fieldname: "custom_insurance_months", label: () => __("months"), max: 11 },
];

function render_insurance_tenure(frm) {
	const field = frm.get_field("custom_insurance_html");
	if (!field) return;

	const editable = Boolean(frm.perm[0] && frm.perm[0].write);
	const inputs = TENURE_PARTS.map(
		(part) => `
			<input type="number" min="0" max="${part.max}" step="1" class="form-control input-xs"
				data-fieldname="${part.fieldname}" style="width: 72px; display: inline-block;"
				${editable ? "" : "disabled"}>
			<span class="text-muted" style="margin: 0 12px 0 6px;">${part.label()}</span>`
	);

	field.$wrapper.html(`
		<div class="frappe-control">
			<div class="form-group">
				<div class="clearfix"><label class="control-label">${__("Insurance Tenure Before Joining")}</label></div>
				<div class="control-input-wrapper" style="display: flex; align-items: center;">
					${inputs.join("")}
				</div>
				<p class="help-box small text-muted">${__(
					"The tenure earned before this company. The time worked here is added automatically; the total sets the sick pay percent: under 3 years — 50%, 3 to 5 — 60%, 5 to 8 — 70%, over 8 — 100%."
				)}</p>
			</div>
		</div>`);

	field.$wrapper.find("input").on("change", function () {
		const fieldname = this.dataset.fieldname;
		const part = TENURE_PARTS.find((entry) => entry.fieldname === fieldname);
		const value = Math.min(Math.max(cint(this.value), 0), part.max);

		this.value = value;
		if (cint(frm.doc[fieldname]) !== value) frm.set_value(fieldname, value);
	});

	sync_insurance_tenure(frm);
}

function sync_insurance_tenure(frm) {
	const field = frm.get_field("custom_insurance_html");
	if (!field) return;

	field.$wrapper.find("input").each(function () {
		if (document.activeElement !== this) this.value = cint(frm.doc[this.dataset.fieldname]);
	});
}
