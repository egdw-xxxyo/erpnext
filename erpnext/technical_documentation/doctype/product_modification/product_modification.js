// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// Everything here narrows a link field to what the card already decided. The subtype list
// is the type's subtypes, the attribute list is what the type and subtype declare, and the
// revision list is the revisions of the document in that very row. The same rules are
// enforced on the server, because a form can only narrow what it draws.

frappe.ui.form.on("Product Modification", {
	async setup(frm) {
		const types = await frappe.db.get_list("Technical Document Type", {
			filters: { has_modifications: 1 },
			pluck: "name",
			limit: 0,
		});

		frm.set_query("technical_document", () => ({ filters: { document_type: ["in", types] } }));

		frm.set_query("product_subtype", () => ({
			filters: { active: 1, ...(frm.doc.product_type ? { product_type: frm.doc.product_type } : {}) },
		}));

		frm.set_query("attribute", "attributes", () => ({
			filters: { name: ["in", declared_attributes(frm)] },
		}));

		// A package row names the type before the document, so the type is what narrows the
		// document list — otherwise the row asks for «Інструкція з пакування» and then offers
		// every document in the register, and the type it displays is decided by whatever is
		// picked despite having been chosen first.
		frm.set_query("technical_document", "documents", (doc, cdt, cdn) => ({
			filters: {
				...(locals[cdt][cdn].document_type ? { document_type: locals[cdt][cdn].document_type } : {}),
			},
		}));

		frm.set_query("document_revision", "documents", (doc, cdt, cdn) => ({
			filters: { technical_document: locals[cdt][cdn].technical_document || "" },
		}));
	},

	refresh(frm) {
		load_attributes(frm);
		lock_subtype(frm);
	},

	product_type(frm) {
		if (frm.doc.product_subtype) frm.set_value("product_subtype", null);
		load_attributes(frm);
		lock_subtype(frm);
	},

	product_subtype(frm) {
		load_attributes(frm);
	},
});

frappe.ui.form.on("Product Modification Document", {
	technical_document(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.document_revision) frappe.model.set_value(cdt, cdn, "document_revision", null);
		if (!row.technical_document) return;

		frappe.db
			.get_value("Technical Document", row.technical_document, "document_type")
			.then(({ message }) => {
				frappe.model.set_value(cdt, cdn, "document_type", message && message.document_type);
			});
	},

	// Changing the type after a document is already in the row leaves a row that says two
	// different things about the same document. The document is what goes, not the type: the
	// type is the field just changed, and the picker next to it now offers the documents that
	// answer to it.
	document_type(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.document_type || !row.technical_document) return;

		frappe.db
			.get_value("Technical Document", row.technical_document, "document_type")
			.then(({ message }) => {
				if (message && message.document_type === row.document_type) return;

				frappe.model.set_value(cdt, cdn, "technical_document", null);
				frappe.model.set_value(cdt, cdn, "document_revision", null);
			});
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

// The declared set is read once per type/subtype change and kept on the form, because the
// grid asks for it on every row it draws and the answer is the same for all of them.
function load_attributes(frm) {
	if (!frm.doc.product_type && !frm.doc.product_subtype) {
		frm.__declared_attributes = [];
		return;
	}

	frappe
		.xcall("erpnext.technical_documentation.attributes.get_attributes", {
			product_type: frm.doc.product_type,
			product_subtype: frm.doc.product_subtype,
		})
		.then((rows) => {
			frm.__declared_attributes = rows || [];
		});
}

function declared_attributes(frm) {
	return (frm.__declared_attributes || []).map((row) => row.attribute);
}
