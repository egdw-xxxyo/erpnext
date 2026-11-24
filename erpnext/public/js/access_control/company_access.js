frappe.provide("erpnext.company_access");

erpnext.company_access.names = (rows, field) => (rows || []).map((row) => row[field]).filter(Boolean);

erpnext.company_access.pills = (values) =>
	values
		.map((v) => `<span class="indicator-pill blue mr-1">${frappe.utils.escape_html(v)}</span>`)
		.join("");

erpnext.company_access.modules_html = (by_module) =>
	Object.entries(by_module)
		.map(
			([module, doctypes]) => `
			<div class="mb-3">
				<div class="text-muted small mb-1"><i class="fa fa-folder-o"></i> ${frappe.utils.escape_html(
					__(module)
				)}</div>
				<div>${doctypes
					.map(
						(doctype) =>
							`<a class="indicator-pill gray mr-1 mb-1" href="/app/${frappe.router.slug(
								doctype
							)}">${frappe.utils.escape_html(__(doctype))}</a>`
					)
					.join("")}</div>
			</div>`
		)
		.join("");
