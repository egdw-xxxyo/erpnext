(() => {
	const esc = frappe.utils.escape_html;
	const SHOWN = 3;
	const COLORS = { "In Effect": "green", Narrows: "orange", "No Effect": "gray", "User Disabled": "red" };

	const lines = (value) => (value || "").split("\n").filter(Boolean);

	const more = (rest) =>
		rest.length
			? `<span class="text-muted small" title="${esc(rest.join(", "))}">+${rest.length}</span>`
			: "";

	const company_pill = (company, scope) =>
		`<span class="mr-2"><span class="indicator-pill blue">${esc(company)}</span>${
			scope ? `<span class="text-muted small ml-1">${esc(scope)}</span>` : ""
		}</span>`;

	const extra = (value) => {
		const grants = lines(value).map((line) => line.split(" · "));
		return (
			grants
				.slice(0, SHOWN)
				.map(([company, scope]) => company_pill(company, scope))
				.join("") + more(grants.slice(SHOWN).map(([company, scope]) => `${company} · ${scope}`))
		);
	};

	const main = (value) => {
		const companies = lines(value);
		if (!companies.length) return `<span class="text-muted">—</span>`;
		return (
			companies
				.slice(0, SHOWN)
				.map((company) => `<span class="indicator-pill gray mr-1">${esc(company)}</span>`)
				.join("") + more(companies.slice(SHOWN))
		);
	};

	const user = (value) =>
		value
			? erpnext.entity.html(
					{
						name: value,
						key: value,
						image: frappe.user_info(value)?.image,
						route: ["Form", "User", value],
					},
					{ size: 20 }
			  )
			: "";

	frappe.listview_settings["User Company Access"] = {
		add_fields: ["access_status", "main_companies", "extra_companies"],
		hide_name_column: true,
		hide_name_filter: true,
		custom_filter_configs: [
			{
				fieldtype: "Link",
				fieldname: "company",
				options: "Company",
				label: __("Extra Company"),
				doctype: "User Company Access Grant",
			},
			{
				fieldtype: "Link",
				fieldname: "scope",
				options: "Company Access Scope",
				label: __("Company Access Scope"),
				doctype: "User Company Access Grant",
			},
		],
		get_indicator: (doc) =>
			doc.access_status
				? [__(doc.access_status), COLORS[doc.access_status], `access_status,=,${doc.access_status}`]
				: null,
		formatters: { user, main_companies: main, extra_companies: extra },
		onload: (listview) => erpnext.entity.bind_list_links(listview),
		refresh: (listview) =>
			erpnext.entity
				.load_users(listview.data.map((doc) => doc.user))
				.then((loaded) => loaded && listview.render()),
	};
})();
