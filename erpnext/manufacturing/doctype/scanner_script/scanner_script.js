const SCANNER_SCRIPT_API_REFERENCE = `
<div style="font-size: 13px; line-height: 1.6;">
<h5>${__("Scanner Script — Reusable Library")}</h5>
<p>${__("Scanner Scripts are")} <strong>${__("reusable function libraries")}</strong> ${__("that can be called from")}
<strong>${__("Workplace Scripts")}</strong>. ${__("They do not have an entry point like")} <code>on_scan</code> —
${__("instead, they define functions that Workplace Scripts invoke.")}</p>

<p>${__("All active Scanner Scripts are loaded into the")} <code>scripts</code> ${__("namespace in Workplace Scripts.")})
${__("Access them by script name (lowercased, spaces/dashes → underscores).")}</p>

<h5>${__("Example Scanner Script")}: "job_cards"</h5>
<pre style="background: var(--bg-color); padding: 10px; border-radius: 4px; font-size: 12px;">
def start_or_finish(job_card_doc):
    if job_card_doc.status == "Open":
        job_card_doc.start_job()
    elif job_card_doc.status == "Work In Progress":
        job_card_doc.complete_job()

def link_serial(job_card_name, serial_no):
    frappe.db.set_value("Serial No", serial_no, "job_card", job_card_name)
</pre>

<h5>${__("Usage in Workplace Script")}</h5>
<pre style="background: var(--bg-color); padding: 10px; border-radius: 4px; font-size: 12px;">
def on_scan(e):
    if e.scan_type == "job_card":
        scripts.job_cards.start_or_finish(e.doc)
        return {"message": f"Job Card {e.doc.name} updated"}
</pre>

<p>${__("frappe and json modules are available in the script scope.")}</p>
</div>
`;

frappe.ui.form.on("Scanner Script", {
	refresh(frm) {
		if (frm.fields_dict.help_html) {
			frm.fields_dict.help_html.$wrapper.html(SCANNER_SCRIPT_API_REFERENCE);
		}
	},
});
