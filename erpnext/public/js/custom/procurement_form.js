(() => {
	if (erpnext.procurement_form_ui_loaded) return;
	erpnext.procurement_form_ui_loaded = true;

	const preference = "standard_procurement_form";
	const scope = "procurement-form-ui";
	const consolidated = "Consolidated Purchase Order";
	const material_request = "Material Request";
	const payment_request = "Payment Request";
	const doctypes = [consolidated, material_request, payment_request];
	const new_titles = {
		[consolidated]: "New Consolidated Purchase Order",
		[material_request]: "New Material Request",
		[payment_request]: "New Payment Request",
	};

	function is_standard(doctype) {
		return frappe.get_user_settings(doctype)[preference] === true;
	}

	function update_dialog_theme() {
		const [view, doctype] = frappe.get_route();
		document.body.classList.toggle(
			"procurement-dialog-theme",
			view === "Form" && doctypes.includes(doctype) && !is_standard(doctype)
		);
	}

	function fit_dialog_dropdown(event) {
		const input = event.target;
		const wrapper = input.closest(".awesomplete");
		const body = input.closest(".grid-form-body, .modal-body");
		const modal = input.closest(".procurement-dialog-theme .modal");
		const row = input.closest(
			".procurement-form-ui .form-in-grid, .procurement-dialog-theme .modal .form-in-grid"
		);
		if (
			!wrapper ||
			!body ||
			(!modal && !row) ||
			modal?.classList.contains("procurement-initiator-dialog")
		) {
			return;
		}
		const list =
			wrapper.querySelector(':scope > [role="listbox"]') ||
			document.getElementById(input.getAttribute("aria-controls") || input.getAttribute("aria-owns"));
		if (!list || list.hidden || list.classList.contains("procurement-dialog-list-positioned")) return;

		const frame = row || modal.querySelector(".modal-content");
		const home = list.parentElement;
		const overlay = document.createElement("div");
		overlay.className = "awesomplete procurement-dialog-list-overlay";
		const controller = new AbortController();
		const { signal } = controller;
		const set_height = (height) => list.style.setProperty("--procurement-list-height", `${height}px`);
		const restore = () => {
			if (overlay.isConnected) home.append(list);
			overlay.remove();
		};
		const position = () => {
			const anchor = input.getBoundingClientRect();
			const bounds = body.getBoundingClientRect();
			const frame_rect = frame.getBoundingClientRect();
			const top = Math.max(bounds.top, frame_rect.top, 0);
			const bottom = Math.min(bounds.bottom, frame_rect.bottom, window.innerHeight);
			const above = anchor.top - top - 6;
			const below = bottom - anchor.bottom - 6;
			const opens_above = below < 140 && above > below;
			overlay.hidden = anchor.bottom <= top || anchor.top >= bottom;
			set_height(Math.min(220, Math.max(0, opens_above ? above : below)));
			overlay.style.width = `${Math.min(anchor.width, bounds.width)}px`;
			overlay.style.left = `${anchor.left - frame_rect.left - frame.clientLeft + frame.scrollLeft}px`;
			overlay.style.top = `${
				(opens_above ? anchor.top - 6 : anchor.bottom + 6) -
				frame_rect.top -
				frame.clientTop +
				frame.scrollTop
			}px`;
			overlay.style.transform = opens_above ? "translateY(-100%)" : "";
		};
		const fit = () => {
			restore();
			// Grow a short dialog to show the list. Keep the list out of the scroll
			// area when the dialog already needs that space for its fields.
			list.style.display = "none";
			const max_height = parseFloat(getComputedStyle(frame).maxHeight);
			const room = max_height - (frame.offsetHeight - body.clientHeight + body.scrollHeight) - 8;
			list.style.removeProperty("display");
			if (!row && home === wrapper && room >= 112) {
				set_height(Math.min(220, room));
				return;
			}
			frame.append(overlay);
			overlay.append(list);
			position();
		};
		list.classList.add("procurement-dialog-list-positioned");
		fit();
		window.addEventListener("resize", fit, { signal });
		frame.addEventListener("scroll", () => overlay.isConnected && position(), { capture: true, signal });
		input.addEventListener(
			"awesomplete-close",
			() => {
				controller.abort();
				restore();
				list.classList.remove("procurement-dialog-list-positioned");
				list.style.removeProperty("--procurement-list-height");
			},
			{ once: true }
		);
	}

	function update_header(frm) {
		const header = frm.body.children(".procurement-form-header");
		if (!header.length) return;

		const is_consolidated = frm.doctype === consolidated;
		const is_new = frm.is_new();
		const kind = __(frm.doctype);
		const title = is_new
			? __(new_titles[frm.doctype])
			: (!is_consolidated && frm.doc.title) || frm.doc.name;
		header
			.find(".procurement-form-context")
			.text(!is_new && title !== frm.doc.name ? `${kind} · ${frm.doc.name}` : kind);
		header.find("h2").text(title);

		const procurement_status =
			is_consolidated && !is_new && !frm.is_dirty() && frm.doc.procurement_completion_status;
		const [label, color] = procurement_status
			? [__(procurement_status), erpnext.buying.get_procurement_status_color(procurement_status)]
			: frappe.get_indicator(frm.doc) || [];
		header
			.find(".procurement-form-status")
			.attr("class", `procurement-form-status indicator-pill no-indicator-dot ${color || ""}`)
			.text(label || "");
	}

	function update_request_owner(frm) {
		frm.body
			.find(".procurement-form-header .procurement-form-people")
			.html(erpnext.entity.user(frm.doc.custom_request_initiator_user || frm.doc.owner));
	}

	function apply_view(frm) {
		const enabled = !is_standard(frm.doctype);
		const is_consolidated = frm.doctype === consolidated;
		const wrapper = $(frm.wrapper);
		wrapper.toggleClass(scope, enabled).off("dirty.procurement-form");
		update_dialog_theme();
		if (is_consolidated) frm.trigger("render_supplier_invoice_actions");
		frm.body.find(".procurement-section-caption").remove();
		frm.body.children(".procurement-form-header").remove();
		if (!enabled) {
			if (is_consolidated) frm.trigger("render_procurement_users");
			if (frm.doctype === payment_request) erpnext.payment_request_form?.apply(frm, false);
			return;
		}

		$(`<header class="procurement-form-header">
			<div class="procurement-form-heading"><div class="procurement-form-context"></div><h2></h2></div>
			<div class="procurement-form-meta">
				<span class="procurement-form-status"></span><div class="procurement-form-people"></div>
			</div>
		</header>`).prependTo(frm.body);
		const details = frm.layout.sections_dict[is_consolidated ? "details_section" : "type_section"];
		if (details && !details.df.label) {
			$('<div class="procurement-section-caption"></div>')
				.text(__("Details"))
				.prependTo(details.wrapper);
		}
		wrapper.on("dirty.procurement-form", () => update_header(frm));
		update_header(frm);
		if (is_consolidated) frm.trigger("render_procurement_users");
		else if (frm.doctype === payment_request) erpnext.payment_request_form?.apply(frm, true);
		else update_request_owner(frm);
	}

	function refresh(frm) {
		frm.page.menu.find(".procurement-form-switch").closest("li").remove();
		frm.page
			.add_menu_item(
				is_standard(frm.doctype) ? __("Use New Procurement UI") : __("Return to Standard Frappe UI"),
				async () => {
					if (frm._saving_procurement_form_view) return;
					frm._saving_procurement_form_view = true;
					try {
						await frappe.model.user_settings.save(
							frm.doctype,
							preference,
							!is_standard(frm.doctype)
						);
						refresh(frm);
					} finally {
						frm._saving_procurement_form_view = false;
					}
				},
				false,
				null,
				true
			)
			.addClass("procurement-form-switch");
		apply_view(frm);
	}

	for (const doctype of doctypes) {
		frappe.ui.form.on(doctype, {
			refresh,
			title: update_header,
			status: update_header,
			procurement_completion_status: update_header,
		});
	}

	frappe.ui.form.on(material_request, {
		custom_request_initiator_user: update_request_owner,
	});
	frappe.router.on("change", update_dialog_theme);
	document.addEventListener("awesomplete-open", fit_dialog_dropdown);
})();
