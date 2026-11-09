frappe.listview_settings["Commercial Offer"] = {
	add_fields: ["is_template", "disabled", "docstatus"],
	hide_name_column: false,

	onload(listview) {
		const get_args = listview.get_args.bind(listview);
		listview.get_args = () => {
			const args = get_args();
			const table = "`tabCommercial Offer`";
			args.order_by = `${table}.is_template desc, ${table}.disabled asc, ${args.order_by}`;
			return args;
		};
	},

	get_indicator(doc) {
		if (doc.is_template) {
			return doc.disabled
				? [__("Template (disabled)"), "gray", "is_template,=,1|disabled,=,1"]
				: [__("Template"), "purple", "is_template,=,1|disabled,=,0"];
		}
		if (doc.docstatus === 1) return [__("Submitted"), "blue", "docstatus,=,1"];
		if (doc.docstatus === 2) return [__("Cancelled"), "red", "docstatus,=,2"];
		return [__("Draft"), "orange", "docstatus,=,0"];
	},
};
