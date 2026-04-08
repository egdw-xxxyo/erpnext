const SCANNER_API_REFERENCE = `
<div style="font-size: 13px; line-height: 1.6;">
<h5>How it works</h5>
<p>When a scanner sends data, the system first checks if it's a <strong>Workplace barcode</strong> or
<strong>Employee barcode</strong> (attendance_device_id). If so, the scanner's context is switched.
Otherwise, the system resolves what was scanned and calls the matching handler from this script.</p>

<p><strong>Execution order:</strong> workplace-specific scripts run first, then general scripts (no workplace).
The first script that returns a result wins.</p>

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
<tr><td><code>e.scanner</code></td><td>Scanner Setup document</td></tr>
<tr><td><code>e.workplace</code></td><td>Current Workplace document</td></tr>
<tr><td><code>e.employee</code></td><td>Current Employee name (str) or None</td></tr>
</table>

<h5>Return value</h5>
<pre style="background: var(--bg-color); padding: 10px; border-radius: 4px; font-size: 12px;">
return {
    "message": "Job Card JC-001 started",
    "prompt": "Scan next barcode",           # optional
    "target_doctype": "Job Card",            # optional, for scan log
    "target_document": "JC-001",             # optional, for scan log
}
</pre>
</div>
`;

frappe.ui.form.on("Scanner Script", {
	refresh(frm) {
		if (frm.fields_dict.help_html) {
			frm.fields_dict.help_html.$wrapper.html(SCANNER_API_REFERENCE);
		}
	},
});
