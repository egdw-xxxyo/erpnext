frappe.listview_settings["Package"] = {
	get_indicator: function (doc) {
		if (doc.status === "Draft") return [__("Draft"), "red", "status,=,Draft"];
		if (doc.status === "Packed") return [__("Packed"), "blue", "status,=,Packed"];
		if (doc.status === "Shipped") return [__("Shipped"), "green", "status,=,Shipped"];
		if (doc.status === "Cancelled") return [__("Cancelled"), "grey", "status,=,Cancelled"];
	},
};
