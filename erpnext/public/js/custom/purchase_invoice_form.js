(() => {
	if (erpnext.purchase_invoice_form) return;

	const files_field = "custom_supplier_invoice_files_html";
	const attachment_field = "custom_recurring_invoice_pdf";
	const date_fields = ["posting_date", "posting_time", "due_date"];
	const posting_control = "set_posting_time";
	const vat_field = "custom_supplier_is_vat_payer";
	const paid_field = "custom_paid_outside_company";
	const payer_field = "custom_external_payer";
	const payment_note_field = "custom_external_payment_note";
	const source_fields = ["custom_consolidated_purchase_order", "custom_recurring_purchase"];
	const summary_field = "purchase-invoice-summary-field";
	const details_fields = [
		"posting_date",
		"posting_time",
		"due_date",
		"custom_set_responsible_employee",
		"company",
		"return_against",
		"amended_from",
	];
	const details_flags = [
		"is_paid",
		"is_return",
		"apply_tds",
		"update_outstanding_for_self",
		"update_billed_amount_in_purchase_order",
		"update_billed_amount_in_purchase_receipt",
	];
	const invoice_files = new WeakMap();
	const supplier_vat = new WeakMap();
	const payer_contacts = new WeakMap();
	const draft_dates = new WeakMap();
	const address_contacts = new WeakMap();
	const address_fields = {
		supplier_address: "address_display",
		dispatch_address: "dispatch_address_display",
		shipping_address: "shipping_address_display",
		billing_address: "billing_address_display",
	};

	function can_show(field) {
		return field && !Number(field.df.mask) && ["Read", "Write"].includes(field.get_status());
	}

	function file_anchor(frm, fieldname) {
		const target = frm.get_field(fieldname)?.$wrapper?.[0];
		if (!target) return;
		target.id ||= `purchase-invoice-${fieldname}`;
		target.tabIndex = -1;
		target.classList.add("purchase-invoice-file-anchor");
		return $('<a class="procurement-created-card-link">')
			.attr("href", `#${target.id}`)
			.text(__("Supplier Invoice Files"))
			.on("click", (event) => {
				event.preventDefault();
				const pane = target.closest(".tab-pane");
				const tab = frm.layout.tabs?.find((item) => item.wrapper[0] === pane);
				if (tab && !tab.is_active()) tab.set_active();
				const section_name = target.closest(".form-section")?.dataset.fieldname;
				const section = frm.layout.sections_dict[section_name];
				if (section?.is_collapsed()) section.collapse(false);
				requestAnimationFrame(() => {
					target.focus({ preventScroll: true });
					target.scrollIntoView({ block: "start", behavior: "smooth" });
				});
			});
	}

	function render_header(frm) {
		const header = frm.body.children(".procurement-form-header");
		if (!header.length) return;
		const owner = header.find(".procurement-form-people").empty().addClass("purchase-invoice-owner");
		if (frm.doc.owner) {
			$("<span>")
				.text(`${__("Created")}:`)
				.appendTo(owner);
			owner.append(erpnext.entity.user(frm.doc.owner));
		}

		const meta = header.find(".procurement-form-meta");
		meta.children(".purchase-invoice-header-links").remove();
		const links = $('<div class="purchase-invoice-header-links">');
		for (const name of source_fields) {
			const field = frm.get_field(name);
			const show = can_show(field);
			field?.$wrapper.toggleClass(summary_field, show && field.get_status() === "Read");
			const value = frm.doc[name];
			if (!show || !value) continue;
			const label =
				name === "custom_consolidated_purchase_order"
					? __("Created from a consolidated purchase order")
					: __("Created from a recurring purchase");
			const row = $('<div class="purchase-invoice-source-reference">').appendTo(links);
			$("<span>").text(`${label}:`).appendTo(row);
			$('<a class="procurement-created-card-link">')
				.attr("href", frappe.utils.get_form_link(field.df.options, value))
				.text(value)
				.appendTo(row);
		}

		const target =
			invoice_files.get(frm.doc) && can_show(frm.get_field(files_field))
				? files_field
				: frm.doc[attachment_field] && can_show(frm.get_field(attachment_field))
				? attachment_field
				: null;
		if (target) file_anchor(frm, target)?.appendTo(links);
		if (links.children().length) links.appendTo(meta);
	}

	function update_invoice_files(frm, has_files) {
		invoice_files.set(frm.doc, has_files);
		render_header(frm);
	}

	function append_requisite(details, label, value) {
		const fact = $("<div>").appendTo(details);
		$("<dt>").text(label).appendTo(fact);
		const item = $("<dd>").appendTo(fact);
		$("<span>")
			.text(value || "—")
			.appendTo(item);
		if (!value) return;
		const copy_label = __("Copy {0}", [label]);
		$('<button type="button" class="btn btn-default btn-xs purchase-invoice-requisite-copy">')
			.attr({ title: copy_label, "aria-label": copy_label })
			.html(frappe.utils.icon("copy", "sm"))
			.on("click", () => frappe.utils.copy_to_clipboard(String(value)))
			.appendTo(item);
	}

	function load_payer_contact(frm, payer) {
		const doc = frm.doc;
		const company = doc.company;
		const cached = payer_contacts.get(doc);
		if (cached?.payer === payer && cached.company === company) return cached;

		const contact = { payer, company };
		payer_contacts.set(doc, contact);
		const employee_filters = company ? { user_id: payer, company } : { user_id: payer };
		Promise.allSettled([
			frappe.xcall(
				"erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.get_procurement_user_names",
				{ users: [payer] }
			),
			frappe.model.can_read("Employee") &&
				frappe.db.get_value("Employee", employee_filters, [
					"employee_name",
					"department",
					"designation",
					"company_email",
					"cell_number",
				]),
			frappe.model.can_read("User") &&
				frappe.db.get_value("User", payer, ["email", "mobile_no", "phone"]),
		]).then(([names, employee, user]) => {
			contact.full_name = names.value?.[payer];
			contact.employee = employee.value?.message;
			contact.user = user.value?.message;
			if (frm.doc === doc && doc[payer_field] === payer && payer_contacts.get(doc) === contact) {
				const section = frm.get_field("supplier")?.section?.body;
				if (section?.length && frm.body.children(".procurement-form-header").length) {
					render_payer(frm, section);
				}
			}
		});
		return contact;
	}

	function messenger_phone_number(phone) {
		if (!phone || !/^[+\d().\s-]+$/.test(phone)) return "";
		let digits = phone.replace(/\D/g, "");
		if (/^0\d{9}$/.test(digits)) digits = `38${digits}`;
		else if (digits.startsWith("00")) digits = digits.slice(2);
		return /^[1-9]\d{9,14}$/.test(digits) ? digits : "";
	}

	function append_messenger_buttons(actions, number) {
		for (const [label, icon, url] of [
			[__("Telegram"), "paper-plane", `https://t.me/+${number}`],
			[__("WhatsApp"), "whatsapp", `https://wa.me/${number}`],
			[__("Viber"), "phone", `viber://chat?number=%2B${number}`],
		]) {
			const action = number
				? $('<a target="_blank" rel="noopener noreferrer">').attr("href", url)
				: $('<button type="button" disabled>').attr("title", __("Contact phone is not specified"));
			action
				.addClass("btn btn-xs btn-default")
				.text(` ${label}`)
				.prepend($('<i aria-hidden="true">').addClass(`fa fa-${icon}`))
				.appendTo(actions);
		}
	}

	function render_payer_actions(card, payer, number) {
		const actions = $('<div class="procurement-supplier-actions">').appendTo(card);
		append_messenger_buttons(actions, number);
		if (payer !== frappe.session.user && erpnext.whatsapp?.can_use_employee_chat?.()) {
			const chat = $(
				'<button type="button" class="btn btn-xs btn-default purchase-invoice-payer-chat">'
			)
				.text(__("Open chat"))
				.appendTo(actions);
			chat.on("click", async () => {
				chat.prop("disabled", true);
				try {
					const thread = await frappe.xcall(
						"erpnext.crm.page.employee_chat.employee_chat.create_thread",
						{
							participant_users: JSON.stringify([payer]),
						}
					);
					const bubble = erpnext.whatsapp.bubble;
					if (bubble) {
						if (!bubble.open || bubble.active_key !== "personal") bubble.open_source("personal");
						await bubble.refresh();
						bubble.open_thread(thread.name);
					} else {
						const view = frappe.pages["employee-chat"]?.chat_view;
						frappe.route_options = { thread: thread.name };
						await frappe.set_route("employee-chat");
						await view?.open_new(thread.name);
					}
				} catch {
					frappe.msgprint(__("Failed to open chat"));
				} finally {
					chat.prop("disabled", false);
				}
			});
		}
	}

	function append_detail(details, label, value, href) {
		const fact = $("<div>").appendTo(details);
		$("<dt>").text(label).appendTo(fact);
		const content = $("<dd>").appendTo(fact);
		if (href) $("<a>").attr("href", href).text(value).appendTo(content);
		else content.text(value || __("Not specified"));
	}

	function place_party_card(frm, section, card) {
		const dates = draft_dates.get(frm)?.card;
		if (dates?.parent()[0] === section[0]) card.insertBefore(dates);
		else card.appendTo(section);
	}

	function render_payer(frm, section) {
		section.children(".purchase-invoice-payer-card").remove();
		const flag = frm.get_field(paid_field);
		const payer_control = frm.get_field(payer_field);
		const note_control = frm.get_field(payment_note_field);
		const paid = Boolean(Number(frm.doc[paid_field]));
		const payer = frm.doc[payer_field];
		const show = Boolean(paid && payer && can_show(flag) && can_show(payer_control));
		flag?.$wrapper.toggleClass(summary_field, flag.get_status() === "Read" && (!paid || show));
		payer_control?.$wrapper.toggleClass(summary_field, show && payer_control.get_status() === "Read");
		const note = show && can_show(note_control) ? frm.doc[payment_note_field] : "";
		note_control?.$wrapper.toggleClass(
			summary_field,
			Boolean(note && note_control.get_status() === "Read")
		);
		if (!show) return;

		const contact = load_payer_contact(frm, payer);
		const { employee, user } = contact;
		const profile = frappe.user_info(payer);
		const full_name =
			[contact.full_name, employee?.employee_name, profile.fullname].find(
				(name) => name && (name !== payer || !payer.includes("@"))
			) || __("User");
		const sub = [__("Paid by Initiator"), employee?.designation, employee?.department]
			.filter(Boolean)
			.join(" · ");
		const phone = employee?.cell_number || user?.mobile_no || user?.phone;
		const number = messenger_phone_number(phone);
		const email = employee?.company_email || user?.email || profile.email;
		const card = $('<article class="procurement-created-card purchase-invoice-payer-card">');
		const supplier_card = section.children(".purchase-invoice-supplier-card");
		if (supplier_card.length) card.insertBefore(supplier_card);
		else place_party_card(frm, section, card);
		$('<div class="procurement-created-card-heading">')
			.append(erpnext.entity.user({ user: payer, full_name }, { sub }))
			.appendTo(card);
		const details = $('<dl class="purchase-invoice-payer-contact">').appendTo(card);
		append_detail(details, __("Phone"), phone, number && `tel:+${number}`);
		append_detail(
			details,
			__("Email"),
			email,
			email && `mailto:${encodeURIComponent(email).replace("%40", "@")}`
		);
		render_payer_actions(card, payer, number);
		if (note) $('<p class="purchase-invoice-payer-note">').text(note).appendTo(card);
	}

	function invoice_contact_data(frm, fieldname, doctype, name, snapshot, fetch) {
		const doc = frm.doc;
		if (!address_contacts.has(doc)) address_contacts.set(doc, new Map());
		const selections = address_contacts.get(doc);
		const previous = selections.get(fieldname);
		const can_fetch = name && frappe.model.can_read(doctype);
		if (previous && previous.name === name)
			return can_fetch || previous.cleared ? previous.value : snapshot;
		const cleared = !name && Boolean(previous?.name);
		const entry = { name, cleared, value: previous && (can_fetch || cleared) ? undefined : snapshot };
		selections.set(fieldname, entry);
		if (can_fetch && (doctype === "Contact" || !entry.value)) {
			fetch().then(
				(value) => {
					entry.value = value || entry.value;
					if (frm.doc === doc && doc[fieldname] === name && selections.get(fieldname) === entry) {
						render_address_contacts(frm);
					}
				},
				() => {}
			);
		}
		return entry.value;
	}

	function invoice_display_value(frm, name) {
		const field = frm.get_field(name);
		if (!can_show(field)) return;
		return frm.doc[name];
	}

	function address_text(html) {
		const template = document.createElement("template");
		template.innerHTML = html || "";
		template.content.querySelectorAll("script, style").forEach((node) => node.remove());
		template.content.querySelectorAll("br").forEach((node) => node.replaceWith("\n"));
		template.content.querySelectorAll("div, p, li").forEach((node) => node.append("\n"));
		return template.content.textContent
			.split("\n")
			.map((line) => line.trim())
			.filter(Boolean)
			.join("\n");
	}

	function render_address_contacts(frm) {
		if (!frm.body.children(".procurement-form-header").length) return;
		frm.body.find(".purchase-invoice-contact-cards").remove();
		function add_card(field, doctype, name, title, label, displayed_fields) {
			const section = field?.section?.body;
			for (const name of displayed_fields) {
				const control = frm.get_field(name);
				control?.$wrapper.toggleClass(
					summary_field,
					Boolean(section?.length && control.get_status() === "Read")
				);
			}
			if (!section?.length) return;
			field.$wrapper.toggleClass(summary_field, Boolean(title && field.get_status() === "Read"));
			if (!title) return;
			let cards = section.children(".purchase-invoice-contact-cards");
			if (!cards.length) cards = $('<div class="purchase-invoice-contact-cards">').appendTo(section);
			const card = $('<article class="procurement-created-card">').appendTo(cards);
			$('<div class="procurement-created-card-heading">')
				.append(
					erpnext.entity.html({
						name: title,
						sub: label,
						key: name || title,
						route: name && frappe.model.can_read(doctype) ? ["Form", doctype, name] : null,
					})
				)
				.appendTo(card);
			return card;
		}

		for (const [name, display] of Object.entries(address_fields)) {
			const field = frm.get_field(name);
			if (!field?.section?.body?.length) continue;
			const id = invoice_display_value(frm, name);
			const snapshot = invoice_display_value(frm, display);
			const value = invoice_contact_data(frm, name, "Address", id, snapshot, () =>
				frappe.xcall("frappe.contacts.doctype.address.address.get_address_display", {
					address_dict: id,
				})
			);
			const label = __(frm.get_field(display)?.df.label || "Address");
			const title = id ? frappe.utils.get_link_title("Address", id) || id : value && label;
			const card = add_card(field, "Address", id, title, id ? label : "", [display]);
			const text = address_text(value);
			if (text) $('<div class="purchase-invoice-address-text">').text(text).appendTo(card);
		}

		const field = frm.get_field("contact_person");
		if (!field?.section?.body?.length) return;
		const id = invoice_display_value(frm, "contact_person");
		const snapshot = {
			full_name: invoice_display_value(frm, "contact_display"),
			phone: invoice_display_value(frm, "contact_mobile"),
			email: invoice_display_value(frm, "contact_email"),
		};
		const [name, phone, email] = ["contact_display", "contact_mobile", "contact_email"];
		const contact =
			invoice_contact_data(frm, "contact_person", "Contact", id, snapshot, async () => {
				const data = await frappe.xcall("erpnext.support.repair_access.contact_details", {
					contact: id,
				});
				if (!Number(frm.doc.docstatus)) return data;
				return {
					...data,
					...Object.fromEntries(Object.entries(snapshot).filter(([, value]) => value)),
				};
			}) || {};
		const title = contact.full_name || id || (contact.phone || contact.email ? __("Contact Person") : "");
		const card = add_card(field, "Contact", id, title, __("Contact Person"), [name, phone, email]);
		if (!card) return;
		const details = $('<dl class="purchase-invoice-requisites">').appendTo(card);
		const number = messenger_phone_number(contact.phone);
		append_detail(details, __("Phone"), contact.phone, number && `tel:+${number}`);
		append_requisite(details, __("Email"), contact.email);
		append_messenger_buttons($('<div class="procurement-supplier-actions">').appendTo(card), number);
	}

	function render_details(frm, section) {
		section.children(".purchase-invoice-details-card").remove();
		const submitted = Number(frm.doc.docstatus) > 0;
		const fields = new Map();
		for (const name of [...details_fields, ...details_flags]) {
			const field = frm.get_field(name);
			if (field?.section?.body?.[0] !== section[0]) continue;
			const summarized = submitted && !Number(field.df.mask) && field.get_status() === "Read";
			field.$wrapper.toggleClass(summary_field, summarized);
			if (summarized) fields.set(name, field.df);
		}
		if (!fields.size) return;

		const card = $('<article class="procurement-created-card purchase-invoice-details-card">').attr(
			"aria-label",
			__("Details")
		);
		const facts = $("<dl>");
		const posting_time = fields.has("posting_time") && frm.doc.posting_time;
		const combine_posting = Boolean(posting_time && fields.has("posting_date") && frm.doc.posting_date);
		for (const name of details_fields) {
			const field = fields.get(name);
			const value = frm.doc[name];
			if (!field || !value || (name === "posting_time" && combine_posting)) continue;
			const label = __(field.label, null, frm.doctype);
			if (field.fieldtype === "Date") {
				const date = frappe.datetime.str_to_user(value);
				const text =
					name === "posting_date" && combine_posting
						? `${date} · ${frappe.datetime.str_to_user(posting_time, true)}`
						: date;
				append_detail(facts, label, text);
			} else if (field.fieldtype === "Time") {
				append_detail(facts, label, frappe.datetime.str_to_user(value, true));
			} else {
				const doctype = field.options;
				const title = frappe.utils.get_link_title(doctype, value) || value;
				const href = frappe.model.can_read(doctype) && frappe.utils.get_form_link(doctype, value);
				append_detail(facts, label, title, href);
			}
		}
		if (facts.children().length) card.append(facts);

		const flags = $('<div class="purchase-invoice-detail-flags">');
		for (const name of details_flags) {
			if (!fields.has(name) || !Number(frm.doc[name])) continue;
			$('<span class="indicator-pill no-indicator-dot gray">')
				.text(__(fields.get(name).label, null, frm.doctype))
				.appendTo(flags);
		}
		if (flags.children().length) card.append(flags);
		if (card.children().length) card.prependTo(section);
	}

	function render_parties(frm) {
		if (!frm.body.children(".procurement-form-header").length) return;
		const supplier_field = frm.get_field("supplier");
		const section = supplier_field?.section?.body;
		if (!section?.length) return;
		render_supplier(frm, supplier_field, section);
		render_payer(frm, section);
		render_details(frm, section);
	}

	function render_supplier(frm, supplier_field, section) {
		section.children(".purchase-invoice-supplier-card").remove();
		const { supplier, supplier_name } = frm.doc;
		const show = Boolean(supplier && can_show(supplier_field));
		const readonly = (field) => Boolean(show && can_show(field) && field.get_status() === "Read");
		const draft = !Number(frm.doc.docstatus);
		for (const name of ["supplier", "supplier_name", "tax_id", "edrpou"]) {
			const field = frm.get_field(name);
			const tax_identifier = name === "tax_id" || name === "edrpou";
			field?.$wrapper.toggleClass(summary_field, (draft && tax_identifier) || readonly(field));
		}
		const vat = supplier_vat.get(frm.doc);
		const vat_control = frm.get_field(vat_field);
		const show_vat = vat?.supplier === supplier && readonly(vat_control);
		vat_control?.$wrapper.toggleClass(summary_field, show_vat);
		if (!show) return;

		const card = $('<article class="procurement-created-card purchase-invoice-supplier-card">');
		place_party_card(frm, section, card);
		const heading = $('<div class="procurement-created-card-heading">').appendTo(card);
		heading.append(
			erpnext.entity.html({
				name: can_show(frm.get_field("supplier_name")) ? supplier_name || supplier : supplier,
				sub: __("Supplier"),
				key: supplier,
				route: ["Form", "Supplier", supplier],
			})
		);
		if (show_vat) {
			$("<span>")
				.addClass(`indicator-pill no-indicator-dot ${vat.payer ? "green" : "gray"}`)
				.text(vat.payer ? __("Is a VAT payer") : __("Is not a VAT payer"))
				.appendTo(heading);
		}
		const details = $('<dl class="purchase-invoice-requisites">');
		if (readonly(frm.get_field("tax_id"))) append_requisite(details, __("Tax ID"), frm.doc.tax_id);
		if (readonly(frm.get_field("edrpou"))) append_requisite(details, __("EDRPOU Code"), frm.doc.edrpou);
		if (details.children().length) card.append(details);
	}

	function update_supplier_vat(frm, payer) {
		supplier_vat.set(frm.doc, { supplier: frm.doc.supplier, payer });
		render_parties(frm);
	}

	function open_date_picker(field) {
		if (field.get_status() !== "Write") return;
		field.$input?.[0]?.focus({ preventScroll: true });
		if (!field.datepicker?.visible) field.datepicker?.show();
	}

	function update_date_action(frm) {
		const layout = draft_dates.get(frm);
		if (!layout) return;
		const manual = Boolean(Number(frm.doc[posting_control]));
		layout.edit.text(manual ? __("Reset") : __("Edit")).toggle(layout.control.get_status() === "Write");
	}

	function apply_draft_dates(frm, enabled) {
		const current = draft_dates.get(frm);
		if (!enabled || Number(frm.doc.docstatus) > 0) {
			if (!current) return;
			for (const [marker, node] of current.positions) marker.replaceWith(node);
			current.buttons.forEach((button) => button.remove());
			current.card.remove();
			draft_dates.delete(frm);
			return;
		}
		if (current) {
			update_date_action(frm);
			return;
		}

		const dates = date_fields.map((name) => frm.get_field(name));
		const control = frm.get_field(posting_control);
		const fields = [...dates, control];
		const section = dates[0]?.section?.body;
		if (
			!section?.length ||
			!fields.every((field) => field?.$wrapper?.length && field.section?.body?.[0] === section[0])
		) {
			return;
		}

		const card = $('<div class="procurement-created-card purchase-invoice-dates-card">').appendTo(
			section
		);
		const heading = $('<div class="purchase-invoice-dates-heading">').appendTo(card);
		$('<span class="purchase-invoice-dates-title">')
			.append($('<i class="fa fa-clock-o" aria-hidden="true">'), $("<strong>").text(__("Dates")))
			.appendTo(heading);
		const edit = $('<button type="button" class="btn btn-xs btn-default">').appendTo(heading);
		const body = $('<div class="purchase-invoice-dates-fields">').appendTo(card);
		const positions = fields.map(({ $wrapper }) => {
			const marker = document.createComment("purchase-invoice-date-position");
			$wrapper.before(marker).appendTo(body);
			return [marker, $wrapper[0]];
		});
		const buttons = dates.map((field) => {
			const label = __(field.df.label, null, frm.doctype);
			const icon = field.df.fieldtype === "Time" ? "fa-clock-o" : "fa-calendar";
			return $('<button type="button" class="btn btn-xs btn-default purchase-invoice-date-picker">')
				.attr({ title: label, "aria-label": label })
				.append($('<i aria-hidden="true">').addClass(`fa ${icon}`))
				.on("click", (event) => {
					event.stopPropagation();
					open_date_picker(field);
				})
				.appendTo(field.$input_wrapper);
		});
		const layout = { card, edit, control, positions, buttons };
		draft_dates.set(frm, layout);
		update_date_action(frm);
		edit.on("click", async () => {
			if (control.get_status() !== "Write") return;
			const doc = frm.doc;
			const manual = !Number(doc[posting_control]);
			edit.prop("disabled", true);
			try {
				await frm.set_value(posting_control, Number(manual));
				if (frm.doc !== doc || draft_dates.get(frm) !== layout) return;
				if (manual && dates[0].get_status() !== "Write") {
					await frm.trigger("set_posting_date_and_time_read_only");
				}
				if (manual && frm.doc === doc && draft_dates.get(frm) === layout) open_date_picker(dates[0]);
			} finally {
				edit.prop("disabled", false);
				update_date_action(frm);
			}
		});
	}

	function toggle_empty_tax_sections(frm, enabled) {
		const hide_empty = enabled && Number(frm.doc.docstatus) > 0;
		for (const name of ["taxes_section", "section_break_51", "totals"]) {
			const section = frm.layout.sections_dict[name];
			if (!section) continue;
			const hide =
				hide_empty &&
				!(name === "totals" && frm.doc.taxes?.length) &&
				!section.fields_list.some((field) => {
					const status = field.get_status();
					if (status === "Write") return true;
					if (status !== "Read") return false;
					const value = frm.doc[field.df.fieldname];
					if (Array.isArray(value)) return value.length > 0;
					if (field.df.fieldtype === "Currency") return Boolean(Number(value));
					return typeof value === "string" ? Boolean(value.trim()) : Boolean(value);
				});
			section.wrapper.toggleClass(summary_field, hide);
		}
	}

	function apply(frm, enabled) {
		toggle_empty_tax_sections(frm, enabled);
		apply_draft_dates(frm, enabled);
		frm.layout.sections_dict.section_break_26?.wrapper.toggleClass(
			"purchase-invoice-totals-card",
			enabled
		);
		for (const name of ["totals_section", "base_totals_section"]) {
			frm.layout.sections_dict[name]?.wrapper.toggleClass(
				"purchase-invoice-totals-card purchase-invoice-final-totals",
				enabled
			);
		}
		if (!enabled) {
			frm.body
				.find(
					".purchase-invoice-details-card, .purchase-invoice-supplier-card, .purchase-invoice-payer-card"
				)
				.remove();
			frm.body.find(`.${summary_field}`).removeClass(summary_field);
			frm.body.find(".purchase-invoice-contact-cards").remove();
			return;
		}
		render_header(frm);
		render_parties(frm);
		render_address_contacts(frm);
	}

	frappe.ui.form.on("Purchase Invoice", {
		supplier: render_parties,
		supplier_name: render_parties,
		tax_id: render_parties,
		edrpou: render_parties,
		company: render_parties,
		set_posting_time: update_date_action,
		[paid_field]: render_parties,
		[payer_field]: render_parties,
		[payment_note_field]: render_parties,
		custom_consolidated_purchase_order: render_header,
		custom_recurring_purchase: render_header,
		custom_recurring_invoice_pdf: render_header,
		contact_person: render_address_contacts,
		contact_display: render_address_contacts,
		contact_mobile: render_address_contacts,
		contact_email: render_address_contacts,
		supplier_address: render_address_contacts,
		address_display: render_address_contacts,
		dispatch_address: render_address_contacts,
		dispatch_address_display: render_address_contacts,
		shipping_address: render_address_contacts,
		shipping_address_display: render_address_contacts,
		billing_address: render_address_contacts,
		billing_address_display: render_address_contacts,
	});

	erpnext.purchase_invoice_form = { apply, update_invoice_files, update_supplier_vat };
})();
