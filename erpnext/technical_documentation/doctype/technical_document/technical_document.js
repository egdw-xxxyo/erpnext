// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// The form asks the server once and renders what it is given. The prototype built these
// panels here out of four generic queries and its own copy of the completeness rule; that
// copy could disagree with the register, so the arithmetic now lives on the server and this
// file only draws it.

// The one status value this file needs to know. The statuses are Ukrainian words in the
// schema, so this is the same string the server compares against, not a translation of it.
const REVISION_EFFECTIVE = "Чинна";

frappe.ui.form.on("Technical Document", {
	setup(frm) {
		frm.set_query("product_subtype", () => ({
			filters: { active: 1, ...(frm.doc.product_type ? { product_type: frm.doc.product_type } : {}) },
		}));

		// The three rules the server applies to a current revision, applied to the list the
		// field offers: a revision of this document, submitted, and the effective one. The
		// server keeps them anyway — a form can only narrow what it draws — but a field that
		// offers a revision it will then refuse is a question asked in bad faith.
		frm.set_query("current_revision", () => ({
			filters: { technical_document: frm.doc.name, docstatus: 1, revision_status: REVISION_EFFECTIVE },
		}));

		// A template written for one product suits no other, but a template written for none
		// suits all of them — those are the packages defined by the kind of document rather
		// than by what it describes, and leaving them out would hide the ones most documents
		// use.
		frm.set_query("requirement_template", () => ({
			filters: frm.doc.product_type ? { product_type: ["in", [frm.doc.product_type, ""]] } : {},
		}));
	},

	refresh(frm) {
		render_panels(frm);
		add_revision_button(frm);
		lock_subtype(frm);
	},

	document_type(frm) {
		load_type_flags(frm);
	},

	product_type(frm) {
		if (frm.doc.product_subtype) frm.set_value("product_subtype", null);
		lock_subtype(frm);
	},
});

// Until the type is chosen the subtype list is every subtype of every type, and whichever
// one is picked there decides the type that was supposed to be asked first — the card ends
// up filled in backwards. So the field waits: locked, visible, and saying what is missing,
// the same way the subtype filter waits in the list. A card that already carries a subtype
// without a type is left editable, because locking it would be locking the only field that
// could fix it.
function lock_subtype(frm) {
	const locked = !frm.doc.product_type && !frm.doc.product_subtype;

	frm.set_df_property("product_subtype", "read_only", locked ? 1 : 0);
	frm.set_df_property("product_subtype", "description", locked ? __("Pick a product type first") : "");
}

// The extension sections are driven by the type's flags, which the server puts on the
// document as it loads it. A document being created has never been loaded, so the flags
// are fetched the moment a type is chosen — computed, never stored on the document, so a
// flag switched off on the type is never left behind on the cards.
function load_type_flags(frm) {
	if (!frm.doc.document_type) {
		frm.doc.__onload = { ...(frm.doc.__onload || {}), type_flags: {} };
		frm.refresh_fields();
		return;
	}

	frappe.db
		.get_value("Technical Document Type", frm.doc.document_type, [
			"has_product_classification",
			"has_modifications",
			"requires_completeness",
		])
		.then(({ message }) => {
			frm.doc.__onload = { ...(frm.doc.__onload || {}), type_flags: message || {} };
			frm.refresh_fields();
		});
}

const REVISION_DOCTYPE = "Technical Document Revision";

// A revision is where the files live, so "add the next version" is the one action a card
// leads to often enough to earn the primary slot. It is not offered while the card is
// still being created, because a revision needs a saved document to point at.
function add_revision_button(frm) {
	if (frm.is_new() || !frappe.model.can_create(REVISION_DOCTYPE)) return;

	frm.add_custom_button(__("New Revision"), () => open_new_revision(frm)).addClass("btn-primary");
}

