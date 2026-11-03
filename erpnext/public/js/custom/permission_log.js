frappe.ui.form.on("Permission Log", {
	refresh(frm) {
		const PL = erpnext.permission_log;
		const render = () => {
			const summary = PL.describe(frm.doc).short;
			const user = frm.doc.for_doctype === "User" ? frm.doc.for_document : PL.current(frm.doc).user;
			const object = user ? frappe.user_info(user).fullname : __(frm.doc.for_document);
			const title = `${__(frm.doc.for_doctype)}: ${object}`;
			frm.page.set_title(title);
			frm.page.$title_area.find(".title-text-form").text(summary).attr("title", summary);
			$(".navbar-breadcrumbs .title-text-form, #navbar-breadcrumbs .title-text-form").text(summary);
			frm.$wrapper.find(".form-sidebar .form-title-text .bold").text(summary).attr("title", summary);
			document.title = `${summary} · ${title}`;
			frm.fields_dict.changed_values.$wrapper.html(PL.table_html(frm.doc));
		};
		render();
		Promise.all([erpnext.entity.load_users(PL.users_of(frm.doc)), PL.load_roles([frm.doc])]).then(
			(loaded) => loaded.some(Boolean) && render()
		);
	},
});
