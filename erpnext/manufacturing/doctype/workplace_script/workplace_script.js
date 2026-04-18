const WORKPLACE_SCRIPT_API_REFERENCE = `
<div style="font-size: 13px; line-height: 1.6;">
<h5>${__("How it works")}</h5>
<p>${__("When a scanner sends data, the system resolves what was scanned and calls")} <code>on_scan(e)</code>
${__("from the Workplace Script matching the scanner's current workplace. If no workplace-specific script is found, the default script (no workplace) runs.")}</p>

<p>${__("The script controls everything — setting workplace/employee, returning messages, managing multi-step state. Reusable logic lives in")} <strong>${__("Scanner Scripts")}</strong>, ${__("accessible via the")}
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
<tr><td><code>e.doc</code></td><td>Document</td><td>${__("Resolved Frappe document (Workplace, Employee, Job Card, Serial No, Item) or None")}</td></tr>
<tr><td><code>e.item_code</code></td><td>str</td><td>${__("Item code (for serial_no and item scans)")}</td></tr>
<tr><td><code>e.barcode</code></td><td>str</td><td>${__("Original barcode (if resolved via Item Barcode)")}</td></tr>
<tr><td><code>e.scanner</code></td><td>Document</td><td>${__("Scanner document")}</td></tr>
<tr><td><code>e.workplace</code></td><td>Document</td><td>${__("Current Workplace document (from scanner context, not this scan)")}</td></tr>
<tr><td><code>e.employee</code></td><td>str</td><td>${__("Current Employee name (from scanner context)")}</td></tr>
</table>

<h5>${__("State API")} (e.state)</h5>
<p>${__("State persists between scans in Redis with automatic timeout.")}</p>
<table class="table table-bordered" style="font-size: 12px;">
<tr><th>${__("Property / Method")}</th><th>${__("Description")}</th></tr>
<tr><td><code>e.state.name</code></td><td>${__("Current state name (str) or None if idle")}</td></tr>
<tr><td><code>e.state.context</code></td><td>${__("Dict of state context data")}</td></tr>
<tr><td><code>e.state.set("name", {ctx})</code></td><td>${__("Transition to a new state with optional context")}</td></tr>
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

frappe.ui.form.on("Workplace Script", {
	refresh(frm) {
		if (frm.fields_dict.help_html) {
			frm.fields_dict.help_html.$wrapper.html(WORKPLACE_SCRIPT_API_REFERENCE);
		}
	},
});
