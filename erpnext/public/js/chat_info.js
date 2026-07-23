// Shared chat overview dialog for the chat pages (WhatsApp Chat Center + Employee Chat).
//
// Both pages open it from the thread header: it shows who the conversation is with and
// everything shared in it — media, files and links. The pages fetch and shape the data
// (they differ in storage and, for secret chats, in decryption); this module only
// renders it and wires the media lazy-loader.

frappe.provide("erpnext.chat_info");

function esc(v) {
	return frappe.utils.escape_html(v == null ? "" : String(v));
}

function human_size(bytes) {
	if (!bytes && bytes !== 0) return "";
	const units = ["B", "KB", "MB", "GB"];
	let i = 0;
	let n = bytes;
	while (n >= 1024 && i < units.length - 1) {
		n /= 1024;
		i++;
	}
	return `${n < 10 && i ? n.toFixed(1) : Math.round(n)} ${units[i]}`;
}

function when(creation) {
	if (!creation) return "";
	return frappe.datetime.str_to_user(creation);
}

erpnext.chat_info = {
	human_size,

	inject_styles() {
		if (document.getElementById("chat-info-styles-v1")) return;
		const css = `
		.ci-head{display:flex;align-items:center;gap:12px;margin-bottom:12px;}
		.ci-head-avatar{flex:none;width:52px;height:52px;border-radius:50%;background:var(--bg-light-gray);display:flex;align-items:center;justify-content:center;font-weight:600;color:var(--text-muted);overflow:hidden;font-size:18px;}
		.ci-head-avatar img{width:100%;height:100%;object-fit:cover;}
		.ci-head-main{min-width:0;flex:1;}
		.ci-title{font-weight:600;font-size:var(--text-lg);word-break:break-word;}
		.ci-subtitle{color:var(--text-muted);font-size:var(--text-sm);}
		.ci-tabs{display:flex;gap:4px;border-bottom:1px solid var(--border-color);margin-bottom:10px;flex-wrap:wrap;}
		.ci-tab{cursor:pointer;padding:6px 10px;font-size:var(--text-sm);border-bottom:2px solid transparent;color:var(--text-muted);}
		.ci-tab.active{color:var(--text-color);border-bottom-color:var(--primary);font-weight:600;}
		.ci-tab .ci-count{opacity:.6;margin-left:4px;}
		.ci-pane{max-height:46vh;overflow-y:auto;}
		.ci-row{display:flex;align-items:center;gap:10px;padding:6px 4px;border-bottom:1px solid var(--border-color);}
		.ci-row:last-child{border-bottom:none;}
		.ci-row-main{flex:1;min-width:0;}
		.ci-row-title{font-size:var(--text-md);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
		.ci-row-sub{color:var(--text-muted);font-size:var(--text-sm);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
		.ci-row-action{cursor:pointer;color:var(--text-muted);}
		.ci-row-action:hover{color:var(--primary);}
		.ci-avatar{flex:none;width:30px;height:30px;border-radius:50%;background:var(--bg-light-gray);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;color:var(--text-muted);overflow:hidden;}
		.ci-avatar img{width:100%;height:100%;object-fit:cover;}
		.ci-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:6px;}
		.ci-media{position:relative;aspect-ratio:1/1;border-radius:6px;overflow:hidden;background:var(--bg-light-gray);}
		.ci-media .chat-img,.ci-media .chat-img img{width:100%;height:100%;max-width:none;object-fit:cover;}
		.ci-media-fallback{display:flex;width:100%;height:100%;align-items:center;justify-content:center;font-size:22px;cursor:pointer;}
		.ci-empty{color:var(--text-muted);font-size:var(--text-sm);padding:14px 4px;text-align:center;}
		.ci-file-icon{flex:none;font-size:18px;}
		.ci-section-label{font-size:var(--text-sm);text-transform:uppercase;color:var(--text-muted);letter-spacing:.04em;margin:12px 0 4px;}
		`;
		$(`<style id="chat-info-styles-v1">${css}</style>`).appendTo(document.head);
	},

	// data: {title, subtitle, avatar, avatar_text, source, people:[], media:[], files:[],
	//        links:[], sections:[{label, items:[{title, subtitle, on_click}]}],
	//        actions:[{label, on_click}], note}
	show(data) {
		this.inject_styles();
		const d = new frappe.ui.Dialog({
			title: __("Chat info"),
			size: "large",
		});
		this.render(d.$body, data);
		d.show();
		return d;
	},

	render($body, data) {
		const people = data.people || [];
		const media = data.media || [];
		const files = data.files || [];
		const links = data.links || [];

		const avatar = data.avatar
			? `<img src="${esc(data.avatar)}">`
			: esc((data.avatar_text || data.title || "?").trim().charAt(0).toUpperCase());

		$body.empty().append(`
			<div class="ci-head">
				<div class="ci-head-avatar">${avatar}</div>
				<div class="ci-head-main">
					<div class="ci-title"></div>
					<div class="ci-subtitle"></div>
				</div>
			</div>
			<div class="ci-actions"></div>
			<div class="ci-tabs"></div>
			<div class="ci-pane"></div>
		`);
		$body.find(".ci-title").text(data.title || __("Chat"));
		$body.find(".ci-subtitle").text(data.subtitle || "");

		const $actions = $body.find(".ci-actions");
		for (const a of data.actions || []) {
			$(`<button class="btn btn-xs btn-default" style="margin:0 6px 8px 0;"></button>`)
				.text(a.label)
				.on("click", () => a.on_click())
				.appendTo($actions);
		}

		const tabs = [
			{ key: "people", label: __("Participants"), count: people.length },
			{ key: "media", label: __("Media"), count: media.length },
			{ key: "files", label: __("Files"), count: files.length },
			{ key: "links", label: __("Links"), count: links.length },
		];
		if (data.sections && data.sections.length) {
			tabs.push({ key: "linked", label: __("Linked"), count: null });
		}

		const $tabs = $body.find(".ci-tabs");
		const $pane = $body.find(".ci-pane");
		const draw = (key) => {
			$tabs.find(".ci-tab").removeClass("active");
			$tabs.find(`.ci-tab[data-key="${key}"]`).addClass("active");
			$pane.empty();
			if (key === "people") this.render_people($pane, people, data);
			else if (key === "media") this.render_media($pane, media, data);
			else if (key === "files") this.render_files($pane, files, data);
			else if (key === "links") this.render_links($pane, links);
			else this.render_sections($pane, data.sections || []);
		};

		for (const t of tabs) {
			$(
				`<div class="ci-tab" data-key="${t.key}">${esc(t.label)}${
					t.count == null ? "" : `<span class="ci-count">${t.count}</span>`
				}</div>`
			)
				.on("click", () => draw(t.key))
				.appendTo($tabs);
		}
		draw(data.default_tab || "people");
	},

	render_people($pane, people, data) {
		if (!people.length) return $pane.append(`<div class="ci-empty">${__("No participants")}</div>`);
		for (const p of people) {
			const av = p.image
				? `<img src="${esc(p.image)}">`
				: esc((p.name || p.user || "?").trim().charAt(0).toUpperCase());
			const $row = $(`
				<div class="ci-row">
					<div class="ci-avatar">${av}</div>
					<div class="ci-row-main">
						<div class="ci-row-title"></div>
						<div class="ci-row-sub"></div>
					</div>
					<div class="ci-row-action" style="display:none;">&times;</div>
				</div>
			`);
			$row.find(".ci-row-title").text(p.name + (p.is_me ? ` (${__("you")})` : ""));
			$row.find(".ci-row-sub").text(p.subtitle || p.user || "");
			if (p.on_remove) {
				$row.find(".ci-row-action")
					.show()
					.attr("title", __("Remove"))
					.on("click", () => p.on_remove());
			}
			$pane.append($row);
		}
		if (data && data.on_add_person) {
			$(`<button class="btn btn-xs btn-default" style="margin-top:8px;">+ ${__("Add people")}</button>`)
				.on("click", () => data.on_add_person())
				.appendTo($pane);
		}
	},

	render_media($pane, media, data) {
		if (!media.length) return $pane.append(`<div class="ci-empty">${__("No media yet")}</div>`);
		const $grid = $('<div class="ci-grid"></div>').appendTo($pane);
		for (const m of media) {
			const $cell = $(`<div class="ci-media">${m.html || ""}</div>`);
			if (!m.html) {
				$cell.html(`<div class="ci-media-fallback">${m.icon || "📄"}</div>`);
			}
			if (m.on_click) $cell.on("click", () => m.on_click());
			$cell.attr("title", [m.sender_name, when(m.creation), m.caption].filter(Boolean).join(" · "));
			$grid.append($cell);
		}
		if (data && data.source) erpnext.chat_media.bind($pane, data.source);
	},

	render_files($pane, files) {
		if (!files.length) return $pane.append(`<div class="ci-empty">${__("No files yet")}</div>`);
		for (const f of files) {
			const $row = $(`
				<div class="ci-row">
					<div class="ci-file-icon">📎</div>
					<div class="ci-row-main">
						<div class="ci-row-title"></div>
						<div class="ci-row-sub"></div>
					</div>
				</div>
			`);
			$row.find(".ci-row-title").text(f.file_name || __("File"));
			$row.find(".ci-row-sub").text(
				[f.sender_name, when(f.creation), human_size(f.file_size)].filter(Boolean).join(" · ")
			);
			$row.css("cursor", "pointer").on("click", () => {
				if (f.on_click) return f.on_click();
				if (f.url) window.open(f.url, "_blank");
			});
			$pane.append($row);
		}
	},

	render_links($pane, links) {
		if (!links.length) return $pane.append(`<div class="ci-empty">${__("No links yet")}</div>`);
		for (const l of links) {
			const $row = $(`
				<div class="ci-row">
					<div class="ci-file-icon">🔗</div>
					<div class="ci-row-main">
						<div class="ci-row-title"><a target="_blank" rel="noopener"></a></div>
						<div class="ci-row-sub"></div>
					</div>
				</div>
			`);
			$row.find("a").attr("href", l.url).text(l.url);
			$row.find(".ci-row-sub").text(
				[l.sender_name, when(l.creation)].filter(Boolean).join(" · ")
			);
			$pane.append($row);
		}
	},

	render_sections($pane, sections) {
		let any = false;
		for (const s of sections) {
			if (!s.items || !s.items.length) continue;
			any = true;
			$(`<div class="ci-section-label"></div>`).text(s.label).appendTo($pane);
			for (const it of s.items) {
				const $row = $(`
					<div class="ci-row">
						<div class="ci-row-main">
							<div class="ci-row-title"></div>
							<div class="ci-row-sub"></div>
						</div>
					</div>
				`);
				$row.find(".ci-row-title").text(it.title);
				$row.find(".ci-row-sub").text(it.subtitle || "");
				if (it.on_click) $row.css("cursor", "pointer").on("click", () => it.on_click());
				$pane.append($row);
			}
		}
		if (!any) $pane.append(`<div class="ci-empty">${__("Nothing linked yet")}</div>`);
	},
};
