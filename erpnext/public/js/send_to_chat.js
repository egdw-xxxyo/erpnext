// "Send to chat" — a global 3-dot-menu action that shares the current desk object
// (a record form, a report, or a page) into Employee Chat as a rich link card.
//
// The menu item is injected on every form (via the global `form-refresh` event) and on
// report / query-report views (via route change). The picker dialog lets the user drop
// the link into an existing thread or start a new direct chat. The link is resolved to a
// card server-side (`resolve_link`) and sent with `content_type="link"`.

frappe.provide("erpnext.send_to_chat");

const STC_API = "erpnext.crm.page.employee_chat.employee_chat";

function stc_can_use() {
	return !!(
		erpnext.whatsapp &&
		erpnext.whatsapp.can_use_employee_chat &&
		erpnext.whatsapp.can_use_employee_chat()
	);
}

// The real desk URL of whatever is on screen — correct for forms, lists, reports and
// pages alike, already percent-encoded (the server unquotes it).
function stc_desk_url() {
	return window.location.origin + window.location.pathname;
}

function stc_card_icon(kind) {
	return (
		{
			document: "📄",
			report: "📊",
			list: "🗂️",
			page: "🔗",
			external: "🔗",
		}[kind] || "🔗"
	);
}

// Send a resolved card into one thread. Secret threads carry the card inside the
// encrypted payload; normal threads store it in `link_data`.
async function stc_send(thread, is_secret, card) {
	const args = { thread, content_type: "link" };
	if (is_secret) {
		if (!(await erpnext.chat_crypto.ensure_unlocked())) return false;
		const { ciphertext, iv } = await erpnext.chat_crypto.encrypt(thread, { link: card });
		args.message = ciphertext;
		args.is_encrypted = 1;
		args.enc_iv = iv;
	} else {
		args.link_data = JSON.stringify(card);
	}
	await frappe.xcall(STC_API + ".send_message", args);
	return true;
}

erpnext.send_to_chat.open = async function (url) {
	if (!stc_can_use()) {
		frappe.msgprint(__("You do not have access to Employee Chat"));
		return;
	}

	let card;
	try {
		card = await frappe.xcall(STC_API + ".resolve_link", { url });
	} catch (e) {
		card = { kind: "page", url, title: url };
	}
	if (!card || !card.url) card = { kind: "page", url, title: url };

	const [threads, people] = await Promise.all([
		frappe.xcall(STC_API + ".get_threads"),
		frappe.xcall(STC_API + ".search_employees", { txt: "" }),
	]);

	const d = new frappe.ui.Dialog({
		title: __("Send to chat"),
		fields: [
			{ fieldtype: "HTML", fieldname: "preview" },
			{
				fieldtype: "Data",
				fieldname: "search",
				label: __("Search chats and people"),
				placeholder: __("Search chats and people"),
			},
			{ fieldtype: "HTML", fieldname: "list" },
		],
	});

	// Card preview at the top of the dialog.
	d.fields_dict.preview.$wrapper.html(`
		<div style="display:flex;gap:10px;align-items:center;padding:8px 10px;border:1px solid var(--border-color);border-radius:8px;margin-bottom:8px;">
			<div style="font-size:22px;">${stc_card_icon(card.kind)}</div>
			<div style="min-width:0;">
				<div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${frappe.utils.escape_html(
					card.title || card.url
				)}</div>
				<div style="color:var(--text-muted);font-size:var(--text-sm);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${frappe.utils.escape_html(
					card.subtitle || card.doctype || card.url
				)}</div>
			</div>
		</div>
	`);

	const $list = d.fields_dict.list.$wrapper;

	const send_and_close = async (fn) => {
		frappe.dom.freeze(__("Sending…"));
		try {
			const ok = await fn();
			if (ok !== false) {
				d.hide();
				frappe.show_alert({ message: __("Sent to chat"), indicator: "green" });
			}
		} catch (e) {
			frappe.msgprint(__("Failed to send"));
		} finally {
			frappe.dom.unfreeze();
		}
	};

	const render = (txt) => {
		txt = (txt || "").toLowerCase();
		const rows = [];

		const matching_threads = (threads || []).filter(
			(t) => !txt || (t.display_title || "").toLowerCase().includes(txt)
		);
		for (const t of matching_threads) {
			rows.push({
				title: t.display_title,
				subtitle: t.thread_type === "Group" ? __("Group chat") : __("Direct chat"),
				image: null,
				on_click: () => send_and_close(() => stc_send(t.name, t.is_secret, card)),
			});
		}

		const in_thread = new Set(
			(threads || []).filter((t) => t.thread_type === "Direct" && t.other_user).map((t) => t.other_user)
		);
		const matching_people = (people || []).filter(
			(p) =>
				!in_thread.has(p.user_id) &&
				(!txt || (p.employee_name || p.user_id || "").toLowerCase().includes(txt))
		);
		for (const p of matching_people) {
			rows.push({
				title: p.employee_name || p.user_id,
				subtitle: __("Start a chat"),
				image: p.image,
				on_click: () =>
					send_and_close(async () => {
						const res = await frappe.xcall(STC_API + ".create_thread", {
							participant_users: JSON.stringify([p.user_id]),
						});
						return stc_send(res.name, res.is_secret, card);
					}),
			});
		}

		$list.empty();
		if (!rows.length) {
			$list.html(
				`<div style="color:var(--text-muted);padding:12px 4px;text-align:center;">${__(
					"No chats or people found"
				)}</div>`
			);
			return;
		}
		const $wrap = $(`<div style="max-height:46vh;overflow-y:auto;margin-top:6px;"></div>`).appendTo(
			$list
		);
		for (const r of rows) {
			const av = r.image
				? `<img src="${frappe.utils.escape_html(
						r.image
				  )}" style="width:100%;height:100%;object-fit:cover;">`
				: frappe.utils.escape_html((r.title || "?").trim().charAt(0).toUpperCase());
			const $row = $(`
				<div style="display:flex;gap:10px;align-items:center;padding:7px 6px;border-bottom:1px solid var(--border-color);cursor:pointer;">
					<div style="flex:none;width:32px;height:32px;border-radius:50%;background:var(--bg-light-gray);display:flex;align-items:center;justify-content:center;font-weight:600;color:var(--text-muted);overflow:hidden;">${av}</div>
					<div style="min-width:0;">
						<div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"></div>
						<div style="color:var(--text-muted);font-size:var(--text-sm);"></div>
					</div>
				</div>
			`);
			$row.find("div").eq(1).children().eq(0).text(r.title);
			$row.find("div").eq(1).children().eq(1).text(r.subtitle);
			$row.on("click", r.on_click);
			$wrap.append($row);
		}
	};

	d.fields_dict.search.$input.on("input", (e) => render(e.target.value));
	render("");
	d.show();
};

