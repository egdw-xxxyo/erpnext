// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

const REVISION_STATUS_COLORS = {
	Чернетка: "red",
	Затверджена: "blue",
	Чинна: "green",
	Замінена: "gray",
	Скасована: "red",
};

frappe.listview_settings["Technical Document Revision"] = {
	add_fields: ["revision_status"],
	has_indicator_for_draft: true,
	has_indicator_for_cancelled: true,
	get_indicator(doc) {
		const status = doc.revision_status;
		return [__(status), REVISION_STATUS_COLORS[status] || "gray", `revision_status,=,${status}`];
	},
};