// Deliberately not `frappe.new_doc`: the revision has few mandatory fields, so that route
// opens the quick-entry dialog, and the dialog has no place for the files that are the
// point of a revision. The meta has to be loaded first — field defaults come from it, so a
// document built before it arrives is created without its draft status.
function open_new_revision(frm) {
	frappe.model.with_doctype(REVISION_DOCTYPE, () => {
		const revision = frappe.model.get_new_doc(REVISION_DOCTYPE);

		revision.technical_document = frm.doc.name;
		revision.creation_date = frappe.datetime.get_today();

		frappe.set_route("Form", REVISION_DOCTYPE, revision.name);
	});
}

const RELATION_DOCTYPE = "Technical Document Relation";

// A relation is recorded on one side only, so adding one from the card has to say which
// side this card is on: a methodology is "an annex to" three specifications, and the same
// pair entered the other way round says something else entirely. That question is answered
// by which table the button sits above — one button per direction, right where the rows it
// adds to are — so the dialog itself never asks it. It does say it: the types come in
// mirrored pairs («Має додаток» / «Додаток до»), and picking the wrong half of a pair
// records the opposite of what was meant, so the side this card is on is written out above
// the list rather than left to be inferred from the heading.
function open_relation_dialog(frm, direction) {
	frappe.model.with_doctype(RELATION_DOCTYPE, () => {
		const types = frappe.meta.get_docfield(RELATION_DOCTYPE, "relation_type").options;

		const dialog = new frappe.ui.Dialog({
			title: direction === "outgoing" ? __("This document refers to") : __("Referred to by"),
			fields: [
				{
					fieldname: "relation_type",
					fieldtype: "Select",
					label: __("Relation Type"),
					options: types,
					reqd: 1,
					description:
						direction === "outgoing"
							? __("Reads as: this document — relation — the document below")
							: __("Reads as: the document below — relation — this document"),
					onchange: () => update_package_hint(frm, dialog, direction),
				},
				{
					fieldname: "document",
					fieldtype: "Link",
					label: __("Document"),
					options: "Technical Document",
					reqd: 1,
					get_query: () => ({ filters: { name: ["!=", frm.doc.name] } }),
					onchange: () => update_package_hint(frm, dialog, direction),
				},
				{ fieldname: "package_hint", fieldtype: "HTML" },
				{ fieldname: "note", fieldtype: "Small Text", label: __("Note") },
			],
			primary_action_label: __("Add"),
			primary_action: (values) => save_relation(frm, dialog, direction, values),
		});

		dialog.show();
	});
}

// The relation types this hint reasons about, spelled the way the schema stores them: the
// two the package is read from, and the neutral one it can be confused with.
const RELATION_HAS_ANNEX = "Має додаток";
const RELATION_ANNEX_TO = "Додаток до";
const RELATION_RELATED_TO = "Повʼязаний з";

// Nothing about the completeness rule is announced up front: on most relations it is beside
// the point, and a warning shown to everyone is read by no one. It is said at the one moment
// it is about to matter — a document of a type this package still needs, being recorded as
// merely related to it — and it names the relation that would have filed it in the package.
// The same reasoning the missing row uses, at the moment the row is being created rather
// than after: «Повʼязаний з» is the one type that says nothing about membership either way,
// so it is the one that can be meant as an annex. The dialog then records exactly what was
// asked for, hint or no hint.
function update_package_hint(frm, dialog, direction) {
	const wrapper = dialog.get_field("package_hint").$wrapper;
	const expected = direction === "outgoing" ? RELATION_HAS_ANNEX : RELATION_ANNEX_TO;
	const document = dialog.get_value("document");
	const wanted = incomplete_types(frm);

	wrapper.empty();
	if (!document || dialog.get_value("relation_type") !== RELATION_RELATED_TO || !wanted.size) return;

	frappe.db.get_value("Technical Document", document, "document_type").then(({ message }) => {
		const type = message && message.document_type;
		const stale =
			dialog.get_value("document") !== document ||
			dialog.get_value("relation_type") !== RELATION_RELATED_TO;

		if (stale || !type || !wanted.has(type)) return;

		wrapper.html(
			`<div class="small text-muted">${esc(
				__("{0} is a document this package requires — only the relation {1} puts it there", [
					type,
					expected,
				])
			)}</div>`
		);
	});
}

