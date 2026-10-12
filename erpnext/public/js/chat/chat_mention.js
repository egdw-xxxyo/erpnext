// "@" mentions for a chat composer: type "@" and a few letters, pick a person, and the
// message carries a link to them. The text stays readable ("@Jane Doe"); the link travels
// beside it as an entity {offset, length, doctype, name} — the same shape any other document
// link in a message uses (see erpnext.chat_render.rich).
//
//   const mention = erpnext.chat_mention.attach($textarea, {enabled: () => bool, thread: () => id});
//   $textarea.on("keydown", (e) => { if (mention.handle_key(e)) return; ... });
//   const entities = mention.take(text);   // on send, with the final text

frappe.provide("erpnext.chat_mention");

(function (M) {
	const SEARCH = "erpnext.crm.page.employee_chat.employee_chat.search_mentions";
	// "@" at the start or after whitespace, then the query up to the caret.
	const TRIGGER = /(^|\s)@([^\s@]{0,40})$/;
	const WORD = /[\p{L}\p{N}_]/u;

	class Mention {
		constructor($input, opts) {
			this.$input = $input;
			this.opts = opts || {};
			this.picked = [];
			this.items = [];
			this.index = 0;
			this.seq = 0;
			this.$menu = null;
			this.search = frappe.utils.debounce((query, seq) => this.fetch(query, seq), 120);
			$input.on("input click", () => this.update());
			$input.on("blur", () => setTimeout(() => this.close(), 150));
		}

		is_open() {
			return !!this.$menu;
		}

		// The "@query" being typed right before the caret, if any.
		current() {
			const el = this.$input.get(0);
			if (!el || el.selectionStart !== el.selectionEnd) return null;
			const caret = el.selectionStart;
			const m = TRIGGER.exec(el.value.slice(0, caret));
			return m ? { query: m[2], start: caret - m[2].length - 1, caret } : null;
		}

		update() {
			const cur = this.opts.enabled && !this.opts.enabled() ? null : this.current();
			if (!cur) return this.close();
			this.search(cur.query, ++this.seq);
		}

		async fetch(query, seq) {
			let rows = [];
			try {
				rows = await frappe.xcall(SEARCH, {
					txt: query,
					thread: (this.opts.thread && this.opts.thread()) || null,
				});
			} catch (e) {
				rows = [];
			}
			// A newer keystroke (or a pick) made this answer stale.
			if (seq !== this.seq || !this.current()) return;
			this.items = rows || [];
			this.index = 0;
			if (!this.items.length) return this.close(true);
			this.render();
		}

		render() {
			M.inject_styles();
			if (!this.$menu) {
				this.$menu = $('<div class="cm-menu"></div>').appendTo(document.body);
				this.$menu.on("mousedown", ".cm-item", (e) => {
					// Keep the focus in the composer.
					e.preventDefault();
					this.pick(this.items[$(e.currentTarget).data("i")]);
				});
			}
			this.$menu.html(
				this.items
					.map(
						(r, i) =>
							`<div class="cm-item${
								i === this.index ? " active" : ""
							}" data-i="${i}">${erpnext.entity.html(
								{ name: r.label, sub: r.sub, image: r.image, key: r.user },
								{ size: 26 }
							)}</div>`
					)
					.join("")
			);
			const rect = this.$input.get(0).getBoundingClientRect();
			this.$menu.css({
				left: Math.max(8, rect.left),
				bottom: window.innerHeight - rect.top + 4,
				width: Math.max(220, Math.min(rect.width, 340)),
			});
		}

		close(keep_seq) {
			if (!keep_seq) this.seq++;
			if (this.$menu) this.$menu.remove();
			this.$menu = null;
			this.items = [];
		}

		// Composer keydown hook: true when the key belonged to the open menu.
		handle_key(e) {
			if (!this.is_open()) return false;
			if (e.key === "ArrowDown" || e.key === "ArrowUp") {
				const n = this.items.length;
				this.index = (this.index + (e.key === "ArrowDown" ? 1 : n - 1)) % n;
				this.render();
			} else if (e.key === "Enter" || e.key === "Tab") {
				this.pick(this.items[this.index]);
			} else if (e.key === "Escape") {
				this.close();
			} else {
				return false;
			}
			e.preventDefault();
			e.stopPropagation();
			return true;
		}

		pick(item) {
			const cur = this.current();
			this.close();
			if (!item || !cur) return;
			const el = this.$input.get(0);
			const insert = `@${item.label} `;
			el.value = el.value.slice(0, cur.start) + insert + el.value.slice(cur.caret);
			el.selectionStart = el.selectionEnd = cur.start + insert.length;
			if (!this.picked.some((p) => p.doctype === item.doctype && p.name === item.name)) {
				this.picked.push({ label: item.label, doctype: item.doctype, name: item.name });
			}
			this.$input.trigger("input").trigger("focus");
		}

		// Entities for the text being sent: every "@Label" of a picked person still standing in
		// it. Located in the final text, so editing around a mention (or deleting it) is safe.
		take(text) {
			const src = String(text || "");
			const picked = this.picked.slice().sort((a, b) => b.label.length - a.label.length);
			this.picked = [];
			this.close();
			const out = [];
			for (const p of picked) {
				const token = `@${p.label}`;
				let from = 0;
				for (;;) {
					const at = src.indexOf(token, from);
					if (at < 0) break;
					from = at + token.length;
					const next = src.charAt(from);
					if (next && WORD.test(next)) continue;
					if (out.some((e) => at < e.offset + e.length && e.offset < from)) continue;
					out.push({ offset: at, length: token.length, doctype: p.doctype, name: p.name });
				}
			}
			return out.sort((a, b) => a.offset - b.offset);
		}
	}

	M.attach = function ($input, opts) {
		return new Mention($input, opts);
	};

	// Mentions need a source that stores entities, and a body the server can read.
	M.allowed = function (source, chat) {
		return !!(source && source.mentions && chat && !chat.is_secret && !chat.read_only);
	};

	M.inject_styles = function () {
		if (document.getElementById("cm-styles-v1")) return;
		$(`<style id="cm-styles-v1">
			.cm-menu{position:fixed;z-index:1060;max-height:260px;overflow-y:auto;padding:4px;
				background:var(--card-bg);border:1px solid var(--border-color);
				border-radius:var(--border-radius-md);box-shadow:0 6px 20px rgba(0,0,0,.22);}
			.cm-item{padding:5px 8px;border-radius:6px;cursor:pointer;font-size:var(--text-sm);}
			.cm-item.active,.cm-item:hover{background:var(--bg-light-gray);}
			.cm-item .ent{display:flex;}
		</style>`).appendTo(document.head);
	};
})(erpnext.chat_mention);
