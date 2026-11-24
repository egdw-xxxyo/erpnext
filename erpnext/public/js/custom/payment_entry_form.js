(() => {
	if (erpnext.payment_entry_form) return;

	const instruction_field = "custom_fiscal_receipt";
	const party_requisites = {
		tax_id: ["custom_party_tax_id", "Tax ID"],
		edrpou: ["custom_party_edrpou", "EDRPOU Code"],
		iban: ["custom_party_iban", "IBAN"],
	};
	const vat_field = "custom_supplier_is_vat_payer";
	const hidden_field = "payment-entry-party-hidden";
	const bank_tab_name = "payment_entry_bank_transactions_tab";
	const invoice_section_name = "custom_supplier_invoice_files_section";
	const invoice_anchor = "payment-entry-supplier-invoices";
	const layouts = new WeakMap();
	const party_details = new WeakMap();
	const invoice_links = new WeakMap();

	function render_instruction(frm) {
		const layout = layouts.get(frm)?.instruction;
		if (!layout) return;

		const attached = Boolean(frm.doc[instruction_field]);
		const status = layout.field.get_status();
		layout.note
			.find(".payment-entry-instruction-status")
			.text(attached ? __("Attached") : __("Payment instruction has not been attached"));
		layout.note.find(".payment-entry-instruction-formats").toggle(!attached && status === "Write");
		layout.field.$wrapper.toggleClass(
			"payment-entry-instruction-read-empty",
			!attached && status === "Read"
		);
	}

	function place_instruction(frm) {
		const field = frm.get_field(instruction_field);
		const section = field?.section?.wrapper;
		const payment_type = frm.layout.sections_dict.type_of_payment?.wrapper;
		if (!section?.length || section.parent()[0] !== payment_type?.parent()[0]) return;

		const marker = document.createComment("payment-entry-instruction-position");
		section.before(marker);
		section.prependTo(payment_type.parent());
		section.addClass("payment-entry-instruction");

		const note = $(`<div class="payment-entry-instruction-note">
				<span class="payment-entry-instruction-icon" aria-hidden="true">
					${frappe.utils.icon("es-line-attachment", "sm")}
				</span>
				<div>
					<strong class="payment-entry-instruction-status" role="status"></strong>
					<div class="payment-entry-instruction-formats">PDF, JPG, JPEG, PNG</div>
				</div>
			</div>`).prependTo(field.$wrapper.children(".form-group"));
		return { field, section, marker, note };
	}

	function place_reference_actions(frm) {
		const section = frm.layout.sections_dict.section_break_14;
		if (!section?.head?.length || section.df.collapsible) return;
		const fields = ["get_outstanding_invoices", "get_outstanding_orders"]
			.map((name) => frm.get_field(name))
			.filter((field) => field?.section === section && field.$wrapper?.length);
		if (!fields.length) return;

		const head = section.head.addClass("payment-entry-reference-head");
		const toolbar = $('<div class="payment-entry-reference-actions">').appendTo(head);
		const positions = fields.map(({ $wrapper }) => {
			const marker = document.createComment("payment-entry-reference-action");
			$wrapper.before(marker).appendTo(toolbar);
			return [marker, $wrapper[0]];
		});
		return { head, toolbar, positions };
	}

	function can_show(field) {
		return field && !Number(field.df.mask) && ["Read", "Write"].includes(field.get_status());
	}

	function add_copyable_detail(details, label, value) {
		if (!value) return;
		const fact = $("<div>").appendTo(details);
		$("<dt>").text(label).appendTo(fact);
		const item = $("<dd>").appendTo(fact);
		$("<span>").text(value).appendTo(item);
		$('<button type="button" class="btn btn-default btn-xs payment-entry-party-copy">')
			.attr({ title: __("Copy {0}", [label]), "aria-label": __("Copy {0}", [label]) })
			.html(frappe.utils.icon("copy", "sm"))
			.on("click", () => frappe.utils.copy_to_clipboard(String(value)))
			.appendTo(item);
	}

	function render_party(frm) {
		const card = layouts.get(frm)?.party;
		if (!card?.length) return;

		const { party, party_type, party_name, party_bank_account, payment_type } = frm.doc;
		const show = Boolean(
			party && ["Pay", "Receive"].includes(payment_type) && can_show(frm.get_field("party"))
		);
		const supplier = show && party_type === "Supplier";
		const selection = party_details.get(frm.doc);
		const values = supplier && selection?.party === party ? selection.values : {};
		const name_field = frm.get_field("party_name");
		const show_name = can_show(name_field);
		name_field?.$wrapper.toggleClass(
			hidden_field,
			show && show_name && name_field.get_status() === "Read"
		);
		card.empty().toggle(show);

		const details = $('<dl class="payment-entry-party-requisites">');
		for (const [key, [fieldname, label]] of Object.entries(party_requisites)) {
			const field = frm.get_field(fieldname);
			const in_card = Boolean(supplier && can_show(field) && field.get_status() === "Read");
			field?.$wrapper.toggleClass(hidden_field, in_card);
			if (in_card && (key !== "iban" || selection?.bank_account === party_bank_account)) {
				add_copyable_detail(details, __(label), values[key]);
			}
		}

		const vat = frm.get_field(vat_field);
		const show_vat = Boolean(supplier && can_show(vat) && vat.get_status() === "Read");
		vat?.$wrapper.toggleClass(hidden_field, show_vat);
		if (!show) return;

		const heading = $('<div class="procurement-created-card-heading">').appendTo(card);
		const editable_supplier_name = supplier && name_field?.get_status() === "Write";
		const name = show_name && (editable_supplier_name ? values.supplier_name : party_name);
		heading.append(
			erpnext.entity.html({
				name: name || party,
				sub: __(party_type),
				key: party,
			})
		);
		if (show_vat && values.custom_is_vat_payer != null) {
			const payer = Boolean(Number(values.custom_is_vat_payer));
			$("<span>")
				.addClass(`indicator-pill no-indicator-dot ${payer ? "green" : "gray"}`)
				.text(payer ? __("Is a VAT payer") : __("Is not a VAT payer"))
				.appendTo(heading);
		}
		if (details.children().length) card.append(details);
	}

	function update_party_details(frm, values) {
		const { party, party_bank_account } = frm.doc;
		party_details.set(frm.doc, { party, bank_account: party_bank_account, values });
		render_party(frm);
	}

	function document_link(doctype, name) {
		return $('<a class="procurement-created-card-link">')
			.attr("href", frappe.utils.get_form_link(doctype, name))
			.text(name);
	}

	function render_invoice_links(frm) {
		if (!layouts.has(frm)) return;
		const header = frm.body.children(".procurement-form-header").find(".procurement-form-meta");
		header.children(".payment-entry-invoice-links").remove();
		const { invoices, has_files } = invoice_links.get(frm.doc) || {};
		if (!invoices?.length && !has_files) return;

		const links = $('<div class="payment-entry-invoice-links">').appendTo(header);
		if (invoices?.length) {
			const row = $('<div class="payment-entry-invoice-references">').appendTo(links);
			$("<span>").text(__("According to invoice")).appendTo(row);
			for (const name of invoices) document_link("Purchase Invoice", name).appendTo(row);
		}
		const section = frm.layout.sections_dict[invoice_section_name];
		if (has_files && section?.wrapper.length && !section.wrapper.hasClass("hide-control")) {
			const target = section.wrapper[0];
			$(target).attr({ id: invoice_anchor, tabindex: -1 });
			$('<a class="procurement-created-card-link">')
				.attr("href", `#${invoice_anchor}`)
				.text(__("Supplier Invoice Files"))
				.on("click", (event) => {
					event.preventDefault();
					const pane = section.wrapper.closest(".tab-pane")[0];
					const tab = frm.layout.tabs.find((item) => item.wrapper[0] === pane);
					if (tab && !tab.is_active()) tab.set_active();
					if (section.is_collapsed()) section.collapse(false);
					requestAnimationFrame(() => {
						target.focus({ preventScroll: true });
						target.scrollIntoView({ block: "start", behavior: "smooth" });
					});
				})
				.appendTo(links);
		}
	}

	function update_invoice_links(frm, invoices, has_files) {
		invoice_links.set(frm.doc, { invoices, has_files });
		render_invoice_links(frm);
	}

	function toggle_bank_tab(frm, enabled) {
		const tabs = frm.layout.tabs || [];
		const tab = tabs.find((item) => item.df.fieldname === bank_tab_name);
		if (!tab) return;
		tab.df.hidden = enabled ? 0 : 1;
		frm.layout.refresh_tabs();
		if (!enabled && tab.is_active()) tabs.find((item) => !item.is_hidden())?.set_active();
		tab.tab_link
			.closest(".form-tabs-list")
			.toggleClass(
				"payment-entry-single-tab",
				!enabled && tabs.filter((item) => !item.is_hidden()).length === 1
			);
		frm.dashboard?.links_area?.wrapper.toggleClass("payment-entry-bank-links-in-tab", enabled);
		return tab;
	}

	function render_bank_transaction(cards, transaction) {
		const card = $('<article class="procurement-created-card">').appendTo(cards);
		const heading = $('<div class="procurement-created-card-heading">').appendTo(card);
		document_link("Bank Transaction", transaction.name).appendTo(heading);
		if (transaction.status) {
			const color = { Reconciled: "green", Unreconciled: "orange", Cancelled: "red" }[
				transaction.status
			];
			$('<span class="indicator-pill no-indicator-dot">')
				.addClass(color || "gray")
				.text(__(transaction.status))
				.appendTo(heading);
		}
		const facts = $("<dl>");
		const values = {
			Date: transaction.date && frappe.datetime.str_to_user(transaction.date),
			"Reference Number": transaction.reference_number,
		};
		for (const [label, value] of Object.entries(values)) {
			if (!value) continue;
			const fact = $("<div>").appendTo(facts);
			$("<dt>").text(__(label)).appendTo(fact);
			$("<dd>").text(value).appendTo(fact);
		}
		if (facts.children().length) card.append(facts);
	}

	async function render_bank_transactions(frm) {
		const layout = layouts.get(frm);
		const target = frm.get_field("payment_entry_bank_transactions_html")?.$wrapper;
		if (!layout || !target?.length) return;
		const doc = frm.doc;
		const request = Symbol();
		layout.bank_request = request;
		const message = $('<p class="text-muted" role="status">').appendTo(target.empty());
		if (frm.is_new() || !frappe.model.can_read("Bank Transaction")) {
			message.text(
				frm.is_new()
					? __("Save the document to view its links.")
					: __("No linked documents available.")
			);
			return;
		}
		message.text(__("Loading..."));
		const transactions = await frappe
			.xcall(
				"frappe.client.get_list",
				{
					doctype: "Bank Transaction",
					fields: ["name", "date", "status", "reference_number"],
					filters: [
						["Bank Transaction Payments", "payment_document", "=", "Payment Entry"],
						["Bank Transaction Payments", "payment_entry", "=", doc.name],
					],
					order_by: "date desc, name asc",
					limit_page_length: 0,
				},
				"GET",
				{ silent: true }
			)
			.catch(() => null);
		if (layouts.get(frm) !== layout || frm.doc !== doc || layout.bank_request !== request) return;
		if (!transactions?.length) {
			message.text(__("No linked documents available."));
			return;
		}
		message.remove();
		const cards = $('<div class="procurement-created-grid">').appendTo(target);
		const unique = new Map(transactions.map((transaction) => [transaction.name, transaction]));
		for (const transaction of unique.values()) render_bank_transaction(cards, transaction);
	}

	function apply(frm, enabled) {
		const layout = layouts.get(frm);
		const bank_tab = toggle_bank_tab(frm, enabled);
		if (!enabled) {
			if (!layout) return;
			if (layout.instruction) {
				const { marker, section, field, note } = layout.instruction;
				marker.replaceWith(section[0]);
				section.removeClass("payment-entry-instruction");
				field.$wrapper.removeClass("payment-entry-instruction-read-empty");
				note.remove();
			}
			if (layout.reference_actions) {
				const { head, toolbar, positions } = layout.reference_actions;
				for (const [marker, field] of positions) marker.replaceWith(field);
				toolbar.remove();
				head.removeClass("payment-entry-reference-head");
			}
			layout.party?.remove();
			frm.body.find(`.${hidden_field}`).removeClass(hidden_field);
			layouts.delete(frm);
			return;
		}
		if (!layout) {
			const section = frm.layout.sections_dict.party_section;
			const party =
				section &&
				$('<div class="procurement-created-card payment-entry-party-card">').insertAfter(
					section.body
				);
			layouts.set(frm, {
				instruction: place_instruction(frm),
				party,
				reference_actions: place_reference_actions(frm),
			});
		}
		render_instruction(frm);
		render_party(frm);
		render_invoice_links(frm);
		if (bank_tab) render_bank_transactions(frm);
	}

	frappe.ui.form.on("Payment Entry", {
		[instruction_field]: render_instruction,
		payment_type: render_party,
		party_type: render_party,
		party: render_party,
		party_name: render_party,
		party_bank_account: render_party,
	});
	erpnext.payment_entry_form = { apply, update_party_details, update_invoice_links };
})();
