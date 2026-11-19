(() => {
	if (erpnext.payment_request_form) return;

	const layouts = new WeakMap();
	const source_requests = new WeakMap();
	const transaction_vat = new WeakMap();
	const summary_fields = ["party_type", "party", "party_name", "reference_doctype", "reference_name"];
	const supplier_requisites = {
		custom_party_tax_id: "Tax ID",
		custom_party_edrpou: "EDRPOU Code",
	};
	const supplier_vat_field = "custom_supplier_is_vat_payer";
	const hidden_class = "payment-request-hidden";
	const preview_method = "erpnext.accounts.doctype.payment_request.payment_request.get_source_preview";
	const payments_method = "erpnext.accounts.doctype.payment_request.payment_request.get_linked_payments";
	const payments_tab = "payment_request_payments_tab";
	const transaction_fields = [
		"grand_total",
		"outstanding_amount",
		"currency",
		"party_account_currency",
		"is_a_subscription",
	];
	const vat_totals_field = "custom_supplier_vat_totals";

	function display_value(frm, fieldname) {
		const status = frm.get_field(fieldname)?.get_status();
		if (status === "Read" || status === "Write") return frm.doc[fieldname];
	}

	function hide_read_only_field(frm, fieldname, replaced) {
		const field = frm.get_field(fieldname);
		field?.$wrapper.toggleClass(hidden_class, Boolean(replaced) && field.get_status() === "Read");
	}

	function currency_value(value, currency) {
		if (value == null || value === "") return "—";
		return typeof value === "number" ? format_currency(value, currency) : String(value);
	}

	function is_preparing(frm) {
		const { workflow_state, docstatus } = frm.doc;
		return (
			frm.is_new() ||
			(!docstatus &&
				(!workflow_state || ["Чернетка", "Потребує доопрацювання"].includes(workflow_state)))
		);
	}

	function render_invoice_owner(frm) {
		const layout = layouts.get(frm);
		if (!layout) return;
		const owner = layout.preview?.invoice_owner;
		const initiator = display_value(frm, "custom_initiator_user");
		const label = owner
			? __("Invoice created by")
			: initiator
			? __("Payment initiator")
			: __("Payment Request Author");
		frm.body
			.find(".procurement-form-header .procurement-form-people")
			.html(erpnext.entity.user(owner || initiator || frm.doc.owner, { sub: label }));
	}

	function render_party(frm) {
		const layout = layouts.get(frm);
		if (!layout) return;
		const type = display_value(frm, "party_type");
		const party = display_value(frm, "party");
		const preview = layout.preview;
		const name =
			display_value(frm, "party_name") ||
			(party && preview?.party_type === type && preview.party === party && preview.party_name) ||
			party;
		const heading = layout.intro.find(".payment-request-party-identity").empty();
		if (name) {
			heading.html(
				erpnext.entity.html({
					name,
					sub: type && __(type),
					key: party || name,
					route: type && party ? ["Form", type, party] : null,
					card: true,
				})
			);
		}
		layout.intro.toggle(Boolean(name));
		for (const fieldname of ["party_type", "party", "party_name"]) {
			hide_read_only_field(frm, fieldname, name);
		}

		const compact = type === "Supplier" && !is_preparing(frm);
		const facts = layout.intro.find(".payment-request-party-requisites").empty();
		for (const [fieldname, label] of Object.entries(supplier_requisites)) {
			if (compact) append_fact(facts, __(label), display_value(frm, fieldname));
			hide_read_only_field(frm, fieldname, compact);
		}
		const vat = compact ? display_value(frm, supplier_vat_field) : null;
		const payer = Number(vat) === 1;
		layout.intro
			.find(".payment-request-vat-note")
			.toggle(vat != null)
			.toggleClass("green", payer)
			.toggleClass("gray", !payer)
			.text(payer ? __("Is a VAT payer") : __("Is not a VAT payer"));
		hide_read_only_field(frm, supplier_vat_field, compact);
	}

	function append_fact(facts, label, value) {
		if (value == null || value === "") return;
		const fact = $("<div>").appendTo(facts);
		$("<dt>").text(label).appendTo(fact);
		return $("<dd>").text(value).appendTo(fact);
	}

	function install_transaction_summary(frm) {
		const section = frm.layout.sections_dict.transaction_details?.wrapper;
		const request_type = frm.get_field("payment_request_type")?.section?.wrapper;
		if (!section?.length || !request_type?.length || section.parent()[0] !== request_type.parent()[0])
			return;
		const marker = document.createComment("payment-request-transaction-position");
		section.before(marker);
		request_type.after(section);
		const card = $(
			'<div class="frappe-control procurement-created-card payment-request-transaction-card"></div>'
		);
		section.children(".section-body").before(card);
		return { section, marker, card };
	}

	function render_transaction(frm) {
		const transaction = layouts.get(frm)?.transaction;
		if (!transaction) return;
		const { card } = transaction;
		card.empty();
		const compact = !is_preparing(frm);
		const values = {};
		for (const name of transaction_fields) {
			const field = frm.get_field(name);
			const summarized = compact && field?.get_status() === "Read";
			if (summarized) values[name] = frm.doc[name];
			field?.$wrapper.toggleClass(hidden_class, summarized);
		}

		const currency = display_value(frm, "currency");
		const account_currency = display_value(frm, "party_account_currency");
		const vat_field = frm.get_field(vat_totals_field);
		const vat = transaction_vat.get(frm.doc);
		const totals =
			values.grand_total != null && vat?.amount === values.grand_total && vat?.currency === currency
				? vat.totals
				: null;
		const show_vat = Boolean(totals) && ["Read", "Write"].includes(vat_field?.get_status());
		vat_field?.$wrapper.toggleClass(hidden_class, show_vat);

		const primary = $('<dl class="payment-request-transaction-amounts">');
		if (values.grand_total != null) {
			append_fact(
				primary,
				show_vat ? __("Total payable") : __("Amount"),
				currency_value(values.grand_total, currency)
			);
		}
		if (values.outstanding_amount != null) {
			append_fact(
				primary,
				__("Outstanding Amount"),
				currency_value(values.outstanding_amount, account_currency)
			);
		}

		const details = $("<dl>");
		if (show_vat) {
			append_fact(details, __("Total excluding VAT"), currency_value(totals.net, currency));
			append_fact(details, __("VAT"), currency_value(totals.vat, currency));
		}
		append_fact(details, __("Transaction Currency"), values.currency);
		append_fact(details, __("Party Account Currency"), values.party_account_currency);
		if (values.is_a_subscription != null) {
			append_fact(
				details,
				__("Is a Subscription"),
				Number(values.is_a_subscription) ? __("Yes") : __("No")
			);
		}
		if (primary.children().length) card.append(primary);
		if (details.children().length) card.append(details);
		card.toggleClass("hide-control", !card.children().length);
	}

	function update_transaction_vat(frm, data) {
		transaction_vat.set(frm.doc, {
			amount: frm.doc.grand_total,
			currency: data.currency,
			totals: data.visible ? data.totals : null,
		});
		render_transaction(frm);
	}

	function append_date(facts, label, value) {
		if (!value) return;
		append_fact(facts, label, frappe.datetime.str_to_user(value))?.addClass("payment-request-date");
	}

	function file_link(url, label) {
		if (!/^(?:\/files\/|\/private\/files\/|https?:\/\/)/i.test(url)) return;
		return $("<a class='procurement-created-card-link' target='_blank' rel='noopener noreferrer'>")
			.attr("href", url)
			.text(label);
	}

	function append_invoice_files(card, files) {
		const links = $("<div class='payment-request-source-files'>");
		const list = $("<ul>").appendTo(links);
		for (const { file_name, file_url } of files || []) {
			const link = file_link(file_url, file_name || __("Supplier Invoice PDF"));
			if (link) link.appendTo($("<li>").appendTo(list));
		}
		if (list.children().length) {
			$("<span>").text(__("Supplier Invoice PDF")).prependTo(links);
			card.append(links);
		}
	}

	function document_link(doctype, name) {
		return $("<a class='procurement-created-card-link'>")
			.attr("href", frappe.utils.get_form_link(doctype, name))
			.text(name);
	}

	function render_items(target, { items, currency, vat }, invoice) {
		const title = invoice ? __("Invoice Items") : __("Source Document Items");
		$("<h4 class='payment-request-items-title'>").text(title).appendTo(target);
		const prices = vat
			? [
					["rate", "Input price"],
					...(vat.show_net_rate ? [["net_rate", "Price excluding VAT"]] : []),
					["gross_rate", "Price including VAT (calculated)"],
					["gross_amount", "Amount"],
			  ]
			: [
					["rate", "Rate"],
					["amount", "Amount"],
			  ];
		const headings = ["Item", "Qty", "UOM", ...prices.map(([, label]) => label)].map((label) =>
			__(label)
		);
		const rows = items.map((item) => ({
			code: item.item_name && item.item_code !== item.item_name ? item.item_code : null,
			values: [
				item.item_name || item.item_code || "—",
				item.qty ?? "—",
				item.uom ? __(item.uom) : "—",
				...prices.map(([fieldname]) => currency_value(item[fieldname], currency)),
			],
		}));
		if (target.hasClass("payment-request-standard-items")) {
			render_frappe_items(target, title, headings, rows);
			return;
		}

		const scroller = $("<div class='payment-request-items-scroll'>").appendTo(target);
		const table = $("<table class='table table-bordered payment-request-items'>").appendTo(scroller);
		const head = $("<tr>").appendTo($("<thead>").appendTo(table));
		for (const label of headings) {
			$("<th scope='col'>").text(label).appendTo(head);
		}
		const body = $("<tbody>").appendTo(table);
		for (const { code, values } of rows) {
			const row = $("<tr>").appendTo(body);
			for (const value of values) $("<td>").text(value).appendTo(row);
			if (code) $("<small>").text(code).appendTo(row.children().first());
		}
	}

	function render_frappe_items(target, title, headings, rows) {
		const container = $('<div class="form-grid-container payment-request-items-grid"></div>').appendTo(
			target
		);
		const grid = $('<div class="form-grid" role="table"></div>')
			.attr("aria-label", title)
			.appendTo(container);
		grid[0].style.setProperty("--payment-request-price-columns", String(headings.length - 3));
		const head = $('<div class="grid-heading-row" role="rowgroup"></div>').appendTo(grid);
		const body = $('<div class="grid-body" role="rowgroup"></div>').appendTo(grid);
		append_frappe_items_row(head, headings, "columnheader");
		for (const { code, values } of rows) append_frappe_items_row(body, values, "cell", code);
	}

	function append_frappe_items_row(group, values, role, code) {
		const row = $(
			'<div class="grid-row" role="row"><div class="data-row" role="presentation"></div></div>'
		).appendTo(group);
		const cells = row.children();
		for (const value of values) {
			const cell = $('<div class="grid-static-col"></div>').attr("role", role).appendTo(cells);
			const content = $('<div class="static-area"></div>').text(value).appendTo(cell);
			if (role === "columnheader") content.attr("title", value);
		}
		if (code) $("<small>").text(code).appendTo(cells.children().first());
	}

	function prepare_source_card(frm, layout, type, name, invoice) {
		layout.preview = null;
		render_invoice_owner(frm);
		render_party(frm);

		layout.source
			.find(".section-head")
			.text(invoice ? __("Invoice and Counterparty") : __("Source Document and Counterparty"));
		const main = layout.source.find(".payment-request-source-main").empty();
		for (const fieldname of ["reference_doctype", "reference_name"]) {
			hide_read_only_field(frm, fieldname, type && name);
		}
		if (!type || !name) return;

		const card = $("<article class='procurement-created-card'>").appendTo(main);
		const header = $("<header class='procurement-created-card-heading'>").appendTo(card);
		$("<h4 class='procurement-created-card-title'>").text(__(type)).appendTo(header);
		document_link(type, name).appendTo(header);
		return card;
	}

	function standard_source_items(frm, show) {
		const body = frm.layout.sections_dict.party_details?.wrapper.children(".section-body");
		if (!body?.length) return;
		const existing = body.children(".payment-request-standard-items");
		if (!show) {
			existing.remove();
			return;
		}
		return existing.length
			? existing
			: $('<div class="frappe-control payment-request-standard-items"></div>').appendTo(body);
	}

	async function render_source(frm) {
		const layout = layouts.get(frm);
		const { name: payment_request, reference_doctype: type, reference_name: name } = frm.doc;
		const invoice = type?.endsWith("Invoice");
		const request = Symbol();
		source_requests.set(frm, request);
		const items =
			layout?.items || standard_source_items(frm, type === "Purchase Invoice" && Boolean(name));
		if (!items) return;
		items.empty();
		const card = layout && prepare_source_card(frm, layout, type, name, invoice);
		const message = $("<p class='payment-request-source-message' role='status'>").appendTo(items);
		if (!type || !name) {
			message.text(__("No source document linked."));
			return;
		}
		message.text(__("Loading source document…"));
		const preview = await frappe
			.xcall(preview_method, { reference_doctype: type, reference_name: name }, "GET", { silent: true })
			.catch(() => null);
		if (
			layouts.get(frm) !== layout ||
			source_requests.get(frm) !== request ||
			frm.doc.name !== payment_request ||
			frm.doc.reference_doctype !== type ||
			frm.doc.reference_name !== name
		)
			return;
		if (!preview) {
			message.text(__("Source document details are unavailable."));
			return;
		}

		if (card) {
			layout.preview = preview;
			render_invoice_owner(frm);
			render_party(frm);
			const facts = $("<dl>");
			append_fact(facts, __("Supplier Invoice Number"), preview.bill_no);
			append_date(facts, invoice ? __("Invoice Date") : __("Transaction Date"), preview.date);
			append_date(facts, __("Due Date"), preview.due_date);
			if (preview.total != null)
				append_fact(
					facts,
					__("Source Document Total"),
					currency_value(preview.total, preview.currency)
				);
			if (facts.children().length) card.append(facts);
			append_invoice_files(card, preview.supplier_invoice_files);
		}
		if (preview.items.length) {
			message.remove();
			render_items(items, preview, invoice);
		} else {
			message.text(__("No items to display."));
		}
	}

	function render_payment_card(container, doctype, payment) {
		const card = $("<article class='procurement-created-card'>").appendTo(container);
		const header = $("<header class='procurement-created-card-heading'>").appendTo(card);
		document_link(doctype, payment.name).appendTo(header);
		const status = [
			[__("Draft"), "gray"],
			[__("Submitted"), "green"],
			[__("Cancelled"), "red"],
		][payment.docstatus];
		if (status) {
			$("<span class='indicator-pill no-indicator-dot'>")
				.addClass(status[1])
				.text(status[0])
				.appendTo(header);
		}
		const facts = $("<dl>");
		append_date(facts, __("Posting Date"), payment.posting_date);
		if (doctype === "Payment Entry") {
			const receive = payment.payment_type === "Receive";
			const amount = receive ? payment.received_amount : payment.paid_amount;
			const currency = receive ? payment.paid_to_account_currency : payment.paid_from_account_currency;
			if (amount != null)
				append_fact(facts, __("Payment Entry Amount"), currency_value(amount, currency));
		}
		if (facts.children().length) card.append(facts);
		const instruction = file_link(payment.custom_fiscal_receipt, __("Open payment instruction"));
		if (instruction) {
			instruction.appendTo($("<div class='payment-request-instruction'>").appendTo(card));
		}
	}

	async function render_payments(frm) {
		const layout = layouts.get(frm);
		const target = frm.get_field("payment_request_payments_html")?.$wrapper;
		if (!layout || !target) return;
		const name = frm.doc.name;
		const request = Symbol();
		layout.payments_request = request;
		target.empty();
		const message = $("<p class='payment-request-source-message' role='status'>").appendTo(target);
		if (frm.is_new()) {
			message.text(__("Save the document to view its links."));
			return;
		}
		message.text(__("Loading..."));
		const groups = await frappe
			.xcall(payments_method, { payment_request: name }, "GET", { silent: true })
			.catch(() => null);
		if (layouts.get(frm) !== layout || layout.payments_request !== request || frm.doc.name !== name)
			return;
		if (!groups) {
			message.text(__("Linked payments are unavailable."));
			return;
		}
		if (!groups.some((group) => group.documents.length)) {
			message.text(__("No linked documents available."));
			return;
		}
		message.remove();
		const groups_container = $("<div class='procurement-created-cards'>").appendTo(target);
		for (const { doctype, documents } of groups) {
			if (!documents.length) continue;
			$("<h5>").text(__(doctype)).appendTo(groups_container);
			const cards = $("<div class='procurement-created-grid'>").appendTo(groups_container);
			for (const payment of documents) render_payment_card(cards, doctype, payment);
		}
	}

	function toggle_payments_tab(frm, enabled) {
		const tabs = frm.layout.tabs || [];
		const tab = tabs.find((tab) => tab.df.fieldname === payments_tab);
		if (!tab) return;
		tab.df.hidden = enabled ? 0 : 1;
		tab.refresh();
		if (!enabled && tab.is_active()) tabs.find((entry) => !entry.is_hidden())?.set_active();
		const bar = tab.tab_link.closest(".form-tabs-list");
		bar.toggleClass(
			"payment-request-single-tab",
			!enabled && tabs.filter((entry) => !entry.is_hidden()).length === 1
		);
		frm.dashboard?.links_area?.wrapper.toggleClass("payment-request-dashboard-links", enabled);
	}

	function apply(frm, enabled) {
		frm.get_field("section_break_10")?.wrapper.hide();
		frm.layout.sections_dict.party_details?.wrapper.toggleClass(
			"payment-request-standard-party",
			!enabled
		);
		for (const fieldname of ["branch_code", "swift_number"]) {
			frm.get_field(fieldname)?.$wrapper.toggleClass(hidden_class, enabled);
		}
		let layout = layouts.get(frm);
		if (!enabled) {
			toggle_payments_tab(frm, false);
			if (!layout) return render_source(frm);
			layouts.delete(frm);
			layout.source.remove();
			layout.intro.remove();
			layout.items.remove();
			layout.section.wrapper.removeClass("payment-request-party");
			layout.marker.replaceWith(layout.section.wrapper[0]);
			if (layout.transaction) {
				const { section, marker, card } = layout.transaction;
				card.remove();
				marker.replaceWith(section[0]);
				for (const name of [...transaction_fields, vat_totals_field]) {
					frm.get_field(name)?.$wrapper.removeClass(hidden_class);
				}
			}
			for (const fieldname of [
				...summary_fields,
				...Object.keys(supplier_requisites),
				supplier_vat_field,
			])
				hide_read_only_field(frm, fieldname, false);
			const route = frm.get_field("custom_payment_route_section")?.wrapper;
			route?.parent().prepend(route);
			return render_source(frm);
		}

		if (!layout) {
			const section = frm.layout.sections_dict.party_details;
			if (!section?.wrapper?.length) return;
			standard_source_items(frm, false);
			const marker = document.createComment("payment-request-party-position");
			section.wrapper.before(marker);
			section.wrapper.addClass("payment-request-party");
			// Frappe hides form sections without a visible control when it refreshes the layout.
			const source = $(`<div class="frappe-control payment-request-source">
				<h3 class="section-head"></h3>
				<div class="payment-request-source-main"></div>
			</div>`).prependTo(section.wrapper);
			const intro = $(`<div class="procurement-created-card payment-request-party-intro">
				<div class="payment-request-party-identity"></div>
				<dl class="payment-request-party-requisites"></dl>
				<span class="indicator-pill no-indicator-dot payment-request-vat-note"></span>
			</div>`).insertAfter(source);
			const items = $('<div class="payment-request-source-items"></div>').appendTo(section.wrapper);
			layout = { section, marker, intro, source, items, transaction: install_transaction_summary(frm) };
			layouts.set(frm, layout);
		}

		const parent = layout.section.wrapper.parent();
		const route = frm.get_field("custom_payment_route_section")?.wrapper;
		if (route?.length && route.parent()[0] === parent[0]) {
			parent.prepend(route);
			route.after(layout.section.wrapper);
		} else {
			parent.prepend(layout.section.wrapper);
		}
		const payments = render_payments(frm);
		render_transaction(frm);
		toggle_payments_tab(frm, true);
		return Promise.all([render_source(frm), payments]);
	}

	erpnext.payment_request_form = { apply, render_party, update_transaction_vat };
	frappe.ui.form.on("Payment Request", {
		party_type: render_party,
		party: render_party,
		party_name: render_party,
		workflow_state(frm) {
			render_party(frm);
			render_transaction(frm);
		},
		grand_total: render_transaction,
		outstanding_amount: render_transaction,
		currency: render_transaction,
		party_account_currency: render_transaction,
		is_a_subscription: render_transaction,
		custom_initiator_user: render_invoice_owner,
		custom_party_tax_id: render_party,
		custom_party_edrpou: render_party,
		custom_supplier_is_vat_payer: render_party,
		reference_doctype: render_source,
		reference_name: render_source,
	});
})();
