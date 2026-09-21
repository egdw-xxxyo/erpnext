frappe.ui.form.on("Employee", {
	refresh(frm) {
		render_overview_photo(frm);
		render_subordinates(frm);
		show_document_file_names(frm);
		show_kp_job_title(frm);
	},

	image(frm) {
		render_overview_photo(frm);
	},

	setup(frm) {
		frm.set_query("kp_code", () => "erpnext.hr.kp_classifier.search_kp_professions");
	},

	onload_post_render(frm) {
		frm.set_df_property("kp_code", "ignore_validation", 1);
		const awesomplete = frm.fields_dict.kp_code?.awesomplete;
		if (awesomplete) awesomplete.filter = () => true;
	},

	async kp_code(frm) {
		const [kp_code, ...title] = (frm.doc.kp_code || "").split(" ");
		if (title.length) {
			await frm.set_value({ kp_code, kp_job_title: title.join(" ") });
		} else if (!kp_code) {
			await frm.set_value("kp_job_title", "");
		}
		show_kp_job_title(frm);
	},
});

function show_kp_job_title(frm) {
	frm.set_df_property("kp_code", "description", frm.doc.kp_code ? frm.doc.kp_job_title || "" : "");
}

function file_name_from_url(url) {
	const name = url.split("?")[0].split("/").pop();
	try {
		return decodeURIComponent(name);
	} catch {
		return name;
	}
}

function document_file_link(value) {
	if (!value) return "";
	const href = frappe.utils.escape_html(value);
	const name = frappe.utils.escape_html(file_name_from_url(value));
	return `<a href="${href}" target="_blank">${name}</a>`;
}

function show_document_file_names(frm) {
	const grid = frm.fields_dict.employee_documents?.grid;
	if (!grid) return;

	grid.update_docfield_property("file", "formatter", document_file_link);
	grid.refresh();
}

function can_upload_photo(frm) {
	return !frm.is_new() && frm.perm[0]?.write && !frm.get_docfield("image").read_only;
}

function overview_photo_content(frm) {
	if (frm.doc.image) {
		return `<img src="${encodeURI(frm.doc.image)}" alt="${frappe.utils.escape_html(
			frm.doc.employee_name || ""
		)}">`;
	}

	const hint = frm.is_new() ? __("Save the employee to add a photo") : __("Add Photo");
	return `<div class="employee-overview-photo-empty">
		<i class="fa fa-user"></i>
		<span>${hint}</span>
	</div>`;
}

function open_photo_uploader(frm) {
	const field = frm.get_field("image");
	if (!field.$input) {
		field.make_input();
	}
	field.$input.trigger("attach_doc_image");
}

function render_overview_photo(frm) {
	const wrapper = frm.fields_dict.overview_photo?.$wrapper;
	if (!wrapper) return;

	const clickable = can_upload_photo(frm);
	const $photo = $(`<div class="employee-overview-photo ${clickable ? "clickable" : ""}">
		${overview_photo_content(frm)}
	</div>`);

	if (clickable) {
		$photo.attr("title", frm.doc.image ? __("Change Photo") : __("Add Photo"));
		$photo.on("click", () => open_photo_uploader(frm));
	}

	wrapper.empty().append(overview_photo_style(), $photo);
}

function fetch_subordinates(employee) {
	return frappe.db.get_list("Employee", {
		filters: { reports_to: employee, status: "Active" },
		fields: ["name", "employee_name", "designation"],
		order_by: "employee_name asc",
		limit: 0,
	});
}

function subordinate_row(subordinate, index) {
	const name = frappe.utils.escape_html(subordinate.employee_name || subordinate.name);
	const designation = frappe.utils.escape_html(subordinate.designation || "");
	return `<tr>
		<td class="text-muted">${index + 1}</td>
		<td>${frappe.utils.get_form_link("Employee", subordinate.name, true, name)}</td>
		<td>${designation}</td>
	</tr>`;
}

function subordinates_table(subordinates) {
	return `<div class="employee-subordinates">
		<table class="table table-bordered">
			<thead>
				<tr>
					<th>${__("No.")}</th>
					<th>${__("Employee")}</th>
					<th>${__("Designation")}</th>
				</tr>
			</thead>
			<tbody>${subordinates.map(subordinate_row).join("")}</tbody>
		</table>
	</div>`;
}

