// Deal documents panel: shows the Opportunity's file attachments read-through on
// the Opportunity itself, its Quotation and its Sales Order. Upload always targets
// the Opportunity so documents live in one place.

frappe.provide("erpnext.deal_documents");

erpnext.deal_documents.DOCTYPES = ["Opportunity", "Quotation", "Sales Order"];

erpnext.deal_documents.render = async function (frm) {
	if (frm.is_new()) return;

	let data;
	try {
		data = await frappe.xcall("erpnext.crm.deal_documents.get_deal_documents", {
			doctype: frm.doctype,
			docname: frm.doc.name,
		});
	} catch (e) {
		return;
	}
	if (!data || !data.opportunity) return;

	const files = data.files || [];
	const rows =
		files
			.map(
				(f) =>
					`<div class="wa-doc-row"><a href="${frappe.utils.escape_html(
						f.file_url
					)}" target="_blank">${frappe.utils.escape_html(
						f.file_name || f.file_url
					)}</a></div>`
			)
			.join("") ||
		`<div class="text-muted" style="font-size:var(--text-sm);">${__("No documents yet")}</div>`;

	if (!document.getElementById("wa-doc-styles")) {
		$(`<style id="wa-doc-styles">
			.wa-doc-wrap{padding:8px;}
			.wa-doc-row{padding:4px 0;border-bottom:1px solid var(--border-color);font-size:var(--text-sm);}
			.wa-doc-actions{margin-top:8px;}
		</style>`).appendTo(document.head);
	}

	const uploadBtn =
		frm.doctype === "Opportunity"
			? `<div class="wa-doc-actions"><button class="btn btn-xs btn-default wa-doc-add">${__(
					"Attach Document"
			  )}</button></div>`
			: `<div class="wa-doc-actions"><button class="btn btn-xs btn-default wa-doc-add">${__(
					"Attach to Deal"
			  )}</button> <a class="btn btn-xs btn-default" href="/app/opportunity/${encodeURIComponent(
					data.opportunity
			  )}">${__("Open Opportunity")}</a></div>`;

	const html = `<div class="wa-doc-wrap">${rows}${uploadBtn}</div>`;

	if (frm.doctype === "Opportunity" && frm.fields_dict.deal_documents_html) {
		frm.fields_dict.deal_documents_html.$wrapper.html(html);
	} else {
		frm.dashboard.add_section(html, __("Deal Documents"));
	}

	frm.$wrapper.find(".wa-doc-add").off("click").on("click", () => {
		new frappe.ui.FileUploader({
			doctype: "Opportunity",
			docname: data.opportunity,
			on_success() {
				erpnext.deal_documents.render(frm);
			},
		});
	});
};

erpnext.deal_documents.DOCTYPES.forEach((dt) => {
	frappe.ui.form.on(dt, {
		refresh(frm) {
			erpnext.deal_documents.render(frm);
		},
	});
});