// --- Menu injection ---------------------------------------------------------

// Forms: the global event fires on every form refresh with the frm. `add_menu_item`
// dedupes by label, so re-adding on each refresh is safe.
$(document).on("form-refresh", (e, frm) => {
	if (!stc_can_use() || !frm || frm.is_new()) return;
	frm.page.add_menu_item(__("Send to chat"), () => erpnext.send_to_chat.open(stc_desk_url()), false);
	// Open (or create) the single canonical chat about this record.
	frm.page.add_menu_item(
		__("Chat about this document"),
		() => erpnext.send_to_chat.open_document(frm.doctype, frm.docname),
		false
	);
});

// Open the Employee Chat page focused on this record's thread (creating it on first use).
erpnext.send_to_chat.open_document = async function (doctype, name) {
	if (!stc_can_use()) {
		frappe.msgprint(__("You do not have access to Employee Chat"));
		return;
	}
	frappe.dom.freeze(__("Opening chat…"));
	try {
		const res = await frappe.xcall(STC_API + ".open_document_thread", {
			reference_doctype: doctype,
			reference_name: name,
		});
		window.location.href = "/app/employee-chat?thread=" + encodeURIComponent(res.name);
	} catch (e) {
		frappe.msgprint(__("Failed to open chat"));
	} finally {
		frappe.dom.unfreeze();
	}
};

// Reports / lists: no per-view refresh event, so hook route changes and find the page
// object of whichever view just rendered.
function stc_inject_view_menu() {
	if (!stc_can_use()) return;
	const route = frappe.get_route();
	if (!route || !route.length) return;
	const view = route[0];
	let page = null;
	if (view === "query-report" && frappe.query_report) page = frappe.query_report.page;
	else if ((view === "List" || view === "report") && window.cur_list) page = cur_list.page;
	if (!page || !page.add_menu_item) return;
	page.add_menu_item(__("Send to chat"), () => erpnext.send_to_chat.open(stc_desk_url()), false);
}

frappe.router.on("change", () => {
	// The view is built slightly after the route resolves; retry briefly.
	let tries = 0;
	const iv = setInterval(() => {
		stc_inject_view_menu();
		if (++tries >= 5) clearInterval(iv);
	}, 250);
});
