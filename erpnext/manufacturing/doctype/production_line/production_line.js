frappe.ui.form.on("Production Line", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(
			__("Production Flow"),
			() => {
				frappe.set_route("production-flow", { production_line: frm.doc.name });
			},
			__("View")
		);
	},
	setup(frm) {
		frm.set_query("workplace", "workplaces", function (doc) {
			const picked = (doc.workplaces || []).map((row) => row.workplace).filter(Boolean);
			return { filters: { is_active: 1, name: ["not in", picked] } };
		});

		frm.set_query("workplace", "plan", function (doc) {
			const allowed = (doc.workplaces || [])
				.filter((row) => row.enabled && row.workplace)
				.map((row) => row.workplace);
			if (!allowed.length) return { filters: { is_active: 1 } };
			return { filters: { name: ["in", allowed] } };
		});
	},
});