// The types the package asks for and has not got. A row already satisfied is not worth a
// hint: the relation being added is then simply another relation.
function incomplete_types(frm) {
	const rows = (frm.__completeness && frm.__completeness.rows) || [];

	return new Set(rows.filter((row) => row.state_key !== "present").map((row) => row.document_type));
}

function save_relation(frm, dialog, direction, values) {
	const outgoing = direction === "outgoing";

	dialog.disable_primary_action();
	frappe
		.xcall("frappe.client.insert", {
			doc: {
				doctype: RELATION_DOCTYPE,
				main_document: outgoing ? frm.doc.name : values.document,
				related_document: outgoing ? values.document : frm.doc.name,
				relation_type: values.relation_type,
				note: values.note,
			},
		})
		.then(() => {
			dialog.hide();
			frappe.show_alert({ message: __("Relation added"), indicator: "green" });
			render_panels(frm);
		})
		.finally(() => dialog.enable_primary_action());
}

const PANEL_FIELDS = ["revisions_html", "relations_html", "completeness_html", "modifications_html"];

const COMPLETENESS_INDICATORS = {
	present: "green",
	expired: "orange",
	outdated: "red",
	missing: "gray",
};

function render_panels(frm) {
	if (frm.is_new()) {
		PANEL_FIELDS.forEach((field) => set_panel(frm, field, ""));
		return;
	}

	frappe
		.call({
			method: "erpnext.technical_documentation.panels.get_panels",
			args: { document: frm.doc.name },
		})
		.then(({ message }) => {
			if (!message) return;

			set_panel(frm, "revisions_html", revisions_html(message.revisions));
			set_panel(frm, "relations_html", relations_html(message.relations));
			bind_relation_buttons(frm);
			frm.__completeness = message.completeness;
			set_panel(frm, "completeness_html", completeness_html(message.completeness));
			set_panel(frm, "modifications_html", modifications_html(message.modifications));
		})
		.catch(() => {
			PANEL_FIELDS.forEach((field) => set_panel(frm, field, muted(__("Could not load this section"))));
		});
}

function set_panel(frm, fieldname, html) {
	const field = frm.fields_dict[fieldname];
	if (field) field.$wrapper.html(html);
}

const esc = (value) => frappe.utils.escape_html(String(value == null ? "" : value));

const muted = (text) => `<div class="text-muted">${esc(text)}</div>`;

function doc_link(doctype, name, label) {
	const route = frappe.router.slug(doctype);
	return `<a href="/app/${route}/${encodeURIComponent(name)}">${esc(label || name)}</a>`;
}

function file_link(url, label) {
	return url ? `<a href="${esc(url)}" target="_blank">${esc(label)}</a>` : "";
}

function date(value) {
	return value ? frappe.datetime.str_to_user(value) : "";
}

function indicator(colour, text) {
	return `<span class="indicator-pill ${colour}">${esc(text)}</span>`;
}

function table(headers, rows, empty) {
	if (!rows.length) return muted(empty);

	const head = headers.map((header) => `<th>${esc(header)}</th>`).join("");
	return `<div class="table-responsive"><table class="table table-bordered table-sm">
		<thead><tr>${head}</tr></thead>
		<tbody>${rows.join("")}</tbody>
	</table></div>`;
}

function summary(parts) {
	return `<div class="mb-3 text-muted">${parts.filter(Boolean).map(esc).join(" · ")}</div>`;
}

