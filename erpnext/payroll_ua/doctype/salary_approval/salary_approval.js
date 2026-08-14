frappe.ui.form.on("Salary Approval", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		frm.page.set_indicator(
			__(frm.doc.status),
			{ Draft: "orange", Approved: "green", Cancelled: "gray" }[frm.doc.status] || "gray"
		);

		if (frm.doc.status === "Draft") {
			frm.add_custom_button(__("Load Employees"), () =>
				frm
					.call({ doc: frm.doc, method: "load_employees", freeze: true })
					.then(() => frm.reload_doc())
			);

			frm.add_custom_button(__("Approve"), () => confirm_approval(frm)).addClass("btn-primary");
		}
	},
});

frappe.ui.form.on("Salary Approval Item", {
	official_salary: (frm) => frm.trigger("validate"),
	cash_salary: (frm) => frm.trigger("validate"),
	bonus_percent: (frm) => frm.trigger("validate"),
	allowance: (frm) => frm.trigger("validate"),
});

function confirm_approval(frm) {
	frappe.confirm(
		__(
			"The salary of {0} employees will be written to their cards and the bonuses will be created. Continue?",
			[frm.doc.total_employees]
		),
		() =>
			frm
				.call({ doc: frm.doc, method: "approve", freeze: true, freeze_message: __("Working...") })
				.then((response) => {
					const applied = response.message || {};
					frappe.show_alert({
						message: __("Salary updated for {0}, bonuses created: {1}, allowances: {2}", [
							applied.salary || 0,
							applied.bonus || 0,
							applied.allowance || 0,
						]),
						indicator: "green",
					});
					frm.reload_doc();
				})
	);
}
