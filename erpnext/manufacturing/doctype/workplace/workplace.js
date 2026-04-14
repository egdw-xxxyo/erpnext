const SCANNER_API_REFERENCE = `
<div style="font-size: 13px; line-height: 1.6;">
<h5>How it works</h5>
<p>When a scanner sends data, the system first checks if it's a <strong>Workplace barcode</strong> or
<strong>Employee barcode</strong> (attendance_device_id). If so, the scanner's context is switched.
Otherwise, the system resolves what was scanned and calls the matching handler from this script.</p>

<h5>Events</h5>
<pre style="background: var(--bg-color); padding: 10px; border-radius: 4px; font-size: 12px;">
def on_job_card_scanned(e):
    # e.job_card — Job Card name (str)
    # e.doc — Job Card document
    pass

def on_serial_no_scanned(e):
    # e.serial_no — Serial No name (str)
    # e.item_code — Item code of the serial
    pass

def on_item_scanned(e):
    # e.item_code — Item code (str)
    # e.barcode — original barcode if resolved via Item Barcode
    pass

def on_unknown_scanned(e):
    # e.data — raw scanned string
    pass
</pre>

<h5>Common properties on every event (e)</h5>
<table class="table table-bordered" style="font-size: 12px;">
<tr><th>Property</th><th>Description</th></tr>
<tr><td><code>e.data</code></td><td>Raw scanned string</td></tr>
<tr><td><code>e.scanner</code></td><td>Scanner document</td></tr>
<tr><td><code>e.workplace</code></td><td>Current Workplace document</td></tr>
<tr><td><code>e.employee</code></td><td>Current Employee name (str) or None</td></tr>
<tr><td><code>e.state</code></td><td>Current Redis state (dict or None)</td></tr>
</table>

<h5>Return value</h5>
<pre style="background: var(--bg-color); padding: 10px; border-radius: 4px; font-size: 12px;">
return {
    "message": "Job Card JC-001 started",
    "prompt": "Scan next barcode",           # optional
    "set_state": {"mode": "scanning", ...},  # optional, set Redis state
    "clear_state": True,                     # optional, clear Redis state
}
</pre>

<h5>Example: Start or finish Job Card by serial number</h5>
<pre style="background: var(--bg-color); padding: 10px; border-radius: 4px; font-size: 12px;">
def on_serial_no_scanned(e):
    jc_list = frappe.get_all("Job Card", filters={
        "serial_no": ["like", f"%{e.serial_no}%"],
        "docstatus": ("<", 2),
        "status": ["not in", ["Completed", "Stopped", "Cancelled"]],
    }, fields=["name", "status"], order_by="expected_start_date", limit=1)

    if not jc_list:
        frappe.throw(f"No active Job Card for serial {e.serial_no}")

    jc = jc_list[0]
    doc = frappe.get_doc("Job Card", jc.name)

    if jc.status in ("Open", "Material Transferred"):
        if e.employee:
            if not any(r.employee == e.employee for r in doc.employee):
                doc.append("employee", {"employee": e.employee})
            doc.append("time_logs", {
                "from_time": frappe.utils.now_datetime(),
                "employee": e.employee,
            })
        doc.db_set("status", "Work In Progress")
        doc.save(ignore_permissions=True)
        return {"message": f"Started {doc.name}"}

    elif jc.status == "Work In Progress":
        qty = frappe.utils.flt(doc.for_quantity)
        for row in doc.time_logs:
            if row.from_time and not row.to_time:
                row.to_time = frappe.utils.now_datetime()
                row.time_in_mins = frappe.utils.time_diff_in_seconds(
                    row.to_time, row.from_time) / 60
                row.completed_qty = qty
                break
        doc.save(ignore_permissions=True)
        doc.submit()
        return {"message": f"Completed {doc.name}"}
</pre>
</div>
`;

frappe.ui.form.on("Workplace", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Open Portal"), () => {
				frappe.set_route("workplace-portal", { workplace: frm.doc.name });
			}, __("View"));
		}
		render_scanner_scripts(frm);
		setup_barcode_generate(frm);
		if (!frm._barcode_field) {
			frm._barcode_field = new erpnext.BarcodeField({
				frm,
				fieldname: "barcode",
				barcode_type: "CODE128",
				format: "CODE128",
			});
		}
		frm._barcode_field.refresh();
	},
	barcode(frm) {
		frm._barcode_field && frm._barcode_field.refresh();
	},
});

function render_scanner_scripts(frm) {
	const $wrapper = frm.fields_dict.scanner_scripts_html?.$wrapper;
	if (!$wrapper) return;

	if (frm.is_new()) {
		$wrapper.html('<p class="text-muted">Save the document first.</p>');
		return;
	}

	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Scanner Script",
			filters: [
				["is_active", "=", 1],
				["workplace", "in", [frm.doc.name, null, ""]],
			],
			fields: ["name", "script_name", "workplace", "is_active"],
			order_by: "workplace desc, creation asc",
		},
		callback: (r) => {
			const scripts = r.message || [];
			if (!scripts.length) {
				$wrapper.html(`
					<p class="text-muted">No scanner scripts configured for this workplace.</p>
					<a class="btn btn-xs btn-default" href="/app/scanner-script/new?workplace=${encodeURIComponent(frm.doc.name)}">
						+ New Scanner Script
					</a>
				`);
				return;
			}

			let html = '<div style="margin-bottom: 10px;">';
			html += `<a class="btn btn-xs btn-default" href="/app/scanner-script/new?workplace=${encodeURIComponent(frm.doc.name)}">
				+ New Scanner Script
			</a></div>`;
			html += '<table class="table table-bordered" style="font-size: 13px;"><thead><tr>';
			html += '<th>Script</th><th>Scope</th></tr></thead><tbody>';

			for (const s of scripts) {
				const scope = s.workplace
					? `<span class="indicator-pill green">This workplace</span>`
					: `<span class="indicator-pill blue">General</span>`;
				html += `<tr>
					<td><a href="/app/scanner-script/${encodeURIComponent(s.name)}">${frappe.utils.escape_html(s.script_name)}</a></td>
					<td>${scope}</td>
				</tr>`;
			}

			html += "</tbody></table>";
			$wrapper.html(html);
		},
	});
}

function setup_barcode_generate(frm) {
	const $wrapper = frm.fields_dict.barcode.$wrapper;
	$wrapper.find(".btn-generate-barcode").remove();

	if (frm.doc.barcode) return;

	const $btn = $(`<button class="btn btn-xs btn-default btn-generate-barcode" style="margin-top: 6px;">
		${__("Generate Barcode")}
	</button>`);

	$wrapper.find(".help-box").before($btn);

	$btn.on("click", () => {
		const hash = Array.from(crypto.getRandomValues(new Uint8Array(4)))
			.map((b) => b.toString(16).padStart(2, "0"))
			.join("")
			.toUpperCase();
		frm.set_value("barcode", `WP-${hash}`);
		frm.dirty();
	});
}
