(() => {
	const preference = "standard_repair_form";
	const scope = "repair-form-ui";
	const esc = frappe.utils.escape_html;

	function standard(frm) {
		return frm._repair_ui_failed || frappe.get_user_settings(frm.doctype)[preference] === true;
	}

	function update_header(frm) {
		if (standard(frm)) return;
		const issue = frm.doctype === "Issue";
		const title = issue ? frm.doc.subject : frm.doc.product_name || frm.doc.item_code;
		const kind = issue ? __("Service Request") : __("Repair Unit");
		let header = frm.body.children(".repair-form-header");
		if (!header.length) {
			header = $(
				'<header class="repair-form-header"><div class="repair-form-heading">' +
					'<div class="repair-form-context"></div><h2></h2><p class="repair-form-hint"></p></div>' +
					'<div class="repair-form-meta"><span class="repair-form-status"></span>' +
					'<div class="repair-form-owner"></div></div></header>'
			).prependTo(frm.body);
		}
		header.find(".repair-form-context").text(frm.is_new() ? kind : kind + " · " + frm.doc.name);
		header.find("h2").text(title || (issue ? __("New Service Request") : __("New Repair Unit")));
		header
			.find(".repair-form-hint")
			.text(
				issue
					? __("Describe the request, select its type and specify the contact.")
					: __("Review the item details, record the repair work and its result.")
			);
		const [label, color] = frappe.get_indicator(frm.doc, frm.doctype) || [];
		header
			.find(".repair-form-status")
			.attr("class", `repair-form-status indicator-pill no-indicator-dot ${color || ""}`)
			.text(label || "");
		const owner = issue ? frm.doc.custom_support_user : frm.doc.repair_user;
		header.find(".repair-form-owner").html(owner ? erpnext.entity.user(owner, { size: 24 }) : "");
	}

	function request_type(frm) {
		const field = frm.fields_dict.custom_request_type;
		if (!field?.$input || field.get_status() !== "Write") return;
		field.$wrapper.addClass("repair-choice-field");
		const choices = $('<div class="repair-request-types"></div>').appendTo(field.$input.parent());
		const options = [
			["General Request", "comment-o", __("General Request"), __("Questions and support")],
			["Product Repair", "wrench", __("Product Repair"), __("Intake, repair and return")],
		];
		for (const [value, icon, label, hint] of options) {
			const button = $('<button type="button" class="repair-type-choice"></button>')
				.attr("aria-pressed", frm.doc.custom_request_type === value)
				.html(
					'<i class="fa fa-' +
						icon +
						'" aria-hidden="true"></i><span><strong>' +
						esc(label) +
						"</strong><small>" +
						esc(hint) +
						"</small></span>"
				)
				.appendTo(choices);
			button.on("click", async () => {
				choices.find("button").prop("disabled", true);
				try {
					await frm.set_value("custom_request_type", value);
				} finally {
					choices.find("button").prop("disabled", false);
				}
			});
		}
	}

	function arrange_issue(frm) {
		const { contact, subject, custom_request_type, custom_request_references_section, sb_details } =
			frm.fields_dict;
		const type = custom_request_type?.$wrapper;
		const references = custom_request_references_section?.wrapper;
		const dashboard = frm.dashboard.parent;

		// Keep the original locations so the standard view can reuse the same controls.
		const moves = [];
		const remember = (element) => {
			const anchor = document.createComment("");
			element.before(anchor);
			moves.push([anchor, element]);
		};
		frm._restore_repair_issue_layout = () => {
			for (const [anchor, element] of moves) {
				anchor.replaceWith(element[0]);
			}
		};

		if (type?.length && dashboard.length) {
			remember(type);
			const section = $(
				'<section class="form-section repair-issue-request-type"><div class="section-body"></div></section>'
			).insertBefore(dashboard);
			section.children(".section-body").append(type);
		}

		if (contact?.$wrapper.length && subject?.$wrapper.length) {
			remember(contact.$wrapper);
			contact.$wrapper.insertAfter(subject.$wrapper);
		}

		if (references?.length && sb_details?.wrapper.length) {
			remember(references);
			references.insertAfter(sb_details.wrapper);
		}

		for (const [fieldname, label] of [
			["custom_repair_delivery_type", __("Intake Details")],
			["custom_repair_return_address", __("Return Details")],
		]) {
			$('<h4 class="repair-delivery-heading"></h4>')
				.text(label)
				.prependTo(frm.fields_dict[fieldname]?.$wrapper.closest(".form-column"));
		}
	}

	function restore(frm) {
		$(frm.wrapper)
			.removeClass(scope + " repair-issue-ui")
			.off(".repair-header");
		frm._restore_repair_issue_layout?.();
		delete frm._restore_repair_issue_layout;
		frm.body
			.find(
				".repair-form-header, .repair-section-caption, .repair-request-types, .repair-issue-request-type, .repair-delivery-heading"
			)
			.remove();
		frm.body.find(".repair-choice-field").removeClass("repair-choice-field");
	}

	function refresh(frm) {
		frm.page.menu.find(".repair-form-switch").closest("li").remove();
		const isStandard = standard(frm);
		let saving = false;
		frm.page
			.add_menu_item(
				isStandard ? __("Use New Repair UI") : __("Return to Standard Frappe UI"),
				async () => {
					if (saving) return;
					saving = true;
					try {
						await frappe.model.user_settings.save(frm.doctype, preference, !isStandard);
						frm._repair_ui_failed = false;
						refresh(frm);
					} finally {
						saving = false;
					}
				},
				false,
				null,
				true
			)
			.addClass("repair-form-switch");
		restore(frm);
		if (isStandard) return;
		try {
			$(frm.wrapper).addClass(scope);
			if (frm.doctype === "Issue") {
				$(frm.wrapper).addClass("repair-issue-ui");
				arrange_issue(frm);
			}
			update_header(frm);
			request_type(frm);
			for (const section of frm.layout.sections) {
				if (section.df.is_dashboard_section || section.df.label) continue;
				const first = section.fields_list[0]?.df.fieldname;
				if (first === "naming_series" || first === "issue") {
					$('<div class="repair-section-caption"></div>')
						.text(frm.doctype === "Issue" ? __("Request Details") : __("Repair Item Details"))
						.prependTo(section.wrapper);
				}
			}
			$(frm.wrapper)
				.on("dirty.repair-header", () => update_header(frm))
				.on(
					"change.repair-header",
					'[data-fieldname="subject"] input, [data-fieldname="status"] select',
					() => update_header(frm)
				);
		} catch (error) {
			restore(frm);
			frm._repair_ui_failed = true;
			console.error("Repair UI could not be rendered", error);
			refresh(frm);
			frappe.show_alert({
				message: __(
					"The new repair interface could not be loaded. The standard form is available; your input is preserved."
				),
				indicator: "orange",
			});
		}
	}

	erpnext.repair_form = {
		refresh,
		update_header,
		prompt: (...args) => erpnext.repair_dialog.prompt(...args),
	};
	$(document)
		.off("show.bs.modal.repair-ui")
		.on("show.bs.modal.repair-ui", ".modal", function () {
			const frm = window.cur_frm;
			const enabled =
				frappe.get_route()[0] === "Form" &&
				["Issue", "Repair Unit"].includes(frm?.doctype) &&
				!standard(frm);
			$(this).toggleClass(scope, Boolean(enabled));
		});
})();
