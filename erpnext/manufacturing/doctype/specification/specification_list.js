frappe.listview_settings["Specification"] = {
	add_fields: ["disabled"],
	get_indicator: function (doc) {
		if (doc.disabled) {
			return [__("Disabled"), "grey", "disabled,=,1"];
		}
		return [__("Active"), "green", "disabled,=,0"];
	},
};
