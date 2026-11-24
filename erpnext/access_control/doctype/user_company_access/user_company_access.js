frappe.provide("erpnext.company_access");

erpnext.company_access.render_access = frappe.utils.debounce((frm) => {
	if (!frm.doc.user) {
		frm.get_field("base_companies").$wrapper.empty();
		frm.get_field("result").$wrapper.empty();
		return;
	}
	frappe
		.call("erpnext.access_control.company_access.preview_access", {
			user: frm.doc.user,
			grants: (frm.doc.grants || []).map(({ company, scope }) => ({ company, scope })),
		})
		.then(({ message }) => {
			const base = message.global.length
				? `<p>${__("Sees everywhere")}: ${erpnext.company_access.pills(message.global)}</p>`
				: `<p class="text-muted">${__(
						"No main company restriction: the user sees every company"
				  )}</p>`;
			const narrows = message.narrows
				? `<div class="alert alert-warning">${__(
						"The user has no main company, so these rows narrow the chosen document types to the listed companies"
				  )}</div>`
				: "";
			const skipped = message.skipped.length
				? `<div class="alert alert-info">${__("Already visible everywhere, rows skipped: {0}", [
						message.skipped.map(frappe.utils.escape_html).join(", "),
				  ])}</div>`
				: "";
			const companies = Object.entries(message.companies)
				.map(
					([company, by_module]) => `
					<div class="mb-4">
						<h5><i class="fa fa-building-o"></i> ${frappe.utils.escape_html(company)}</h5>
						${erpnext.company_access.modules_html(by_module)}
					</div>`
				)
				.join("");
			frm.get_field("base_companies").$wrapper.html(base);
			frm.get_field("result").$wrapper.html(
				narrows + skipped + (companies || `<p class="text-muted">${__("No extra companies")}</p>`)
			);
		});
}, 300);

frappe.ui.form.on("User Company Access", {
	refresh: (frm) => erpnext.company_access.render_access(frm),
	user: (frm) => erpnext.company_access.render_access(frm),
	grants_remove: (frm) => erpnext.company_access.render_access(frm),
});

frappe.ui.form.on("User Company Access Grant", {
	company: (frm) => erpnext.company_access.render_access(frm),
	scope: (frm) => erpnext.company_access.render_access(frm),
});
