const WORKPLACE_SCRIPT_API_REFERENCE = `
<div style="font-size: 13px; line-height: 1.6;">
<h5>${__("How it works")}</h5>
<p>${__("When a scanner sends data, the system resolves what was scanned and calls")} <code>on_scan(e)</code>
${__(
	"from the Workplace Script matching the scanner's current workplace. If no workplace-specific script is found, the default script (no workplace) runs."
)}</p>

<p>${__(
	"The script controls everything — setting workplace/employee, returning messages, managing multi-step state. Reusable logic lives in"
)} <strong>${__("Scanner Scripts")}</strong>, ${__("accessible via the")}
<code>scripts</code> ${__("namespace")}.</p>

<h5>${__("Entry point")}</h5>
<pre style="background: var(--bg-color); padding: 10px; border-radius: 4px; font-size: 12px;">
def on_scan(e):
    if e.scan_type == "workplace":
        e.set_workplace(e.doc.name)
        return {"message": f"WP: {e.doc.name}"}

    if e.scan_type == "employee":
        e.set_employee(e.doc.name)
        return {"message": f"Employee: {e.doc.employee_name}"}

    if e.scan_type == "job_card":
        return {"message": f"Job Card: {e.doc.name}"}
</pre>

<h5>${__("Event properties")} (e)</h5>
<table class="table table-bordered" style="font-size: 12px;">
<tr><th>${__("Property")}</th><th>${__("Type")}</th><th>${__("Description")}</th></tr>
<tr><td><code>e.data</code></td><td>str</td><td>${__("Raw scanned string")}</td></tr>
<tr><td><code>e.scan_type</code></td><td>str</td><td>"workplace" | "employee" | "job_card" | "serial_no" | "item" | "command" | "packing_template" | "unknown"</td></tr>
<tr><td><code>e.doc</code></td><td>Document</td><td>${__(
	"Resolved Frappe document (Workplace, Employee, Job Card, Serial No, Item) or None"
)}</td></tr>
<tr><td><code>e.item_code</code></td><td>str</td><td>${__(
	"Item code (for serial_no and item scans)"
)}</td></tr>
<tr><td><code>e.barcode</code></td><td>str</td><td>${__(
	"Original barcode (if resolved via Item Barcode)"
)}</td></tr>
<tr><td><code>e.scanner</code></td><td>Document</td><td>${__("Scanner document")}</td></tr>
<tr><td><code>e.workplace</code></td><td>Document</td><td>${__(
	"Current Workplace document (from scanner context, not this scan)"
)}</td></tr>
<tr><td><code>e.employee</code></td><td>str</td><td>${__(
	"Current Employee name (from scanner context)"
)}</td></tr>
</table>

<h5>${__("State API")} (e.state)</h5>
<p>${__("State persists between scans in Redis with automatic timeout.")}</p>
<table class="table table-bordered" style="font-size: 12px;">
<tr><th>${__("Property / Method")}</th><th>${__("Description")}</th></tr>
<tr><td><code>e.state.name</code></td><td>${__("Current state name (str) or None if idle")}</td></tr>
<tr><td><code>e.state.context</code></td><td>${__("Dict of state context data")}</td></tr>
<tr><td><code>e.state.set("name", {ctx})</code></td><td>${__(
	"Transition to a new state with optional context"
)}</td></tr>
<tr><td><code>e.state.clear()</code></td><td>${__("Clear state (return to idle)")}</td></tr>
</table>

<h5>${__("Helper methods")}</h5>
<table class="table table-bordered" style="font-size: 12px;">
<tr><th>${__("Method")}</th><th>${__("Description")}</th></tr>
<tr><td><code>e.set_workplace(name)</code></td><td>${__("Set the scanner's current workplace")}</td></tr>
<tr><td><code>e.set_employee(name)</code></td><td>${__("Set the scanner's current employee")}</td></tr>
</table>

<h5>${__("Calling Scanner Scripts")}</h5>
<p>${__("All active Scanner Scripts are loaded into the")} <code>scripts</code> ${__("namespace")}.
${__("The key is the script name (lowercased, spaces/dashes → underscores).")}</p>
<pre style="background: var(--bg-color); padding: 10px; border-radius: 4px; font-size: 12px;">
# ${__("Scanner Script named")} "job_cards" ${__("defines")}:
#   def finish_card(card_name): ...

# ${__("In Workplace Script")}:
def on_scan(e):
    if e.scan_type == "job_card":
        scripts.job_cards.finish_card(e.doc.name)
        return {"message": "Done"}
</pre>

<h5>${__("Return value")}</h5>
<pre style="background: var(--bg-color); padding: 10px; border-radius: 4px; font-size: 12px;">
return {
    "message": "Job Card started",          # ${__("text for scanner display")}
    "prompt": "Scan next barcode",          # ${__("optional status line")}
    "image": "...",                          # ${__("optional image data")}
    "target_doctype": "Job Card",           # ${__("optional, for scan log")}
    "target_document": "JC-001",            # ${__("optional, for scan log")}
}
</pre>

<h5>${__("Multi-step example")}</h5>
<pre style="background: var(--bg-color); padding: 10px; border-radius: 4px; font-size: 12px;">
def on_scan(e):
    if e.scan_type == "workplace":
        e.set_workplace(e.doc.name)
        return {"message": f"WP: {e.doc.name}"}

    if e.scan_type == "employee" and not e.state.name:
        e.set_employee(e.doc.name)
        return {"message": f"Employee: {e.doc.employee_name}"}

    # ${__("Step 1: scan item → enter awaiting_employee state")}
    if e.scan_type == "item" and not e.state.name:
        e.state.set("awaiting_employee", {"item_code": e.item_code})
        return {"message": f"Item: {e.item_code}", "prompt": "Scan employee"}

    # ${__("Step 2: in awaiting_employee state → assign employee")}
    if e.state.name == "awaiting_employee":
        if e.scan_type == "employee":
            item = e.state.context["item_code"]
            e.state.clear()
            return {"message": f"Assigned {item} to {e.doc.employee_name}"}
        return {"message": "Expected employee badge"}
</pre>
</div>
`;

const MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js";

function load_mermaid() {
	if (window.mermaid) return Promise.resolve(window.mermaid);
	if (window._mermaid_loading) return window._mermaid_loading;
	window._mermaid_loading = new Promise((resolve, reject) => {
		const script = document.createElement("script");
		script.src = MERMAID_CDN;
		script.onload = () => {
			window.mermaid.initialize({ startOnLoad: false, theme: "default", securityLevel: "loose" });
			resolve(window.mermaid);
		};
		script.onerror = reject;
		document.head.appendChild(script);
	});
	return window._mermaid_loading;
}

function unique_id(prefix, raw, seen) {
	let base = (raw || "").replace(/[^A-Za-z0-9_]/g, "");
	if (!base) {
		let hash = 0;
		for (let i = 0; i < raw.length; i++) hash = ((hash << 5) - hash + raw.charCodeAt(i)) | 0;
		base = "x" + Math.abs(hash).toString(36);
	}
	let id = prefix + base;
	let n = 1;
	while (seen.has(id)) {
		id = prefix + base + "_" + ++n;
	}
	seen.add(id);
	return id;
}

function build_diagram_source(frm, extras) {
	const states = frm.doc.states || [];
	const transitions = frm.doc.transitions || [];
	const subflows = (extras && extras.subflows) || [];
	const entries = (extras && extras.entries) || [];
	if (!states.length && !transitions.length && !subflows.length) return null;

	const lines = ["stateDiagram-v2"];
	const escape_label = (s) => (s || "").replace(/"/g, "'").replace(/:/g, "·");
	const seen = new Set();

	const ids = {};
	states.forEach((s) => {
		ids[s.state] = unique_id("", s.state, seen);
		const label = s.label || s.state;
		lines.push(`${ids[s.state]} : ${escape_label(label)}`);
	});

	states.filter((s) => s.is_initial).forEach((s) => lines.push(`[*] --> ${ids[s.state]}`));
	states.filter((s) => s.is_final).forEach((s) => lines.push(`${ids[s.state]} --> [*]`));

	transitions.forEach((t) => {
		const from = ids[t.from_state] || unique_id("", t.from_state, seen);
		const isExit = !t.to_state || t.to_state === "__exit__";
		const to = isExit ? "[*]" : ids[t.to_state] || unique_id("", t.to_state, seen);
		lines.push(`${from} --> ${to} : ${escape_label(t.event)}`);
	});

	const subflowIds = {};
	subflows.forEach((sf) => {
		const sid = unique_id("SUB_", sf.name, seen);
		subflowIds[sf.name] = sid;
		const lbl = `▶ ${sf.name}` + (sf.initial_state ? ` → ${sf.initial_state}` : "");
		lines.push(`${sid} : ${escape_label(lbl)}`);
	});

	entries.forEach((en) => {
		const fromState = en.from_state;
		if (!fromState) return;
		const fromId = ids[fromState] || unique_id("", fromState, seen);
		if (!ids[fromState]) {
			ids[fromState] = fromId;
			lines.push(`${fromId} : ${escape_label(fromState)}`);
		}
		const safeVal = (en.trigger_value || "").replace(/:/g, "·");
		const trig = en.trigger_type === "Command" ? safeVal : `scan ${safeVal}`;
		const sid = subflowIds[en.target_subflow];
		if (sid) lines.push(`${fromId} --> ${sid} : ${escape_label(trig)}`);
	});

	return lines.join("\n");
}

function build_subflow_legend(extras) {
	const subflows = (extras && extras.subflows) || [];
	if (!subflows.length) return "";
	const items = subflows.map((sf) => {
		const url = `/app/workplace-script/${encodeURIComponent(sf.name)}`;
		const initial = sf.initial_state
			? ` <span class="text-muted">→ ${frappe.utils.escape_html(sf.initial_state)}</span>`
			: "";
		return `<li><a href="${url}">▶ ${frappe.utils.escape_html(sf.name)}</a>${initial}</li>`;
	});
	return `<div class="workplace-script-subflows" style="margin-top:12px;font-size:12px;"><strong>${__(
		"Subflows"
	)}</strong><ul style="margin:4px 0 0 20px;padding:0;">${items.join("")}</ul></div>`;
}

async function fetch_diagram_extras(frm) {
	if (frm.doc.parent_script) return null;
	if (frm.is_new()) return null;
	try {
		const r = await frappe.call({
			method: "erpnext.devices.doctype.workplace_script.workplace_script.get_diagram_extras",
			args: { script_name: frm.docname },
		});
		return r.message || null;
	} catch (e) {
		return null;
	}
}

async function render_diagram(frm) {
	const wrapper = frm.fields_dict.diagram_html && frm.fields_dict.diagram_html.$wrapper;
	if (!wrapper) return;

	const extras = await fetch_diagram_extras(frm);
	const source = build_diagram_source(frm, extras);
	if (!source) {
		wrapper.html(
			`<div class="text-muted small">${__("Add states and transitions to render the diagram.")}</div>`
		);
		return;
	}

	try {
		const mermaid = await load_mermaid();
		const id = `wsd_${frm.docname.replace(/[^A-Za-z0-9]/g, "_")}_${Date.now()}`;
		const { svg } = await mermaid.render(id, source);
		const legend = build_subflow_legend(extras);
		wrapper.html(`<div class="workplace-script-diagram">${svg}</div>${legend}`);
	} catch (err) {
		const legend = build_subflow_legend(extras);
		wrapper.html(
			`<pre style="color: var(--text-muted); font-size: 11px;">${frappe.utils.escape_html(
				String(err)
			)}\n\n${frappe.utils.escape_html(source)}</pre>${legend}`
		);
	}
}

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
	return JSON.stringify({
		script: frm.doc.script || "",
		states: (frm.doc.states || []).map((s) => ({
			state: s.state,
			label: s.label,
			is_initial: s.is_initial ? 1 : 0,
			is_final: s.is_final ? 1 : 0,
			position_x: s.position_x,
			position_y: s.position_y,
			on_enter_script: s.on_enter_script,
		})),
		transitions: (frm.doc.transitions || []).map((t) => ({
			from_state: t.from_state,
			event: t.event,
			to_state: t.to_state,
		})),
	});
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
	frm.doc.script = snap.script || "";
	frm.clear_table("states");
	(snap.states || []).forEach((s) => {
		const child = frm.add_child("states");
		Object.assign(child, s);
	});
	frm.clear_table("transitions");
	(snap.transitions || []).forEach((t) => {
		const child = frm.add_child("transitions");
		Object.assign(child, t);
	});
	frm.refresh_fields(["script", "states", "transitions"]);
	render_diagram(frm);
}