function revisions_html(panel) {
	const rows = panel.rows.map((rev) => {
		const files = [
			file_link(rev.word_file, "Word"),
			file_link(rev.pdf_file, "PDF"),
			file_link(rev.signed_scan, __("Scan")),
			file_link(rev.additional_attachment, __("Annex")),
		]
			.filter(Boolean)
			.join(" · ");

		const badge = rev.is_current ? ` ${indicator("green", __("Current version"))}` : "";

		return `<tr>
			<td class="text-nowrap">${doc_link("Technical Document Revision", rev.name, rev.revision_number)}${badge}</td>
			<td>${esc(rev.revision_title)}</td>
			<td>${esc(rev.revision_status)}</td>
			<td>${esc(date(rev.effective_date))}</td>
			<td>${esc(date(rev.end_date))}</td>
			<td>${esc(rev.change_basis)}</td>
			<td>${files || '<span class="text-muted">—</span>'}</td>
		</tr>`;
	});

	return (
		summary([`${__("Revisions")}: ${panel.total}`, `${__("In force")}: ${panel.effective}`]) +
		table(
			[
				__("Revision"),
				__("Title"),
				__("Status"),
				__("Effective Date"),
				__("Expiry Date"),
				__("Change Basis"),
				__("Files"),
			],
			rows,
			__("This document has no revisions yet")
		)
	);
}

// The buttons are drawn as part of the panel and wired up after it is put into the DOM,
// because the panel is replaced wholesale on every refresh and any handler bound to the
// old markup goes with it.
function bind_relation_buttons(frm) {
	const field = frm.fields_dict.relations_html;
	if (!field) return;

	field.$wrapper.find("[data-relation-direction]").on("click", (event) => {
		open_relation_dialog(frm, $(event.currentTarget).attr("data-relation-direction"));
	});

	field.$wrapper.find("[data-remove-relation]").on("click", (event) => {
		event.preventDefault();
		const button = $(event.currentTarget);
		remove_relation(frm, button.attr("data-remove-relation"), button.attr("data-relation-label"));
	});
}

// A relation is a statement about two documents, not a document of its own, so a wrong one
// is worth taking back rather than keeping for the record — the documents it pointed at are
// untouched either way. It is still asked about first: the row is deleted for both cards at
// once, and the other one is not on screen to notice.
function remove_relation(frm, relation, label) {
	frappe.confirm(__("Remove the relation to {0}?", [label]), () => {
		frappe.xcall("frappe.client.delete", { doctype: RELATION_DOCTYPE, name: relation }).then(() => {
			frappe.show_alert({ message: __("Relation removed"), indicator: "green" });
			render_panels(frm);
		});
	});
}

function relation_button(direction, label) {
	if (!frappe.model.can_create(RELATION_DOCTYPE)) return "";

	return `<button class="btn btn-xs btn-default ml-2" data-relation-direction="${direction}">
		${esc(label)}
	</button>`;
}

function remove_relation_link(row) {
	if (!frappe.model.can_delete(RELATION_DOCTYPE)) return "";

	return `<a href="#" class="text-muted" data-remove-relation="${esc(row.relation)}"
		data-relation-label="${esc(row.document_code || row.name)}">${__("Remove")}</a>`;
}

// Each table is read as a sentence, and the two tables read from opposite ends. The card
// itself is the subject of the first — «this document · Має додаток · ІПАК» — so the
// relation opens the row and the other document follows it. In the second the other
// document is the subject: putting the type first there would leave the sentence starting
// with a verb whose subject is two columns away.
function relations_html(panel) {
	const columns = (row, direction) => {
		const relation = `<td>${esc(row.relation_type)}</td>`;
		const document = `<td>${doc_link("Technical Document", row.name, row.document_code || row.name)}<br>
			<span class="text-muted">${esc(row.document_title)}</span></td>`;

		return direction === "outgoing" ? relation + document : document + relation;
	};

	const headers = (direction) =>
		direction === "outgoing"
			? [__("Relation Type"), __("Document")]
			: [__("Document"), __("Relation Type")];

	const section = (title, rows, empty, direction) =>
		`<div class="mb-4"><div class="mb-2"><b>${esc(title)}</b>${relation_button(
			direction,
			__("Add")
		)}</div>${table(
			[...headers(direction), __("Type"), __("Status"), __("Effective Date"), __("Note"), ""],
			rows.map(
				(row) => `<tr>
					${columns(row, direction)}
					<td>${esc(row.document_type)}</td>
					<td>${esc(row.status)}</td>
					<td>${esc(date(row.current_revision_effective_date))}</td>
					<td>${esc(row.note)}</td>
					<td>${remove_relation_link(row)}</td>
				</tr>`
			),
			empty
		)}</div>`;

	return (
		section(__("This document refers to"), panel.outgoing, __("No related documents yet"), "outgoing") +
		section(__("Referred to by"), panel.incoming, __("No document refers to this one"), "incoming")
	);
}

