frappe.provide("erpnext.company_access");

erpnext.company_access.render_scope = frappe.utils.debounce((frm) => {
	const field = frm.get_field("preview");
	frappe
		.call("erpnext.access_control.company_access.preview_scope", {
			modules: erpnext.company_access.names(frm.doc.modules, "module"),
			include: erpnext.company_access.names(frm.doc.include_doctypes, "document_type"),
			exclude: erpnext.company_access.names(frm.doc.exclude_doctypes, "document_type"),
		})
		.then(({ message }) => {
			const unusable = message.unusable.length
				? `<div class="alert alert-warning">${__(
						"No Company field, cannot be opened by company: {0}",
						[message.unusable.map((d) => frappe.utils.escape_html(__(d))).join(", ")]
				  )}</div>`
				: "";
			const body = message.count
				? `<p class="text-muted">${__("{0} document types", [
						message.count,
				  ])}</p>${erpnext.company_access.modules_html(message.by_module)}`
				: `<p class="text-muted">${__("Choose modules or document types")}</p>`;
			field.$wrapper.html(unusable + body);
		});
}, 300);

erpnext.company_access.doctype_query = (frm, mode) => ({
	query: "erpnext.access_control.company_access.doctype_query",
	filters: {
		mode,
		modules: erpnext.company_access.names(frm.doc.modules, "module"),
		include: erpnext.company_access.names(frm.doc.include_doctypes, "document_type"),
	},
});

frappe.ui.form.on("Company Access Scope", {
	setup(frm) {
		frm.set_query("include_doctypes", () => erpnext.company_access.doctype_query(frm, "include"));
		frm.set_query("exclude_doctypes", () => erpnext.company_access.doctype_query(frm, "exclude"));
		frm.set_df_property(
			"include_doctypes",
			"filter_description",
			__("Document types with a Company field outside the chosen modules")
		);
		frm.set_df_property("exclude_doctypes", "filter_description", __("Document types of this scope"));
		["include_doctypes", "exclude_doctypes"].forEach((field) =>
			frm.set_df_property(field, "only_select", 1)
		);
	},
	refresh: (frm) => erpnext.company_access.render_scope(frm),
	modules: (frm) => erpnext.company_access.render_scope(frm),
	include_doctypes: (frm) => erpnext.company_access.render_scope(frm),
	exclude_doctypes: (frm) => erpnext.company_access.render_scope(frm),
});
