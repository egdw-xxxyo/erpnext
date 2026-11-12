frappe.ui.form.on("Sensitive Data Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Sensitive Access Log"), () =>
			frappe.set_route("List", "Sensitive Access Log")
		);
		frm.add_custom_button(__("PIN States"), () => frappe.set_route("List", "Sensitive Data PIN"));
		erpnext.sensitive_data.protection.setup_grids(frm);
	},
});

frappe.ui.form.on("Sensitive Data Field", {
	document_type(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "fieldname", "");
		erpnext.sensitive_data.field_options(frm, cdt, cdn);
	},
	form_render(frm, cdt, cdn) {
		erpnext.sensitive_data.field_options(frm, cdt, cdn);
	},
});

frappe.provide("erpnext.sensitive_data");

erpnext.sensitive_data.field_options = (frm, cdt, cdn) => {
	const row = locals[cdt][cdn];
	if (!row.document_type) return;
	frappe.model.with_doctype(row.document_type, () => {
		const options = frappe
			.get_meta(row.document_type)
			.fields.filter((df) => !frappe.model.no_value_type.includes(df.fieldtype))
			.map((df) => ({
				value: df.fieldname,
				label: `${__(df.label || df.fieldname)} (${df.fieldname})`,
			}));
		frm.fields_dict.fields.grid.update_docfield_property("fieldname", "options", options);
	});
};

