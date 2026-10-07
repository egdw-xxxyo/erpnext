// The one way to show "who / what" in our custom UI: picture + name (+ a second line),
// optionally a link to where that thing lives. People, WhatsApp business numbers,
// customers, chats… all render through erpnext.entity so they look the same on every
// page — no bare names in one place and avatars in another.
//
//   erpnext.entity.html({name, sub, image, icon, key, route, href, title, size, class})
//   erpnext.entity.user("jane@x.com" | {user, full_name, user_image}, opts)
//   erpnext.entity.number({name, verified_name, account_name, display_phone_number,
//                          profile_image}, opts)          // WhatsApp business number
//   erpnext.entity.wa_person({phone, name, image}, opts)  // customer → WhatsApp person page
//   erpnext.entity.list(items, renderer, opts)            // several, wrapped, or "—"
//   erpnext.entity.avatar_html({name, key, image, icon}, size)
//
// `route` is a frappe route array (["Form", "User", name]) turned into a real desk link
// that the router handles (and that opens in a new tab on ctrl/cmd-click). A clickable
// row around a chip should ignore clicks that land inside `a.ent-link`.

frappe.provide("erpnext.entity");

(function (E) {
	const esc = (v) => frappe.utils.escape_html(v === null || v === undefined ? "" : String(v));

	E.initials = function (name) {
		const parts = String(name || "?")
			.replace(/[^\p{L}\p{N} ]/gu, "")
			.trim()
			.split(/\s+/)
			.filter(Boolean);
		if (!parts.length) return "#";
		return ((parts[0][0] || "") + (parts.length > 1 ? parts[1][0] : "")).toUpperCase();
	};

	// Stable colour per key, so the same person or chat keeps its avatar colour.
	E.avatar_color = function (key) {
		const palette = [
			"#e17076",
			"#7bc862",
			"#e5ca77",
			"#65aadd",
			"#a695e7",
			"#ee7aae",
			"#6ec9cb",
			"#faa774",
		];
		let h = 0;
		for (const ch of String(key || "")) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
		return palette[h % palette.length];
	};

	E.avatar_html = function (a, size) {
		E.inject_styles();
		a = a || {};
		const dim = size
			? `width:${size}px;height:${size}px;line-height:${size}px;font-size:${Math.round(size / 2.9)}px;`
			: "";
		if (a.image) {
			return `<span class="cv-avatar ent-avatar" style="${dim}"><img src="${esc(
				a.image
			)}" alt=""></span>`;
		}
		const inner = a.icon ? `<i class="${esc(a.icon)}"></i>` : esc(E.initials(a.name));
		return `<span class="cv-avatar ent-avatar" style="background:${E.avatar_color(
			a.key || a.name
		)};${dim}">${inner}</span>`;
	};

	E.url = function (route) {
		return frappe.router.make_url(route.map((p) => String(p)));
	};

	E.html = function (e, opts) {
		E.inject_styles();
		e = Object.assign({}, e, opts);
		const size = e.size || 24;
		const href = e.href || (e.route ? E.url(e.route) : null);
		const tag = href ? "a" : "span";
		const attrs = [
			`class="ent${href ? " ent-link" : ""}${e.class ? " " + e.class : ""}"`,
			href ? `href="${esc(href)}"` : "",
			`title="${esc(e.title || [e.name, e.sub].filter(Boolean).join(" · "))}"`,
		].join(" ");
		const sub = e.sub ? `<span class="ent-sub">${esc(e.sub)}</span>` : "";
		return `<${tag} ${attrs}>${E.avatar_html(e, size)}<span class="ent-text"><span class="ent-name">${esc(
			e.name
		)}</span>${sub}</span></${tag}>`;
	};

	// A desk user. Accepts an id or {user, full_name, user_image}; fills gaps from boot.
	E.user = function (u, opts) {
		if (!u) return "";
		const id = typeof u === "string" ? u : u.user || u.name;
		const info = (frappe.user_info && frappe.user_info(id)) || {};
		const name = (typeof u === "object" && (u.full_name || u.fullname)) || info.fullname || id;
		return E.html(
			{
				name,
				key: id,
				image: (typeof u === "object" && u.user_image) || info.image,
				route: ["Form", "User", id],
			},
			opts
		);
	};

	// A WhatsApp business number: photo, verified name, display number. Managers get a
	// link to its card in the WhatsApp Overview.
	E.number = function (n, opts) {
		if (!n) return "";
		const name = n.verified_name || n.account_name || n.name;
		return E.html(
			{
				name,
				sub: n.display_phone_number || n.label || "",
				key: n.name,
				image: n.profile_image,
				icon: n.profile_image ? null : "fa fa-whatsapp",
				route: frappe.boot.whatsapp_manager ? ["whatsapp-overview", "number", n.name] : null,
			},
			opts
		);
	};

	// A customer behind a WhatsApp number: {phone, name, image} → their person page.
	E.wa_person = function (p, opts) {
		if (!p || !p.phone) return "";
		return E.html(
			{
				name: p.name || `+${p.phone}`,
				sub: p.name ? `+${p.phone}` : "",
				key: p.phone,
				image: p.image,
				route: ["whatsapp-person", p.phone],
			},
			opts
		);
	};

	E.list = function (items, render, opts) {
		if (!items || !items.length) return `<span class="text-muted">—</span>`;
		return `<span class="ent-list">${items.map((i) => render(i, opts)).join("")}</span>`;
	};

	E.inject_styles = function () {
		if (document.getElementById("ent-styles-v1")) return;
		$(`<style id="ent-styles-v1">
			.ent-avatar{display:inline-block;flex:none;border-radius:50%;color:#fff;font-weight:600;
				text-align:center;overflow:hidden;user-select:none;vertical-align:middle;}
			.ent-avatar img{width:100%;height:100%;object-fit:cover;display:block;}
			.ent{display:inline-flex;align-items:center;gap:8px;min-width:0;max-width:100%;vertical-align:middle;
				color:inherit;text-decoration:none;}
			.ent-text{display:flex;flex-direction:column;min-width:0;line-height:1.25;}
			.ent-name,.ent-sub{overflow:hidden;white-space:nowrap;text-overflow:ellipsis;}
			.ent-sub{font-size:0.85em;color:var(--text-muted);font-weight:400;}
			.ent-link:hover{text-decoration:none;}
			.ent-link:hover .ent-name{text-decoration:underline;}
			.ent-list{display:inline-flex;flex-wrap:wrap;gap:6px 14px;vertical-align:middle;}
		</style>`).appendTo(document.head);
	};
})(erpnext.entity);