function completeness_html(panel) {
	if (!panel.template) return muted(__("No requirement template selected"));

	const percent = panel.required ? Math.round((panel.present * 100) / panel.required) : 0;
	const rows = panel.rows.map(
		(row) => `<tr>
			<td>${indicator(COMPLETENESS_INDICATORS[row.state_key] || "gray", row.state)}</td>
			<td>${esc(row.document_type)}</td>
			<td>${esc(row.mandatory ? __("Yes") : __("No"))}</td>
			<td>${related_cell(row)}</td>
			<td>${esc(row.note)}</td>
		</tr>`
	);

	return (
		summary([
			`${__("Template")}: ${panel.template}`,
			`${__("Mandatory documents")}: ${panel.present} / ${panel.required} (${percent}%)`,
		]) +
		table(
			[__("State"), __("Required Document Type"), __("Mandatory"), __("Document"), __("Note")],
			rows,
			__("The template lists no requirements")
		)
	);
}

// A missing row whose document is already on the card, related but not declared an annex,
// says which one it means. The row stays missing — it is: the package is what was declared,
// not what is nearby — and the name is offered as the next step rather than as the answer.
function related_cell(row) {
	if (row.document) {
		return doc_link("Technical Document", row.document, row.document_title || row.document);
	}

	if (row.candidate) {
		return `<span class="text-muted">—</span>
			<div class="small text-muted mt-1">${__("Related but not declared an annex")}:
			${doc_link("Technical Document", row.candidate, row.candidate_title || row.candidate)}</div>`;
	}

	return `<span class="text-muted">${esc(row.restricted ? __("Access restricted") : "—")}</span>`;
}

function attributes_cell(attributes) {
	if (!attributes || !attributes.length) return '<span class="text-muted">—</span>';

	return attributes
		.map(
			(row) =>
				`<div class="text-nowrap"><span class="text-muted">${esc(row.attribute)}:</span> ${esc(
					row.value
				)}</div>`
		)
		.join("");
}

function modifications_html(panel) {
	const rows = panel.rows.map(
		(mod) => `<tr>
			<td>${doc_link("Product Modification", mod.name, mod.modification_code || mod.name)}<br>
				<span class="text-muted">${esc(mod.full_name)}</span></td>
			<td>${esc(mod.status)}</td>
			<td>${esc(mod.product_type)}</td>
			<td>${esc(mod.product_subtype)}</td>
			<td>${attributes_cell(mod.attributes)}</td>
			<td>${esc(mod.nsn_code)}</td>
			<td>${esc(date(mod.nsn_date))}</td>
		</tr>`
	);

	return (
		summary([
			`${__("Modifications")}: ${panel.total}`,
			`${__("Codified")}: ${panel.codified}`,
			`${__("Not codified")}: ${Math.max(panel.total - panel.codified, 0)}`,
		]) +
		table(
			[
				__("Modification"),
				__("Modification Status"),
				__("Product Type"),
				__("Subtype"),
				__("Attributes"),
				__("NSN"),
				__("Codification Date"),
			],
			rows,
			__("This specification has no modifications yet")
		)
	);
}
