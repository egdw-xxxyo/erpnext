(() => {
	const api = "erpnext.setup.helper_guides.";

	function download(guide, suffix) {
		const name = guide.target_doctype.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
		const url = URL.createObjectURL(new Blob([JSON.stringify(guide, null, 2) + "\n"], { type: "application/json" }));
		const link = document.createElement("a");
		link.href = url;
		link.download = [name || "helper-guide", suffix].filter(Boolean).join("-") + ".json";
		link.click();
		setTimeout(() => URL.revokeObjectURL(url), 1000);
	}

	function choose(label, field, target, callback, filters) {
		frappe.prompt(
			[{ label, fieldname: field, fieldtype: "Link", options: target, reqd: 1, get_query: () => ({ filters }) }],
			(values) => callback(values[field]),
			label,
			__("Download")
		);
	}

	function choose_file(listview) {
		const input = document.createElement("input");
		input.type = "file";
		input.accept = ".json,application/json";
		input.addEventListener("change", async () => {
			const file = input.files[0];
			if (!file) return;
			if (file.size > 512_000) {
				frappe.msgprint(__("Choose a JSON file smaller than 512 KB."));
				return;
			}
			let source;
			try {
				source = await file.text();
			} catch {
				frappe.msgprint(__("Could not read the JSON file."));
				return;
			}
			const name = await frappe.xcall(api + "import_guide", { source }).catch(() => null);
			if (name) {
				listview.refresh();
				frappe.set_route("Form", "Helper Guide", name);
			}
		}, { once: true });
		input.click();
	}

	frappe.listview_settings["Helper Guide"] = {
		onload(listview) {
			const page = listview.page;
			page.add_inner_button(__("Helper Settings"), () => frappe.set_route("Form", "Helper Settings"));
			page.add_menu_item(__("Download JSON Template"), () => {
				choose(__("Target DocType"), "target_doctype", "DocType", (target_doctype) =>
					frappe.xcall(api + "template", { target_doctype }, "GET").then((guide) => download(guide, "template")),
					{ istable: 0 }
				);
			});
			page.add_menu_item(__("Import Guide JSON"), () => choose_file(listview));
			page.add_menu_item(__("Export Guide JSON"), () => {
				const export_guide = (name) =>
					frappe.xcall(api + "export_guide", { name }, "GET").then((guide) => download(guide));
				const selected = listview.get_checked_items();
				if (selected.length === 1) export_guide(selected[0].name);
				else choose(__("Helper Guide"), "guide", "Helper Guide", export_guide, {});
			});
		},
	};
})();
