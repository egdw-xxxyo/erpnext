frappe.listview_settings["Vehicle Trip"] = {
	has_indicator_for_draft: true,
	has_indicator_for_cancelled: true,
	get_indicator: function (doc) {
		if (doc.docstatus === 2) {
			return [__("Cancelled"), "red", "docstatus,=,2"];
		}
		if (doc.status === "Completed") {
			return [__("Completed"), "green", "status,=,Completed"];
		}
		if (doc.status === "En Route") {
			return [__("En Route"), "blue", "status,=,En Route"];
		}
		return [__("Draft"), "red", "docstatus,=,0"];
	},
};