async function render_subordinates(frm) {
	const wrapper = frm.fields_dict.subordinates_html?.$wrapper;
	if (!wrapper) return;

	wrapper.empty();
	frm.toggle_display("subordinates_section", false);
	if (frm.is_new()) return;

	const employee = frm.doc.name;
	const subordinates = await fetch_subordinates(employee);
	if (frm.doc.name !== employee || !subordinates.length) return;

	wrapper.append(subordinates_style(), subordinates_table(subordinates));
	render_attendance_sheet_toggle(frm);
	frm.toggle_display("subordinates_section", true);
}

function attendance_sheet_toggle(frm) {
	const df = frm.get_docfield("does_not_fill_attendance_sheet");
	const hint = frappe.utils.escape_html(__(df.description));
	const $toggle = $(`<label class="employee-subordinates-toggle">
		<input type="checkbox">
		<span>${__(df.label)}</span>
		<i class="fa fa-info-circle text-muted" title="${hint}" data-toggle="tooltip"></i>
	</label>`);

	$toggle
		.find("input")
		.prop("checked", !!frm.doc.does_not_fill_attendance_sheet)
		.prop("disabled", !frm.perm[0]?.write)
		.on("change", (event) =>
			frm.set_value("does_not_fill_attendance_sheet", event.target.checked ? 1 : 0)
		);
	$toggle.on("click", (event) => event.stopPropagation());
	$toggle.find("[data-toggle=tooltip]").tooltip({ placement: "top", container: "body" });

	return $toggle;
}

function render_attendance_sheet_toggle(frm) {
	const head = frm.fields_dict.subordinates_section?.head;
	if (!head || !frm.get_docfield("does_not_fill_attendance_sheet")) return;

	head.addClass("employee-subordinates-head").find(".employee-subordinates-toggle").remove();
	head.append(attendance_sheet_toggle(frm));
}

function subordinates_style() {
	return `<style>
		.employee-subordinates {
			border-radius: var(--border-radius-md);
			overflow: hidden;
			border: 1px solid var(--table-border-color);
			margin-bottom: var(--padding-md);
		}
		.employee-subordinates .table {
			margin: 0;
			border: none;
		}
		.employee-subordinates th {
			background: var(--subtle-fg);
			color: var(--text-muted);
			font-weight: var(--weight-regular);
		}
		.employee-subordinates th:first-child,
		.employee-subordinates td:first-child {
			width: 48px;
			text-align: center;
		}
		.employee-subordinates th:not(:first-child),
		.employee-subordinates td:not(:first-child) {
			width: 50%;
		}
		.employee-subordinates td a {
			text-decoration: underline;
		}
		.employee-subordinates-head {
			display: flex;
			align-items: center;
			gap: var(--margin-md);
		}
		.employee-subordinates-toggle {
			display: inline-flex;
			align-items: center;
			gap: var(--margin-xs);
			margin: 0;
			font-size: var(--text-md);
			font-weight: var(--weight-regular);
			color: var(--text-color);
			cursor: pointer;
		}
		.employee-subordinates-toggle input {
			margin: 0;
		}
		.employee-subordinates-toggle .fa {
			cursor: help;
		}
	</style>`;
}

function overview_photo_style() {
	return `<style>
		.employee-overview-photo {
			width: 100%;
			aspect-ratio: 7 / 8;
			border-radius: var(--border-radius-lg);
			background: var(--control-bg);
			overflow: hidden;
			margin-bottom: var(--margin-md);
		}
		.employee-overview-photo.clickable {
			cursor: pointer;
		}
		.employee-overview-photo img {
			width: 100%;
			height: 100%;
			object-fit: cover;
		}
		.employee-overview-photo-empty {
			height: 100%;
			display: flex;
			flex-direction: column;
			align-items: center;
			justify-content: center;
			gap: var(--margin-sm);
			color: var(--text-muted);
			text-align: center;
			padding: var(--padding-md);
		}
		.employee-overview-photo-empty .fa {
			font-size: 64px;
		}
	</style>`;
}
