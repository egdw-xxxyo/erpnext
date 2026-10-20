frappe.listview_settings["Recurring Purchase"] = {
	add_fields: ["valid_from", "valid_until", "workflow_state"],
	has_indicator_for_draft: true,
	get_indicator(doc) {
		const state = doc.workflow_state || "Чернетка";
		const colors = {
			Чернетка: "blue",
			"Потребує доопрацювання": "orange",
			"Перевірка підрозділу": "yellow",
			"Фінальне погодження": "yellow",
			Погоджено: "green",
			Проведено: "green",
			Відхилено: "red",
		};
		return [__(state), colors[state] || "gray", `workflow_state,=,${state}`];
	},
	onload(listview) {
		listview.settings.before_render = () => {
			const column = listview.columns.find((column) => column.df?.fieldname === "valid_until");
			if (column && column.df.label !== __("Validity Status")) {
				column.df = { ...column.df, label: __("Validity Status") };
				listview.render_header(true);
			}
		};
	},
	formatters: {
		valid_until(value, df, doc) {
			const today = frappe.datetime.get_today();
			const [label, color] =
				!doc.valid_from || !value
					? [__("Not specified"), "gray"]
					: today < doc.valid_from
					? [__("Not yet effective"), "blue"]
					: today > value
					? [__("Validity expired"), "gray"]
					: [__("Effective"), "green"];
			const dates = `${frappe.datetime.str_to_user(
				doc.valid_from || ""
			)} — ${frappe.datetime.str_to_user(value || "")}`;
			return `<span class="indicator-pill no-indicator-dot ${color}" title="${frappe.utils.escape_html(
				dates
			)}">${label}</span>`;
		},
	},
};
