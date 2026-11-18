frappe.ui.form.IssueQuickEntryForm = class IssueQuickEntryForm extends frappe.ui.form.QuickEntryForm {
	is_quick_entry() {
		if (this.doc.__islocal && frappe.get_user_settings(this.doctype).standard_repair_form !== true) {
			this.force = false;
			return false;
		}
		return super.is_quick_entry();
	}
};
