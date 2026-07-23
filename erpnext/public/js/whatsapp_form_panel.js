// WhatsApp conversation panel shown on CRM forms (read-only recent messages +
// jump to the Chat Center). Wired for the doctypes below via erpnext.bundle.js.

frappe.provide("erpnext.whatsapp");

erpnext.whatsapp.WA_DOCTYPES = [
	"Lead",
	"Contact",
	"Customer",
	"Opportunity",
	"Quotation",
	"Sales Order",
];

erpnext.whatsapp.render_panel = async function (frm) {
	if (frm.is_new()) return;
	// Only for users allowed into the Chat Center (same check the bubble uses).
	if (!erpnext.whatsapp.can_use?.()) return;

	let phone;
	try {
		phone = await frappe.xcall(
			"erpnext.crm.page.whatsapp_chat.whatsapp_chat.resolve_phone",
			{ doctype: frm.doctype, docname: frm.doc.name }
		);
	} catch (e) {
		return;
	}
	if (!phone) return;

	frm.add_custom_button(
		__("Open in Chat Center"),
		() => {
			window.location.href = `/app/whatsapp-chat-center?phone=${encodeURIComponent(phone)}`;
		},
		__("WhatsApp")
	);

	let msgs = [];
	try {
		msgs = await frappe.xcall(
			"erpnext.crm.page.whatsapp_chat.whatsapp_chat.get_recent_messages",
			{ phone, limit: 8 }
		);
	} catch (e) {
		return;
	}
	if (!msgs.length) return;

	const media_label = (ct) =>
		({
			image: "📷 " + __("Photo"),
			video: "🎬 " + __("Video"),
			audio: "🎤 " + __("Audio"),
			document: "📎 " + __("Document"),
			sticker: "🩷 " + __("Sticker"),
		})[ct];

	const sys_tz = frappe.sys_defaults.time_zone || "UTC";
	const bubbles = msgs
		.map((m) => {
			const out = m.type === "Outgoing";
			const caption = frappe.utils.escape_html((m.message || "").replace(/<[^>]*>/g, ""));
			const label = media_label(m.content_type);
			let body;
			if (label) {
				body = caption ? `${label}: ${caption}` : label;
			} else {
				body = caption || `<i>(${__("no text")})</i>`;
			}
			const time = moment.tz(m.creation, sys_tz).local().format("DD.MM HH:mm");
			return `<div class="wa-fp-bubble ${out ? "wa-fp-out" : "wa-fp-in"}">
				<span class="wa-fp-body">${body}</span>
				<div class="wa-fp-meta">${time}</div>
			</div>`;
		})
		.join("");

	if (!document.getElementById("wa-fp-styles")) {
		$(`<style id="wa-fp-styles">
			.wa-fp-wrap{display:flex;flex-direction:column;gap:3px;max-height:280px;overflow-y:auto;padding:8px;}
			.wa-fp-bubble{width:fit-content;max-width:80%;padding:4px 8px 2px;border-radius:8px;font-size:12px;line-height:1.3;}
			.wa-fp-in{align-self:flex-start;background:var(--card-bg);border:1px solid var(--border-color);}
			.wa-fp-out{align-self:flex-end;background:#d9fdd3;color:#111;}
			.wa-fp-body{white-space:pre-wrap;word-break:break-word;}
			.wa-fp-meta{font-size:9px;color:var(--text-muted);text-align:right;opacity:.7;}
		</style>`).appendTo(document.head);
	}

	frm.dashboard.add_section(
		`<div class="wa-fp-wrap">${bubbles}</div>`,
		__("WhatsApp Conversation")
	);
};

erpnext.whatsapp.WA_DOCTYPES.forEach((dt) => {
	frappe.ui.form.on(dt, {
		refresh(frm) {
			erpnext.whatsapp.render_panel(frm);
		},
	});
});
