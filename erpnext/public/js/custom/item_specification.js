// The ЄСКД designation an Item is made to. Which one fits is a human judgement — the picker
// only floats the plausible ones (★) and the button explains why each one matched.
frappe.ui.form.on("Item", {
	setup(frm) {
		frm.set_query("specification", () => ({
			query: "erpnext.technical_documentation.item_match.modification_link_query",
			filters: { item: frm.doc.name },
		}));
	},

	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Suggest Specification"), () => suggest(frm));
	},
});

function suggest(frm) {
	frappe.call({
		method: "erpnext.technical_documentation.item_match.suggest_modifications",
		args: { item: frm.doc.name },
		freeze: true,
		callback: ({ message }) => {
			const rows = message || [];
			if (!rows.length) {
				frappe.msgprint({
					title: __("No Match"),
					message: __("No designation shares words with this item's attributes."),
					indicator: "orange",
				});
				return;
			}
			show_matches(frm, rows);
		},
	});
}

function show_matches(frm, rows) {
	const html = rows
		.map(
			(row) => `<tr>
				<td><button class="btn btn-xs btn-default" data-pick="${frappe.utils.escape_html(row.name)}">${__(
				"Pick"
			)}</button></td>
				<td>${frappe.utils.escape_html(row.code)}</td>
				<td>${frappe.utils.escape_html(row.full_name || "")}</td>
				<td class="text-muted">${frappe.utils.escape_html((row.matched || []).join(", "))}</td>
			</tr>`
		)
		.join("");

	const dialog = new frappe.ui.Dialog({
		title: __("Suggested Specifications"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "matches",
				options: `<table class="table table-bordered"><thead><tr><th></th><th>${__(
					"Code"
				)}</th><th>${__("Full Name")}</th><th>${__(
					"Matched On"
				)}</th></tr></thead><tbody>${html}</tbody></table>`,
			},
		],
	});
	dialog.show();
	dialog.$wrapper.find("[data-pick]").on("click", function () {
		frm.set_value("specification", $(this).attr("data-pick"));
		dialog.hide();
	});
}
