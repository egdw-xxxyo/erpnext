frappe.listview_settings["Repair Unit"] = {
	add_fields: ["status", "outcome", "issue", "priority", "company", "warehouse", "repair_user"],
	has_indicator_for_draft: true,
	get_indicator(doc) {
		const colors = {
			"Awaiting Receipt": "gray",
			Received: "blue",
			"In Repair": "orange",
			"Waiting for Parts": "yellow",
			"Waiting for Customer": "yellow",
			"Ready for Dispatch": "green",
			Dispatched: "blue",
			Delivered: "green",
			Disposed: "red",
		};
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
	formatters: {
		priority(value) {
			if (!value) return "—";
			const text = String(value).toLowerCase();
			const color = /urgent|critical|термін|критич/.test(text)
				? "red"
				: /high|висок/.test(text)
				? "orange"
				: /low|низьк/.test(text)
				? "gray"
				: "blue";
			return `<span class="indicator-pill ${color}">${frappe.utils.escape_html(__(value))}</span>`;
		},
	},
};
