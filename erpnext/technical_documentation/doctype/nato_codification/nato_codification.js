// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("NATO Codification", {
	async setup(frm) {
		const types = await frappe.db.get_list("Technical Document Type", {
			filters: { has_modifications: 1 },
			pluck: "name",
			limit: 0,
		});

		frm.set_query("technical_document", () => ({ filters: { document_type: ["in", types] } }));
		frm.set_query("product_modification", () =>
			frm.doc.technical_document ? { filters: { technical_document: frm.doc.technical_document } } : {}
		);
	},

	technical_document(frm) {
		frm.set_value("product_modification", null);
	},
});
