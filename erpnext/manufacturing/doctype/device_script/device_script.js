const DEVICE_SCRIPT_API_REFERENCE = `
<div style="font-size: 13px; line-height: 1.6;">
<h5>${__("Device Script — Scanner vs Reflectometer")}</h5>
<p><strong>${__("Scanner")}</strong> ${__("scripts are reusable function libraries invoked from Workplace Scripts via the")} <code>scripts</code> ${__("namespace. No entry point — define functions only.")}</p>
<p><strong>${__("Reflectometer")}</strong> ${__("scripts run automatically after each OTDR measurement is uploaded. Define")} <code>on_event(ctx)</code> ${__("or")} <code>on_reflectometer(ctx)</code>. ${__("ctx fields:")} <code>ctx.otdr</code>, <code>ctx.log_entry</code>, <code>ctx.payload</code> ${__("(parsed dict).")}</p>

<h5>${__("Example Scanner Script")}: "job_cards"</h5>
<pre style="background: var(--bg-color); padding: 10px; border-radius: 4px; font-size: 12px;">
def start_or_finish(job_card_doc):
    if job_card_doc.status == "Open":
        job_card_doc.start_job()
    elif job_card_doc.status == "Work In Progress":
        job_card_doc.complete_job()
</pre>

<h5>${__("Example Reflectometer Script")}</h5>
<pre style="background: var(--bg-color); padding: 10px; border-radius: 4px; font-size: 12px;">
def on_event(ctx):
    summary = (ctx.payload.get("Summary") or {})
    loss = summary.get("end_to_end_loss_db")
    ctx.log("measurement received", otdr=ctx.otdr.name, loss_db=loss)
    if loss is not None and loss > 3:
        ctx.log(f"loss alert: {loss} dB", level="WARN", payload_keys=list(ctx.payload.keys()))
</pre>
<p>${__("ctx.log(message, level='INFO'|'WARN'|'ERROR', **extra) appends a line to this run's logs. After the script returns, the run is stored under")} <strong>${__("Recent Runs")}</strong> ${__("on this script (last 200 kept, older auto-pruned).")}</p>

<p>${__("frappe and json modules are available in the script scope.")}</p>
</div>
`;

function refresh_version_selects(frm) {
	const opts = (frm.doc.versions || []).map((v) => v.version).filter(Boolean);
	const opt_str = ["", ...opts].join("\n");
	frm.set_df_property("default_version", "options", opt_str);
	frm.set_df_property("viewing_version", "options", opt_str);
	frm.refresh_field("default_version");
	frm.refresh_field("viewing_version");
}

function next_version_name(frm) {
	let n = 0;
	(frm.doc.versions || []).forEach((v) => {
		const m = /^v(\d+)$/.exec(v.version || "");
		if (m) n = Math.max(n, parseInt(m[1], 10));
	});
	return `v${n + 1}`;
}

function capture_working_copy_json(frm) {
	return JSON.stringify({ script: frm.doc.script || "" });
}

function persist_working_copy_to(frm, version_name) {
	const row = (frm.doc.versions || []).find((v) => v.version === version_name);
	if (!row) return;
	row.snapshot = capture_working_copy_json(frm);
}

function load_snapshot_into_working_copy(frm, version_name) {
	const row = (frm.doc.versions || []).find((v) => v.version === version_name);
	if (!row) return;
	let snap = {};
	try {
		snap = JSON.parse(row.snapshot || "{}");
	} catch (e) {
		snap = {};
	}
	frm.set_value("script", snap.script || "");
}

frappe.ui.form.on("Device Script", {
	onload(frm) {
		frm.__prev_viewing = frm.doc.viewing_version;
	},
	refresh(frm) {
		if (frm.fields_dict.help_html) {
			frm.fields_dict.help_html.$wrapper.html(DEVICE_SCRIPT_API_REFERENCE);
		}
		refresh_version_selects(frm);

		frm.add_custom_button(__("+ Add Version"), () => {
			persist_working_copy_to(frm, frm.doc.viewing_version);
			const name = next_version_name(frm);
			const row = frm.add_child("versions");
			row.version = name;
			row.is_default = 0;
			row.snapshot = capture_working_copy_json(frm);
			row.created_on = frappe.datetime.now_datetime();
			refresh_version_selects(frm);
			frm.refresh_field("versions");
			frm.__prev_viewing = name;
			frm.set_value("viewing_version", name);
			frm.dirty();
		}, __("Versions"));

		frm.add_custom_button(__("Remove Version"), () => {
			const versions = frm.doc.versions || [];
			if (versions.length <= 1) {
				frappe.msgprint(__("Cannot remove the only version"));
				return;
			}
			const cur = frm.doc.viewing_version;
			const row = versions.find((v) => v.version === cur);
			if (!row) return;
			if (row.is_default) {
				frappe.msgprint(__("Cannot remove the default version. Switch default to another version first."));
				return;
			}
			frappe.confirm(__("Remove version {0}?", [cur]), () => {
				const idx = versions.indexOf(row);
				versions.splice(idx, 1);
				versions.forEach((v, i) => { v.idx = i + 1; });
				refresh_version_selects(frm);
				frm.refresh_field("versions");
				frm.__prev_viewing = frm.doc.default_version;
				frm.set_value("viewing_version", frm.doc.default_version);
				frm.dirty();
			});
		}, __("Versions"));

		frm.add_custom_button(__("Set Displayed as Default"), () => {
			const cur = frm.doc.viewing_version;
			(frm.doc.versions || []).forEach((v) => { v.is_default = (v.version === cur) ? 1 : 0; });
			frm.doc.default_version = cur;
			frm.refresh_field("versions");
			frm.refresh_field("default_version");
			frm.dirty();
		}, __("Versions"));
	},
	viewing_version(frm) {
		const next = frm.doc.viewing_version;
		const prev = frm.__prev_viewing;
		if (!next || next === prev) return;
		if (prev) persist_working_copy_to(frm, prev);
		load_snapshot_into_working_copy(frm, next);
		frm.__prev_viewing = next;
		frm.refresh_field("versions");
	},
	default_version(frm) {
		const cur = frm.doc.default_version;
		if (!cur) return;
		(frm.doc.versions || []).forEach((v) => { v.is_default = (v.version === cur) ? 1 : 0; });
		frm.refresh_field("versions");
	},
});
