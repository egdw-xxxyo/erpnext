// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// The form asks the server once and renders what it is given. The prototype built these
// panels here out of four generic queries and its own copy of the completeness rule; that
// copy could disagree with the register, so the arithmetic now lives on the server and this
// file only draws it.

frappe.ui.form.on("Technical Document", {
	refresh(frm) {
		render_panels(frm);
		add_revision_button(frm);
	},

	document_type(frm) {
		load_type_flags(frm);
	},
});

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

const PANEL_FIELDS = ["revisions_html", "relations_html", "completeness_html", "codification_overview_html"];

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
			set_panel(frm, "completeness_html", completeness_html(message.completeness));
			set_panel(frm, "codification_overview_html", modifications_html(message.modifications));
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
			<td>${doc_link("Technical Document Revision", rev.name, rev.revision_number)}${badge}</td>
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

function relations_html(panel) {
	const section = (title, rows, empty) =>
		`<div class="mb-4"><div class="mb-2"><b>${esc(title)}</b></div>${table(
			[__("Relation Type"), __("Document"), __("Type"), __("Status"), __("Effective Date"), __("Note")],
			rows.map(
				(row) => `<tr>
					<td>${esc(row.relation_type)}</td>
					<td>${doc_link("Technical Document", row.name, row.document_code || row.name)}<br>
						<span class="text-muted">${esc(row.document_title)}</span></td>
					<td>${esc(row.document_type)}</td>
					<td>${esc(row.status)}</td>
					<td>${esc(date(row.current_revision_effective_date))}</td>
					<td>${esc(row.note)}</td>
				</tr>`
			),
			empty
		)}</div>`;

	return (
		section(__("This document refers to"), panel.outgoing, __("No related documents yet")) +
		section(__("Referred to by"), panel.incoming, __("No document refers to this one"))
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

function related_cell(row) {
	if (row.document) {
		return doc_link("Technical Document", row.document, row.document_title || row.document);
	}

	return `<span class="text-muted">${esc(row.restricted ? __("Access restricted") : "—")}</span>`;
}

function modifications_html(panel) {
	const rows = panel.rows.map(
		(mod) => `<tr>
			<td>${doc_link("Product Modification", mod.name, mod.modification_code || mod.name)}<br>
				<span class="text-muted">${esc(mod.full_name)}</span></td>
			<td>${esc(mod.status)}</td>
			<td>${esc(mod.codification_status)}</td>
			<td>${esc(date(mod.codification_date))}</td>
			<td>${esc(mod.nsn_code)}</td>
			<td>${mod.codification ? doc_link("NATO Codification", mod.codification, mod.codification) : ""}</td>
		</tr>`
	);

	return (
		summary([
			`${__("Modifications")}: ${panel.total}`,
			`${__("Codified")}: ${panel.codified}`,
			`${__("In progress")}: ${panel.in_progress}`,
			`${__("Not codified")}: ${Math.max(panel.total - panel.codified - panel.in_progress, 0)}`,
		]) +
		table(
			[
				__("Modification"),
				__("Modification Status"),
				__("Codification Status"),
				__("Codification Date"),
				__("NSN"),
				__("Codification Record"),
			],
			rows,
			__("This specification has no modifications yet")
		)
	);
}
