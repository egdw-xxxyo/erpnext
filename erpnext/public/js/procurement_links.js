frappe.ui.form.on("Consolidated Purchase Order", {
	refresh(frm) {
		frm.dashboard?.links_area?.wrapper.addClass("hidden");
		if (
			!frm.is_new() &&
			frappe.model.can_create(frm.doctype) &&
			(frappe.user.has_role("Закупівельник") || frappe.session.user === "Administrator")
		) {
			frm.page.add_menu_item(__("Repeat order"), () => {
				if (frm.is_dirty()) {
					frappe.msgprint(__("Save your changes before repeating this order."));
					return;
				}
				frappe.confirm(
					__(
						"Create a new draft with these items? The initiator, supplier invoices and document links will not be copied."
					),
					() => {
						frappe.call({
							method: "erpnext.buying.procurement_order_reuse.repeat_consolidated_order",
							args: { source_name: frm.doc.name },
							freeze: true,
							callback(r) {
								if (!r.message) return;
								frappe.model.sync(r.message);
								frappe.set_route("Form", frm.doctype, r.message.name);
							},
						});
					}
				);
			});
		}
		const field = frm.get_field("custom_procurement_links");
		if (!field) return;
		if (frm.is_new()) {
			field.$wrapper.html(`<p class="text-muted">${__("Save the document to view its links.")}</p>`);
			return;
		}
		const name = frm.doc.name;
		field.$wrapper.html(`<p class="text-muted">${__("Loading...")}</p>`);
		frappe.call({
			method: "erpnext.buying.procurement_links.get_procurement_links",
			args: { source_name: name },
			callback(r) {
				if (frm.doc.name !== name) return;
				const escape = frappe.utils.escape_html;
				const groups = r.message || [];
				const cards = groups
					.map((group, index) => {
						const names = group.documents.length ? group.documents.map((doc) => doc.name) : [""];
						const listUrl = `${frappe.utils
							.get_form_link(group.doctype, "")
							.replace(/\/$/, "")}?name=${encodeURIComponent(JSON.stringify(["in", names]))}`;
						const create =
							["Purchase Order", "Purchase Invoice"].includes(group.doctype) &&
							frappe.model.can_create(group.doctype) &&
							frm.doc.docstatus === 1;
						return `<div class="col-md-4 mb-3"><div class="document-link" data-group="${index}"
						style="display:flex;align-items:center;gap:8px;border:1px solid var(--border-color);border-radius:var(--border-radius-md);padding:10px 12px;min-height:58px">
						<div class="document-link-badge" style="display:flex;align-items:center;gap:8px;flex:1;min-width:0"><a class="badge-link" href="${escape(
							listUrl
						)}">${escape(__(group.doctype))}</a>
						<span class="count badge" style="flex-shrink:0">${group.documents.length}</span></div>
						${
							create
								? `<button class="btn btn-new btn-secondary btn-xs icon-btn" style="flex-shrink:0" title="${escape(
										__("Create")
								  )}">${frappe.utils.icon("plus", "sm")}</button>`
								: ""
						}
					</div></div>`;
					})
					.join("");
				field.$wrapper.html(
					`<div class="form-documents mb-4"><div class="row">${cards}</div></div>` +
						groups
							.map((group) => {
								const rows = group.documents
									.map((doc) => {
										const url = frappe.utils.get_form_link(group.doctype, doc.name);
										const status = [__("Draft"), __("Submitted"), __("Cancelled")][
											doc.docstatus
										];
										return `<tr><td><a href="${escape(
											url
										)}" target="_blank" rel="noopener noreferrer">${escape(
											doc.name
										)}</a></td><td>${escape(status)}</td></tr>`;
									})
									.join("");
								return `<section class="mb-4"><h5>${escape(__(group.doctype))} (${
									group.documents.length
								})</h5>${
									rows
										? `<table class="table table-bordered"><thead><tr><th>${__(
												"Document"
										  )}</th><th>${__(
												"Status"
										  )}</th></tr></thead><tbody>${rows}</tbody></table>`
										: `<p class="text-muted">${__("No linked documents available.")}</p>`
								}</section>`;
							})
							.join("")
				);
				field.$wrapper
					.off("click.procurementLinks")
					.on("click.procurementLinks", ".btn-new", function () {
						const group = groups[$(this).closest(".document-link").data("group")];
						frm.make_new(group.doctype);
					});
			},
		});
	},
});

frappe.ui.form.on("Buying Settings", {
	setup(frm) {
		frm.set_query("approver", "custom_final_approvers", () => ({
			query: "erpnext.buying.procurement_links.get_final_approver_users",
		}));
	},
});
