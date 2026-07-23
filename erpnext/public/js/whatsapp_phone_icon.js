// Generic WhatsApp launcher: adds a small green WhatsApp icon inside every phone-number
// field on every desk form. Clicking it opens the Chat Center conversation for that number.
//
// Works by extending the framework's ControlData.make_input once (the same layer the built-in
// URL / copy / barcode addons hook into), so no per-doctype registration is needed. ControlPhone
// extends ControlData and calls super.make_input(), so dedicated "Phone" fields are covered too.

// Explicit WhatsApp fieldnames that are plain Data (no options=Phone) — e.g. Lead.whatsapp_no,
// Opportunity.whatsapp.
const WA_FIELDNAMES = new Set(["whatsapp", "whatsapp_no"]);

function is_whatsapp_phone_field(df) {
	if (!df) return false;
	if (df.fieldtype === "Phone") return true;
	if (df.fieldtype === "Data" && df.options === "Phone") return true;
	if (df.fieldtype === "Data" && WA_FIELDNAMES.has(df.fieldname)) return true;
	return false;
}

const WA_ICON = `<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true">
	<path d="M12.04 2c-5.5 0-9.96 4.46-9.96 9.96 0 1.76.46 3.48 1.34 5L2 22l5.16-1.35a9.9 9.9 0 0 0 4.88 1.28h.01c5.5 0 9.96-4.46 9.96-9.96S17.54 2 12.04 2zm0 18.13h-.01a8.2 8.2 0 0 1-4.19-1.15l-.3-.18-3.06.8.82-2.98-.2-.31a8.16 8.16 0 0 1-1.25-4.35c0-4.54 3.7-8.23 8.24-8.23 2.2 0 4.27.86 5.82 2.42a8.18 8.18 0 0 1 2.41 5.82c0 4.54-3.69 8.23-8.23 8.23zm4.52-6.16c-.25-.13-1.47-.72-1.69-.81-.23-.08-.39-.13-.56.13-.16.25-.64.8-.79.97-.14.16-.29.18-.54.06-.25-.13-1.05-.39-1.99-1.23-.74-.66-1.23-1.47-1.38-1.72-.14-.25-.02-.39.11-.51.11-.11.25-.29.37-.43.13-.14.17-.25.25-.41.08-.16.04-.31-.02-.43-.06-.13-.56-1.35-.77-1.85-.2-.48-.41-.42-.56-.43l-.48-.01c-.16 0-.43.06-.66.31-.23.25-.87.85-.87 2.07 0 1.22.89 2.4 1.01 2.57.13.16 1.75 2.67 4.23 3.74.59.26 1.05.41 1.41.52.59.19 1.13.16 1.56.1.48-.07 1.47-.6 1.68-1.18.21-.58.21-1.07.14-1.18-.06-.11-.22-.17-.47-.29z"/>
</svg>`;

function inject_styles() {
	if (document.getElementById("wa-phone-btn-styles")) return;
	$(`<style id="wa-phone-btn-styles">
		.control-input-wrapper { position: relative; }
		.wa-phone-btn { position: absolute; top: 0; right: 8px; height: var(--input-height, 28px);
			display: flex; align-items: center; z-index: 3; }
		.wa-phone-btn a { color: #25d366; cursor: pointer; line-height: 0; }
		.wa-phone-btn a:hover { color: #1da851; }
	</style>`).appendTo(document.head);
}

const _orig_make_input = frappe.ui.form.ControlData.prototype.make_input;
frappe.ui.form.ControlData.prototype.make_input = function () {
	_orig_make_input.apply(this, arguments);
	// Only for users allowed into the Chat Center (same check the bubble uses).
	if (!erpnext.whatsapp?.can_use?.()) return;
	if (is_whatsapp_phone_field(this.df)) {
		this.setup_whatsapp_btn();
	}
};

frappe.ui.form.ControlData.prototype.setup_whatsapp_btn = function () {
	// Append into .control-input-wrapper (parent of both the editable .control-input and the
	// read-only .control-value), so the icon shows in both modes — many phone fields (e.g.
	// Contact.mobile_no/phone) are read-only, auto-filled from a child table.
	const $wrapper = (this.$input_wrapper && this.$input_wrapper.length
		? this.$input_wrapper
		: this.$wrapper.find(".control-input-wrapper")
	).first();
	if (!$wrapper.length || $wrapper.find(".wa-phone-btn").length) return;

	inject_styles();

	$wrapper.append(
		`<span class="wa-phone-btn" style="display:none;">
			<a class="btn-open no-decoration" title="${__("Open WhatsApp chat")}">${WA_ICON}</a>
		</span>`
	);

	const $btn = $wrapper.find(".wa-phone-btn");
	const refresh_btn = () => $btn.toggle(/\d/.test(this.get_value() || ""));

	// Show whenever the field holds digits (persistent, not focus-gated). Refresh on typing,
	// on programmatic value set in edit mode (set_formatted_input), and on read-only display
	// refresh (set_disp_area).
	if (this.$input) this.$input.on("input", refresh_btn);
	const _orig_sfi = this.set_formatted_input.bind(this);
	this.set_formatted_input = (value) => {
		_orig_sfi(value);
		refresh_btn();
	};
	const _orig_sda = this.set_disp_area.bind(this);
	this.set_disp_area = (value) => {
		_orig_sda(value);
		refresh_btn();
	};
	refresh_btn();

	$btn.on("click", "a", () => {
		const digits = (this.get_value() || "").replace(/\D/g, "");
		if (!digits) {
			frappe.msgprint(__("No phone number"));
			return;
		}
		window.open(
			`/app/whatsapp-chat-center?phone=${encodeURIComponent(digits)}`,
			"_blank"
		);
	});
};
