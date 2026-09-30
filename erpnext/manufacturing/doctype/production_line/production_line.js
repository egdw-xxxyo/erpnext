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
		frm.add_custom_button(
			__("Production Line Overview"),
			() => {
				frappe.set_route("production-line-overview", { production_line: frm.doc.name });
			},
			__("View")
		);
		frm.add_custom_button(__("Close Day"), () => {
			frappe.confirm(
				__(
					"Units nobody started lose their Job Cards and Serial Nos, and each Work Order of the line shrinks to the units that were started. Continue?"
				),
				() =>
					frappe.call({
						method: "erpnext.manufacturing.doctype.production_line.production_line.close_day",
						args: { line: frm.doc.name },
						freeze: true,
						callback: (r) => {
							frappe.msgprint({
								title: __("Close Day"),
								message: frappe.utils.escape_html(r.message || "").replace(/\n/g, "<br>"),
							});
							frm.reload_doc();
						},
					})
			);
		});
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
