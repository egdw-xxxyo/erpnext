frappe.provide("erpnext.doc_help");

erpnext.doc_help.is_manager = function () {
	return frappe.user.has_role(["System Manager", "Wiki Manager"]);
};

erpnext.doc_help.add_button = function (page, doctype) {
	if (!page || !doctype) return;
	page.icon_group.find(".doc-help-btn").remove();
	const has_link = Boolean(frappe.get_meta(doctype)?.documentation);
	if (!has_link && !erpnext.doc_help.is_manager()) return;
	page.add_action_icon(
		"help",
		() => (has_link ? erpnext.doc_help.show(doctype) : erpnext.doc_help.edit(doctype)),
		"doc-help-btn" + (has_link ? "" : " doc-help-btn--empty"),
		has_link ? __("Help") : __("Link a help page")
	);
};

erpnext.doc_help.refresh_buttons = function (doctype) {
	if (cur_frm?.doctype === doctype) erpnext.doc_help.add_button(cur_frm.page, doctype);
	if (cur_list?.doctype === doctype) erpnext.doc_help.add_button(cur_list.page, doctype);
};

erpnext.doc_help.show = async function (doctype) {
	const { message: help } = await frappe.call({
		method: "erpnext.utilities.doc_help.get_help",
		args: { doctype },
	});
	if (!help?.url) return erpnext.doc_help.edit(doctype);
	if (help.external) return window.open(help.url, "_blank", "noopener");
	if (help.missing) {
		frappe.msgprint({
			title: __("Help"),
			indicator: "orange",
			message: __("The help page is not published or you do not have access to it."),
		});
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: help.title,
		size: "extra-large",
		fields: [{ fieldtype: "HTML", fieldname: "content" }],
		primary_action_label: __("Open Page"),
		primary_action() {
			window.open(help.url, "_blank", "noopener");
			dialog.hide();
		},
	});
	if (erpnext.doc_help.is_manager()) {
		dialog.set_secondary_action_label(__("Change Help Page"));
		dialog.set_secondary_action(() => {
			dialog.hide();
			erpnext.doc_help.edit(doctype);
		});
	}

	const $content = $(`<div class="doc-help-content"></div>`).html(help.html);
	$content.find("a[href]").attr({ target: "_blank", rel: "noopener" });
	dialog.fields_dict.content.$wrapper.empty().append($content);
	dialog.show();
};

erpnext.doc_help.edit = async function (doctype) {
	if (!erpnext.doc_help.is_manager()) return;
	const { message: pages } = await frappe.call("erpnext.utilities.doc_help.get_wiki_pages");
	const current = frappe.get_meta(doctype)?.documentation || "";

	const dialog = new frappe.ui.Dialog({
		title: __("Help Page for {0}", [__(doctype)]),
		fields: [
			{
				fieldtype: "Autocomplete",
				fieldname: "url",
				label: __("Wiki Page or URL"),
				options: pages || [],
				ignore_validation: 1,
				default: current,
				description: __("Pick a wiki page or paste any link. Leave empty to remove the help page."),
			},
		],
		primary_action_label: __("Save"),
		async primary_action(values) {
			const url = (values.url || "").trim();
			await frappe.call({
				method: "erpnext.utilities.doc_help.set_help",
				args: { doctype, url },
				freeze: true,
			});
			frappe.get_meta(doctype).documentation = url || null;
			dialog.hide();
			erpnext.doc_help.refresh_buttons(doctype);
			frappe.show_alert({ message: __("Help page saved"), indicator: "green" });
		},
	});
	dialog.show();
};

$(document).on("form-refresh", (_e, frm) => {
	if (frm?.meta && !frm.meta.istable) erpnext.doc_help.add_button(frm.page, frm.doctype);
});

const setup_list_page_head = frappe.views.ListView.prototype.setup_page_head;
frappe.views.ListView.prototype.setup_page_head = function () {
	setup_list_page_head.call(this);
	erpnext.doc_help.add_button(this.page, this.doctype);
};

frappe.dom.set_style(`
	.doc-help-btn--empty { opacity: 0.45; }
	.doc-help-content { font-size: var(--text-base); line-height: 1.6; }
	.doc-help-content img, .doc-help-content video { max-width: 100%; height: auto; }
	.doc-help-content pre { white-space: pre-wrap; }
	.doc-help-content table { width: 100%; margin-bottom: var(--margin-md); }
	.doc-help-content td, .doc-help-content th { border: 1px solid var(--border-color); padding: 4px 8px; }
`);