erpnext.sensitive_data.protection = (() => {
	const esc = frappe.utils.escape_html;
	const LIMIT = 100;
	const KINDS = {
		DocType: {
			label: __("Whole document"),
			hint: __("Its list, form, print and export ask for the PIN"),
		},
		Field: {
			label: __("Document fields"),
			hint: __("The document stays open, only the chosen fields stay hidden until the PIN is entered"),
		},
		Report: { label: __("Report"), hint: __("Opening and running the report asks for the PIN") },
		Page: {
			label: __("Page"),
			hint: __("Opening the page and the server methods of its own module ask for the PIN"),
		},
	};
	const candidates = {};

	const load = (object_type) =>
		(candidates[object_type] ||= frappe.xcall(
			"erpnext.access_control.doctype.sensitive_data_settings.sensitive_data_settings.protection_candidates",
			{ object_type }
		));

	const field_candidates = (doctype) =>
		new Promise((resolve) =>
			frappe.model.with_doctype(doctype, () =>
				resolve(
					frappe
						.get_meta(doctype)
						.fields.filter((df) => !frappe.model.no_value_type.includes(df.fieldtype))
						.map((df) => ({
							name: df.fieldname,
							title: df.label || df.fieldname,
							module: df.fieldtype,
							label: df.label,
						}))
				)
			)
		);

	const protected_keys = (frm, kind, doctype) =>
		new Set(
			kind === "Field"
				? (frm.doc.fields || [])
						.filter((row) => row.document_type === doctype)
						.map((row) => row.fieldname)
				: (frm.doc.objects || [])
						.filter((row) => row.object_type === kind)
						.map((row) => row.object_name)
		);

	const matches = (item, words) => {
		const haystack = `${__(item.title)} ${item.title} ${item.name} ${__(
			item.module || ""
		)}`.toLowerCase();
		return words.every((word) => haystack.includes(word));
	};

	const item_html = (item, taken, selected) => {
		const title = __(item.title);
		const sub = [__(item.module || ""), item.name !== title ? item.name : ""].filter(Boolean).join(" · ");
		const done = taken.has(item.name);
		return `<label class="sdp-item${done ? " sdp-done" : ""}" data-name="${esc(item.name)}">
			<input type="checkbox" ${done || selected.has(item.name) ? "checked" : ""} ${done ? "disabled" : ""}>
			<span class="sdp-text">
				<span class="sdp-title ellipsis">${esc(title)}</span>
				<span class="sdp-sub text-muted ellipsis">${esc(sub)}</span>
			</span>
			${done ? `<span class="indicator-pill gray">${__("Already protected")}</span>` : ""}
		</label>`;
	};

	const styles = () => {
		if (document.getElementById("sdp-styles")) return;
		$(`<style id="sdp-styles">
			.sdp-hint{margin-bottom:var(--margin-md);}
			.sdp-list{max-height:45vh;overflow-y:auto;border:1px solid var(--border-color);border-radius:var(--border-radius-md);}
			.sdp-item{display:flex;align-items:center;gap:10px;margin:0;padding:6px 12px;cursor:pointer;
				border-bottom:1px solid var(--border-color);font-weight:400;}
			.sdp-item:last-child{border-bottom:none;}
			.sdp-item:hover{background:var(--fg-hover-color);}
			.sdp-item input{margin:0;flex:none;}
			.sdp-done{cursor:default;opacity:.65;}
			.sdp-text{display:flex;flex-direction:column;min-width:0;flex:1;line-height:1.3;}
			.sdp-sub{font-size:var(--text-sm);}
			.sdp-empty,.sdp-more{padding:10px 12px;}
			.sdp-count{margin-top:6px;}
		</style>`).appendTo(document.head);
	};

	const open = (frm, kind = "DocType") => {
		styles();
		const state = { kind, items: [], selected: new Map(), seq: 0 };

		const dialog = new frappe.ui.Dialog({
			title: __("Add Protection"),
			size: "large",
			fields: [
				{
					fieldname: "kind",
					fieldtype: "Select",
					label: __("What to protect"),
					options: Object.entries(KINDS).map(([value, k]) => ({ value, label: k.label })),
					default: kind,
					onchange: () => switch_kind(dialog.get_value("kind")),
				},
				{ fieldname: "hint", fieldtype: "HTML" },
				{
					fieldname: "document_type",
					fieldtype: "Link",
					options: "DocType",
					label: __("Document Type"),
					depends_on: "eval:doc.kind == 'Field'",
					get_query: () => ({ filters: { istable: 0 } }),
					onchange: () => load_items(),
				},
				{
					fieldname: "search",
					fieldtype: "Data",
					label: __("Search"),
					placeholder: __("Name or module"),
				},
				{ fieldname: "results", fieldtype: "HTML" },
				{
					fieldname: "unlock_minutes",
					fieldtype: "Int",
					label: __("Unlock Duration (min)"),
					description: __("Empty: the general value from the settings"),
					depends_on: "eval:doc.kind != 'Field'",
				},
			],
			primary_action_label: __("Add"),
			primary_action: () => add(),
		});

		const $results = dialog.fields_dict.results.$wrapper;
		const document_type = () => dialog.get_value("document_type");

		const render = () => {
			const taken = protected_keys(frm, state.kind, document_type());
			const words = (dialog.get_value("search") || "").toLowerCase().split(/\s+/).filter(Boolean);
			const found = state.items.filter((item) => matches(item, words));
			const shown = found.slice(0, LIMIT);
			const whole =
				state.kind === "Field" && protected_keys(frm, "DocType").has(document_type())
					? `<div class="alert alert-warning">${__(
							"This document is already protected as a whole, its fields are hidden anyway"
					  )}</div>`
					: "";
			const body = shown.length
				? shown.map((item) => item_html(item, taken, state.selected)).join("")
				: `<div class="sdp-empty text-muted">${
						state.kind === "Field" && !document_type()
							? __("Choose a document type first")
							: __("Nothing found")
				  }</div>`;
			const more =
				found.length > shown.length
					? `<div class="sdp-more text-muted">${__(
							"Showing {0} of {1}. Refine the search to see the rest",
							[shown.length, found.length]
					  )}</div>`
					: "";
			$results.html(
				`${whole}<div class="sdp-list">${body}${more}</div>
				<div class="sdp-count text-muted">${__("Selected: {0}", [state.selected.size])}</div>`
			);
		};

		const load_items = () => {
			const seq = ++state.seq;
			state.selected.clear();
			state.items = [];
			$results.html(`<div class="sdp-empty text-muted">${__("Loading...")}</div>`);
			const source =
				state.kind === "Field"
					? document_type()
						? field_candidates(document_type())
						: Promise.resolve([])
					: load(state.kind);
			source.then((items) => {
				if (seq !== state.seq) return;
				state.items = items;
				render();
			});
		};

		const switch_kind = (value) => {
			state.kind = value;
			dialog.fields_dict.hint.$wrapper.html(
				`<div class="sdp-hint text-muted">${esc(KINDS[value].hint)}</div>`
			);
			dialog.set_value("search", "");
			load_items();
		};

		const add = () => {
			if (!state.selected.size) {
				frappe.msgprint(__("Select at least one item"));
				return;
			}
			const minutes = dialog.get_value("unlock_minutes") || 0;
			state.selected.forEach((item) =>
				state.kind === "Field"
					? frm.add_child("fields", {
							document_type: document_type(),
							fieldname: item.name,
							label: item.label,
					  })
					: frm.add_child("objects", {
							object_type: state.kind,
							object_name: item.name,
							unlock_minutes: minutes,
					  })
			);
			if (state.kind === "Page") remember_titles(state.items);
			frm.refresh_field(state.kind === "Field" ? "fields" : "objects");
			frm.dirty();
			frappe.show_alert({
				message: __("Added: {0}. Save the settings to apply", [state.selected.size]),
				indicator: "green",
			});
			dialog.hide();
		};

		$results.on("change", "input[type=checkbox]", (event) => {
			const name = $(event.target).closest(".sdp-item").attr("data-name");
			const item = state.items.find((i) => i.name === name);
			if (event.target.checked) state.selected.set(name, item);
			else state.selected.delete(name);
			$results.find(".sdp-count").text(__("Selected: {0}", [state.selected.size]));
		});
		dialog.fields_dict.search.$input.on("input", frappe.utils.debounce(render, 150));

		dialog.show();
		switch_kind(kind);
	};

	const remember_titles = (pages) =>
		pages.forEach((page) => frappe.utils.add_link_title("Page", page.name, page.title));

	const KIND_LABELS = { DocType: __("Document Type"), Report: __("Report"), Page: __("Page") };

	const setup_grids = (frm) => {
		const objects = frm.fields_dict.objects.grid;
		const fields = frm.fields_dict.fields.grid;
		[objects, fields].forEach((grid) => (grid.cannot_add_rows = true));
		objects.update_docfield_property("object_type", "formatter", (value) =>
			esc(KIND_LABELS[value] || __(value || ""))
		);
		fields.update_docfield_property(
			"label",
			"formatter",
			(value, df, options, doc) =>
				`${esc(__(value || doc?.fieldname || ""))}${
					doc?.fieldname ? ` <span class="text-muted">· ${esc(doc.fieldname)}</span>` : ""
				}`
		);
		objects.add_custom_button(__("Add Protection"), () => open(frm, "DocType"));
		fields.add_custom_button(__("Add Protection"), () => open(frm, "Field"));
		frm.refresh_field("objects");
		frm.refresh_field("fields");
		if ((frm.doc.objects || []).some((row) => row.object_type === "Page")) {
			load("Page").then((pages) => {
				remember_titles(pages);
				frm.refresh_field("objects");
			});
		}
	};

	return { open, setup_grids };
})();
