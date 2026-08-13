frappe.listview_settings["Specification"] = {
	add_fields: ["has_variants", "disabled"],
	get_indicator: function (doc) {
		if (doc.disabled) {
			return [__("Disabled"), "grey", "disabled,=,1"];
		}
		if (doc.has_variants) {
			return [__("Template"), "blue", "has_variants,=,1"];
		}
		return [__("Active"), "green", "has_variants,=,0"];
	},
};
