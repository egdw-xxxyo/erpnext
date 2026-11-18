frappe.listview_settings["Enforcement Order"] = {
	add_fields: ["status", "to_transfer"],
	get_indicator(doc) {
		if (doc.status === "Active" && flt(doc.to_transfer)) {
			return [__("To Transfer"), "orange", "to_transfer,>,0"];
		}

		const colors = { Active: "green", Suspended: "orange", Closed: "gray" };
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