frappe.ui.form.on("Workplace Script", {
	onload(frm) {
		frm.__prev_viewing = frm.doc.viewing_version;
	},
	refresh(frm) {
		if (frm.fields_dict.help_html) {
			frm.fields_dict.help_html.$wrapper.html(WORKPLACE_SCRIPT_API_REFERENCE);
		}
		refresh_version_selects(frm);
		render_diagram(frm);

		frm.add_custom_button(
			__("+ Add Version"),
			() => {
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
			},
			__("Versions")
		);

		frm.add_custom_button(
			__("Remove Version"),
			() => {
				const versions = frm.doc.versions || [];
				if (versions.length <= 1) {
					frappe.msgprint(__("Cannot remove the only version"));
					return;
				}
				const cur = frm.doc.viewing_version;
				const row = versions.find((v) => v.version === cur);
				if (!row) return;
				if (row.is_default) {
					frappe.msgprint(
						__("Cannot remove the default version. Switch default to another version first.")
					);
					return;
				}
				frappe.confirm(__("Remove version {0}?", [cur]), () => {
					const idx = versions.indexOf(row);
					versions.splice(idx, 1);
					versions.forEach((v, i) => {
						v.idx = i + 1;
					});
					refresh_version_selects(frm);
					frm.refresh_field("versions");
					frm.__prev_viewing = frm.doc.default_version;
					frm.set_value("viewing_version", frm.doc.default_version);
					frm.dirty();
				});
			},
			__("Versions")
		);

		frm.add_custom_button(
			__("Set Displayed as Default"),
			() => {
				const cur = frm.doc.viewing_version;
				(frm.doc.versions || []).forEach((v) => {
					v.is_default = v.version === cur ? 1 : 0;
				});
				frm.doc.default_version = cur;
				frm.refresh_field("versions");
				frm.refresh_field("default_version");
				frm.dirty();
			},
			__("Versions")
		);
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
		(frm.doc.versions || []).forEach((v) => {
			v.is_default = v.version === cur ? 1 : 0;
		});
		frm.refresh_field("versions");
	},
});

frappe.ui.form.on("Workplace Script State", {
	states_remove: render_diagram,
	state: render_diagram,
	label: render_diagram,
	is_initial: render_diagram,
	is_final: render_diagram,
});

frappe.ui.form.on("Workplace Script Transition", {
	transitions_remove: render_diagram,
	from_state: render_diagram,
	to_state: render_diagram,
	event: render_diagram,
});
