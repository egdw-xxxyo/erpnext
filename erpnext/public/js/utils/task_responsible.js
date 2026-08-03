frappe.provide("erpnext.projects");

erpnext.projects.get_task_responsible_field = () => ({
	fieldtype: "MultiSelectPills",
	fieldname: "responsible",
	label: __("Responsible"),
	get_data: (txt) => frappe.db.get_link_options("User", txt, { user_type: "System User", enabled: 1 }),
});

erpnext.projects.assign_task_responsible = (doctype, name, users, frm) => {
	if (!users || !users.length) return;
	return frappe
		.call({
			method: "frappe.desk.form.assign_to.add",
			args: { doctype, name, assign_to: JSON.stringify(users) },
		})
		.then(() => {
			if (frm && frm.sidebar) {
				frm.sidebar.reload_docinfo();
			}
		});
};

frappe.ui.form.TaskQuickEntryForm = class TaskQuickEntryForm extends frappe.ui.form.QuickEntryForm {
	render_dialog() {
		this.mandatory = this.mandatory.concat([erpnext.projects.get_task_responsible_field()]);
		super.render_dialog();

		// Dialog/FieldGroup debounces a shared "change"/"awesomplete-selectcomplete"
		// listener (refresh_dependency) that re-renders fields ~100ms after any
		// selection, racing MultiSelectPills' own pill DOM update and dropping the
		// pill just picked. Re-apply the (deduped) value after that window closes.
		const field = this.dialog.fields_dict.responsible;
		field.$input.on("awesomplete-selectcomplete", () => {
			setTimeout(() => {
				field.set_value([...new Set(field.get_value() || [])]);
			}, 150);
		});
	}
	insert() {
		const responsible = this.dialog.get_value("responsible");
		return super.insert().then((doc) => {
			erpnext.projects.assign_task_responsible(doc.doctype, doc.name, responsible);
			return doc;
		});
	}
};

function toggle_new_task_responsible_picker(frm) {
	if (!frm.is_new()) {
		if (frm._responsible_control) {
			frm._responsible_control.$wrapper.remove();
			frm._responsible_control = null;
		}
		return;
	}
	if (frm._responsible_control) return;

	const anchor = frm.get_field("parent_task");
	if (!anchor) return;

	let $wrapper = $("<div></div>").insertAfter(anchor.$wrapper);
	frm._responsible_control = frappe.ui.form.make_control({
		parent: $wrapper,
		df: erpnext.projects.get_task_responsible_field(),
		render_input: true,
	});
	frm._responsible_control.refresh();
}

frappe.ui.form.on("Task", {
	onload_post_render: toggle_new_task_responsible_picker,
	refresh: toggle_new_task_responsible_picker,
	after_save(frm) {
		if (frm._responsible_control) {
			erpnext.projects.assign_task_responsible(
				frm.doctype,
				frm.docname,
				frm._responsible_control.get_value(),
				frm
			);
		}
	},
});
