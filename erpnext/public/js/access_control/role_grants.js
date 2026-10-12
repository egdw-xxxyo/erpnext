frappe.provide("erpnext.access_control");

erpnext.access_control.RIGHT_LABELS = {
	select: __("Select"),
	read: __("Read"),
	write: __("Write"),
	create: __("Create"),
	delete: __("Delete"),
	submit: __("Submit"),
	cancel: __("Cancel"),
	amend: __("Amend"),
	print: __("Print"),
	email: __("Email"),
	report: __("Report"),
	import: __("Import"),
	export: __("Export"),
	share: __("Share"),
};

erpnext.access_control.RISKY_RIGHTS = ["delete", "cancel", "export", "import", "share"];

erpnext.access_control.right_badge = (right, scope) => {
	const label = erpnext.access_control.RIGHT_LABELS[right] || __(right);
	const risky = erpnext.access_control.RISKY_RIGHTS.includes(right);
	const color = risky ? "red" : scope === "owner" ? "orange" : "blue";
	const suffix = scope === "owner" ? ` · ${__("own only")}` : "";
	return `<span class="indicator-pill ${color} ac-right">${frappe.utils.escape_html(
		label
	)}${suffix}</span>`;
};

erpnext.access_control.level_html = (entry) =>
	entry.access
		.map((level) => {
			const badges = Object.entries(level.rights)
				.map(([right, scope]) => erpnext.access_control.right_badge(right, scope))
				.join(" ");
			if (!level.permlevel) return `<div>${badges}</div>`;
			const fields = (entry.fields_by_level[level.permlevel] || []).slice(0, 8).join(", ");
			return `<div class="ac-level">
				<span class="text-muted">${__("Field level {0}", [level.permlevel])}${
				fields ? `: ${frappe.utils.escape_html(fields)}` : ""
			}</span>
				<div>${badges}</div>
			</div>`;
		})
		.join("");

erpnext.access_control.doctype_row = (entry) => {
	const flags = [
		entry.sensitive ? `<span class="indicator-pill red">${__("Sensitive")}</span>` : "",
		entry.source === "custom"
			? `<span class="indicator-pill gray" title="${__(
					"Permissions of this document type are customized (Custom DocPerm)"
			  )}">${__("Custom permissions")}</span>`
			: "",
		entry.is_table ? `<span class="indicator-pill gray">${__("Child table")}</span>` : "",
	].join(" ");
	return `<tr>
		<td class="ac-doctype">
			<a href="/app/${frappe.router.slug(entry.doctype)}" target="_blank">${frappe.utils.escape_html(
		entry.label
	)}</a>
			<div>${flags}</div>
		</td>
		<td>${erpnext.access_control.level_html(entry)}</td>
	</tr>`;
};

erpnext.access_control.doctypes_html = (doctypes) => {
	if (!doctypes.length) return `<p class="text-muted">${__("No document access")}</p>`;
	const modules = [...new Set(doctypes.map((entry) => entry.module || __("Other")))].sort();
	return modules
		.map((module) => {
			const entries = doctypes.filter((entry) => (entry.module || __("Other")) === module);
			const alert = entries.some((entry) => entry.sensitive);
			return `<details class="ac-module" ${alert ? "open" : ""}>
				<summary><b>${frappe.utils.escape_html(__(module))}</b>
					<span class="text-muted">(${entries.length})</span>
					${alert ? `<span class="indicator-pill red">${__("Needs attention")}</span>` : ""}
				</summary>
				<table class="table table-bordered table-sm ac-table">
					<tbody>${entries.map(erpnext.access_control.doctype_row).join("")}</tbody>
				</table>
			</details>`;
		})
		.join("");
};

erpnext.access_control.list_html = (title, items, render) =>
	items.length
		? `<details class="ac-section" ${items.length <= 8 ? "open" : ""}>
			<summary class="ac-heading"><b>${title}</b> <span class="text-muted">(${items.length})</span></summary>
			<ul class="ac-list">${items.map((item) => `<li>${render(item)}</li>`).join("")}</ul>
		</details>`
		: "";

