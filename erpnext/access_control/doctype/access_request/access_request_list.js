frappe.listview_settings["Access Request"] = {
	get_indicator(doc) {
		const colors = {
			Pending: "orange",
			Approved: "green",
			Rejected: "red",
			Cancelled: "gray",
			Revoked: "purple",
			Expired: "gray",
		};
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