erpnext.access_control.render_grants = (data) => {
	const esc = frappe.utils.escape_html;
	const inert = (data.inert_doctypes || []).length
		? `<div class="alert alert-warning">
			${
				data.role === undefined
					? __(
							"These roles are listed in the standard permissions of these document types, but their permissions are customized without them, so they give nothing there:"
					  )
					: __(
							"The role is listed in the standard permissions of these document types, but their permissions are customized without it, so it gives nothing there:"
					  )
			}
			<b>${data.inert_doctypes.map((doctype) => esc(__(doctype))).join(", ")}</b>
		</div>`
		: "";
	const holders =
		data.users === undefined
			? ""
			: `<p class="text-muted">${__("Users with this role: {0}", [data.users])}${
					data.role_profiles.length
						? ` · ${__("Role profiles: {0}", [data.role_profiles.map(esc).join(", ")])}`
						: ""
			  }</p>`;
	const reports = erpnext.access_control.list_html(__("Reports"), data.reports, (report) => {
		const unusable =
			report.usable === false
				? ` <span class="indicator-pill orange">${__("Needs Report access to {0}", [
						esc(__(report.ref_doctype)),
				  ])}</span>`
				: "";
		return `<a href="/app/query-report/${encodeURIComponent(report.name)}" target="_blank">${esc(
			report.label
		)}</a>${unusable}`;
	});
	const transitions = erpnext.access_control.list_html(
		__("Workflow actions"),
		data.workflow.transitions,
		(item) =>
			`${esc(__(item.doctype))}: ${esc(item.state)} → <b>${esc(item.action)}</b> → ${esc(
				item.next_state
			)}${item.has_condition ? ` <span class="text-muted">(${__("with condition")})</span>` : ""}`
	);
	const editable = erpnext.access_control.list_html(
		__("Can edit in workflow states"),
		data.workflow.editable_states,
		(item) => `${esc(__(item.doctype))}: ${esc(item.state)}`
	);
	return `<div class="ac-grants">
		${holders}
		${inert}
		<h6 class="ac-heading">${__("Document types")} <span class="text-muted">(${data.doctypes.length})</span></h6>
		${erpnext.access_control.doctypes_html(data.doctypes)}
		${transitions}
		${editable}
		${erpnext.access_control.list_html(
			__("Pages"),
			data.pages,
			(page) => `<a href="/app/${encodeURIComponent(page.name)}" target="_blank">${esc(page.title)}</a>`
		)}
		${reports}
		${erpnext.access_control.list_html(__("Workspaces"), data.workspaces, (ws) => esc(ws.label))}
		${erpnext.access_control.list_html(
			__("Notifications"),
			data.notifications || [],
			(item) =>
				`${esc(item.name)} <span class="text-muted">(${esc(__(item.doctype))} · ${esc(
					item.event
				)} · ${esc(item.channel)})</span>`
		)}
	</div>`;
};

erpnext.access_control.STYLE = `<style>
	.ac-grants .ac-heading { margin-top: var(--margin-lg); }
	.ac-grants .ac-section summary { cursor: pointer; }
	.ac-grants .ac-module { margin-bottom: var(--margin-sm); }
	.ac-grants .ac-module summary { cursor: pointer; padding: 4px 0; }
	.ac-grants .ac-table { margin: 4px 0 0; }
	.ac-grants .ac-doctype { width: 35%; }
	.ac-grants .ac-right { margin: 2px 2px 2px 0; }
	.ac-grants .ac-level { margin-top: 4px; }
	.ac-grants .ac-list { padding-left: 18px; }
	.ac-denial .ac-right { margin: 2px 2px 2px 0; }
	.ac-denial .ac-list { padding-left: 18px; margin-bottom: 0; }
	.ac-denial .ac-message { margin-bottom: var(--margin-sm); }
</style>`;

erpnext.access_control.show_role_grants = (role) =>
	frappe.xcall("erpnext.access_control.permissions_engine.get_role_grants", { role }).then((data) => {
		const dialog = new frappe.ui.Dialog({
			title: __("What role {0} grants", [__(role)]),
			size: "extra-large",
			fields: [{ fieldtype: "HTML", fieldname: "grants" }],
		});
		dialog.fields_dict.grants.$wrapper.html(
			erpnext.access_control.STYLE + erpnext.access_control.render_grants(data)
		);
		dialog.show();
	});

erpnext.access_control.can_manage = () => frappe.user.has_role(["Access Manager", "System Manager"]);
