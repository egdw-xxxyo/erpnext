// Shared image handling for the chat pages (WhatsApp Chat Center + Employee Chat).
//
// Bubbles render an empty placeholder; the downscaled preview is requested from
// the server only once the bubble scrolls into view, in batches. Clicking a
// preview opens an in-page lightbox that shows the preview instantly and can
// swap to the full-resolution original on demand.

frappe.provide("erpnext.chat_media");

// Mirrors THUMB_MAX_PX / THUMB_MIN_BYTES in erpnext/crm/chat_media.py, for the previews
// the browser has to build itself (encrypted attachments).
const THUMB_MAX_PX = 640;
const THUMB_MIN_BYTES = 80 * 1024;

const THUMB_CACHE = {}; // original file_url -> preview file_url
const ENC_REGISTRY = {}; // placeholder id -> encrypted attachment descriptor
const OBJECT_URLS = {}; // placeholder id -> blob: URL, revoked when the page unloads
let ENC_SEQ = 0;

// Extensions the uploader reports in File.file_type (it is an extension, e.g.
// "JPEG", not a MIME type — hence the two-way mapping below).
const EXT_CONTENT_TYPES = {
	image: ["jpg", "jpeg", "png", "webp", "gif", "bmp", "tiff", "heic", "heif"],
	video: ["mp4", "3gp", "mov", "mkv", "avi", "webm"],
	audio: ["aac", "amr", "mp3", "m4a", "ogg", "oga", "opus", "wav"],
};

erpnext.chat_media = {
	// Map whatever the file picker reports (MIME type or bare extension) to a
	// content type: image / video / audio / document.
	detect_type(type, file_name) {
		const t = (type || "").toLowerCase();
		if (t.startsWith("image/")) return "image";
		if (t.startsWith("video/")) return "video";
		if (t.startsWith("audio/")) return "audio";

		const ext = (t.includes("/") ? "" : t) || (file_name || "").split(".").pop().toLowerCase();
		for (const [content_type, exts] of Object.entries(EXT_CONTENT_TYPES)) {
			if (exts.includes(ext)) return content_type;
		}
		return "document";
	},

	// Markup for an image inside a chat bubble. `cls` lets callers add a modifier
	// (e.g. a sticker size) on top of the shared classes.
	image_html(url, cls) {
		const safe = frappe.utils.escape_html(url);
		return `<div class="chat-img ${cls || ""}">
			<img class="chat-img-el" data-chat-src="${safe}" data-full="${safe}" alt="${__("Image")}">
			<div class="chat-img-spinner"></div>
		</div>`;
	},

	// Markup for an encrypted image. The file keys stay in a JS registry rather than in
	// DOM attributes — a stray `outerHTML` in a log or a screenshot must not carry them.
	// `meta` is the decrypted attachment descriptor: {url, key, iv, thumb_url, thumb_key,
	// thumb_iv, mime, file_name}.
	encrypted_image_html(meta, cls) {
		const id = "e" + ENC_SEQ++;
		ENC_REGISTRY[id] = meta;
		return `<div class="chat-img ${cls || ""}">
			<img class="chat-img-el" data-chat-enc="${id}" alt="${__("Image")}">
			<div class="chat-img-spinner"></div>
		</div>`;
	},

	// Fetch an encrypted attachment and turn it back into a Blob. Used for previews,
	// the lightbox, and downloads alike.
	async fetch_encrypted(url, key, iv, mime) {
		const res = await fetch(url, { credentials: "same-origin" });
		if (!res.ok) throw new Error("fetch-failed");
		return erpnext.chat_crypto.decrypt_blob(await res.arrayBuffer(), key, iv, mime);
	},

	// Downscaled copy of an image, made in the browser. For secret chats the server
	// cannot generate previews (it only ever sees ciphertext), so the sender does it.
	async make_preview_blob(file) {
		if (!(file.type || "").startsWith("image/")) return null;
		try {
			const bitmap = await createImageBitmap(file);
			const scale = Math.min(1, THUMB_MAX_PX / Math.max(bitmap.width, bitmap.height));
			if (scale === 1 && file.size < THUMB_MIN_BYTES) return null;
			const canvas = document.createElement("canvas");
			canvas.width = Math.round(bitmap.width * scale);
			canvas.height = Math.round(bitmap.height * scale);
			canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
			return await new Promise((resolve) =>
				canvas.toBlob(resolve, "image/jpeg", 0.8)
			);
		} catch (e) {
			return null;
		}
	},

	// Upload an already-encrypted blob as a private File. The bytes are opaque to the
	// server, so the name carries an `.enc` suffix to make that obvious on disk.
	async upload_encrypted(blob, file_name) {
		const form = new FormData();
		form.append("file", blob, (file_name || "file") + ".enc");
		form.append("is_private", 1);
		form.append("folder", "Home/Attachments");
		const res = await fetch("/api/method/upload_file", {
			method: "POST",
			headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
			credentials: "same-origin",
			body: form,
		});
		if (!res.ok) throw new Error("upload-failed");
		return (await res.json()).message.file_url;
	},

	// Attach lazy loading + lightbox handlers to every image placeholder inside
	// $container. Safe to call after each re-render.
	bind($container, source) {
		this._bind_encrypted($container);
		const els = $container.find("img[data-chat-src]").toArray();
		if (!els.length) return;

		const load = (batch) => {
			const urls = [];
			for (const el of batch) {
				const url = el.dataset.chatSrc;
				if (THUMB_CACHE[url]) {
					this._apply(el, THUMB_CACHE[url]);
				} else if (!urls.includes(url)) {
					urls.push(url);
				}
			}
			if (!urls.length) return;
			frappe
				.xcall("erpnext.crm.chat_media.get_thumbnails", {
					source,
					files: JSON.stringify(urls),
				})
				.then((map) => {
					for (const el of batch) {
						const url = el.dataset.chatSrc;
						// No preview (unknown/remote file) — fall back to the original.
						const thumb = (map || {})[url] || url;
						THUMB_CACHE[url] = thumb;
						this._apply(el, thumb);
					}
				})
				.catch(() => {
					for (const el of batch) this._apply(el, el.dataset.chatSrc);
				});
		};

		if (!window.IntersectionObserver) {
			load(els);
		} else {
			let pending = [];
			let timer = null;
			const observer = new IntersectionObserver(
				(entries) => {
					for (const entry of entries) {
						if (!entry.isIntersecting) continue;
						observer.unobserve(entry.target);
						pending.push(entry.target);
					}
					if (!pending.length) return;
					// Coalesce everything that became visible in the same scroll
					// tick into a single request.
					clearTimeout(timer);
					timer = setTimeout(() => {
						const batch = pending;
						pending = [];
						load(batch);
					}, 60);
				},
				{ root: $container[0], rootMargin: "300px 0px" }
			);
			for (const el of els) observer.observe(el);
			// Replaced on the next render — drop the old observer with the DOM.
			$container.data("chat-img-observer", observer);
		}

		$container.find(".chat-img-el[data-chat-src]")
			.off("click.chatmedia")
			.on("click.chatmedia", (e) => {
				const el = e.currentTarget;
				this.lightbox(el.dataset.full, el.getAttribute("src"));
			});
	},

	// Encrypted images take the same lazy path, but decryption happens per bubble —
	// there is nothing the server could batch for us.
	_bind_encrypted($container) {
		const els = $container.find("img[data-chat-enc]").toArray();
		if (!els.length) return;

		const load = async (el) => {
			const id = el.dataset.chatEnc;
			const meta = ENC_REGISTRY[id];
			if (!meta) return;
			if (OBJECT_URLS[id]) return this._apply(el, OBJECT_URLS[id]);
			try {
				// Prefer the small preview the sender encrypted for us; the original is
				// only fetched when the lightbox asks for it.
				const blob = await this.fetch_encrypted(
					meta.thumb_url || meta.url,
					meta.thumb_key || meta.key,
					meta.thumb_iv || meta.iv,
					meta.mime
				);
				OBJECT_URLS[id] = URL.createObjectURL(blob);
				this._apply(el, OBJECT_URLS[id]);
			} catch (e) {
				el.closest(".chat-img").innerHTML = `<div class="chat-img-failed">🔒 ${__(
					"Cannot decrypt"
				)}</div>`;
			}
		};

		if (!window.IntersectionObserver) {
			for (const el of els) load(el);
		} else {
			const observer = new IntersectionObserver(
				(entries) => {
					for (const entry of entries) {
						if (!entry.isIntersecting) continue;
						observer.unobserve(entry.target);
						load(entry.target);
					}
				},
				{ root: $container[0], rootMargin: "300px 0px" }
			);
			for (const el of els) observer.observe(el);
			$container.data("chat-enc-observer", observer);
		}

		$container.find(".chat-img-el[data-chat-enc]")
			.off("click.chatmedia")
			.on("click.chatmedia", async (e) => {
				const el = e.currentTarget;
				const meta = ENC_REGISTRY[el.dataset.chatEnc] || {};
				this.lightbox(null, el.getAttribute("src"), {
					name: meta.file_name,
					// Loading the original means one more fetch + decrypt.
					resolve_full: () =>
						this.fetch_encrypted(meta.url, meta.key, meta.iv, meta.mime).then((b) =>
							URL.createObjectURL(b)
						),
				});
			});
	},

	_apply(el, url) {
		el.setAttribute("src", url);
		el.classList.add("chat-img-loaded");
	},

	// Full-screen viewer: preview first, original on request, download always.
	// `opts.resolve_full` lets an encrypted image supply its original lazily: it returns
	// a promise of a blob: URL, produced by fetching and decrypting on demand.
	lightbox(full_url, preview_url, opts) {
		$(".chat-lightbox").remove();
		opts = opts || {};
		const src = preview_url || full_url;
		const fname =
			opts.name || decodeURIComponent((full_url || "").split("/").pop() || "image");
		// An encrypted image has no fetchable URL — the download link is wired up to the
		// decrypted blob once it exists.
		const download_href = full_url ? frappe.utils.escape_html(full_url) : "#";
		const $box = $(`
			<div class="chat-lightbox">
				<div class="chat-lightbox-bar">
					<span class="chat-lightbox-name">${frappe.utils.escape_html(fname)}</span>
					<span class="chat-lightbox-actions">
						<button class="btn btn-xs btn-default chat-lightbox-original">${__("Show original")}</button>
						<a class="btn btn-xs btn-default chat-lightbox-download" href="${download_href}" download="${frappe.utils.escape_html(
							fname
						)}" target="_blank">${__("Download")}</a>
						<button class="btn btn-xs btn-default chat-lightbox-close">&times;</button>
					</span>
				</div>
				<div class="chat-lightbox-body"><img src="${frappe.utils.escape_html(src)}"></div>
			</div>
		`);
		$("body").append($box);

		const close = () => {
			$box.remove();
			$(document).off("keydown.chatlightbox");
		};
		$box.find(".chat-lightbox-close").on("click", close);
		$box.find(".chat-lightbox-body").on("click", (e) => {
			if (e.target === e.currentTarget) close();
		});
		$(document).on("keydown.chatlightbox", (e) => {
			if (e.key === "Escape") close();
		});

		const $btn = $box.find(".chat-lightbox-original");
		if (src === full_url) {
			$btn.hide();
		}
		// Nothing to download until the original has been decrypted.
		if (!full_url) $box.find(".chat-lightbox-download").hide();
		const show_full = (url) => {
			$box.find(".chat-lightbox-body img").attr("src", url);
			$box.find(".chat-lightbox-download").attr("href", url).show();
			$btn.hide();
		};
		$btn.on("click", async () => {
			$btn.prop("disabled", true).text(__("Loading..."));
			if (opts.resolve_full) {
				try {
					show_full(await opts.resolve_full());
				} catch (e) {
					$btn.prop("disabled", false).text(__("Show original"));
				}
				return;
			}
			const img = new Image();
			img.onload = () => show_full(full_url);
			img.onerror = () => $btn.prop("disabled", false).text(__("Show original"));
			img.src = full_url;
		});
	},

	// Styles are shared by both chat pages.
	inject_styles() {
		if (document.getElementById("chat-media-styles")) return;
		const css = `
		.chat-img{position:relative;min-width:120px;min-height:90px;max-width:240px;border-radius:6px;overflow:hidden;background:var(--bg-light-gray);}
		.chat-img img{display:block;max-width:240px;max-height:280px;width:auto;height:auto;cursor:zoom-in;opacity:0;transition:opacity .15s;}
		.chat-img img.chat-img-loaded{opacity:1;}
		.chat-img.chat-img-sticker,.chat-img.chat-img-sticker img{max-width:130px;background:none;}
		.chat-img-spinner{position:absolute;inset:0;background:linear-gradient(90deg,var(--bg-light-gray) 25%,var(--bg-gray) 50%,var(--bg-light-gray) 75%);background-size:200% 100%;animation:chat-img-shimmer 1.2s infinite;}
		.chat-img img.chat-img-loaded + .chat-img-spinner,.chat-img:has(img.chat-img-loaded) .chat-img-spinner{display:none;}
		@keyframes chat-img-shimmer{0%{background-position:200% 0;}100%{background-position:-200% 0;}}
		.chat-lightbox{position:fixed;inset:0;z-index:1050;background:rgba(0,0,0,.85);display:flex;flex-direction:column;}
		.chat-lightbox-bar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:8px 12px;color:#fff;font-size:12px;}
		.chat-lightbox-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
		.chat-lightbox-actions{display:flex;gap:6px;flex:none;}
		.chat-lightbox-body{flex:1;display:flex;align-items:center;justify-content:center;overflow:auto;padding:12px;}
		.chat-lightbox-body img{max-width:100%;max-height:100%;border-radius:4px;}
		.chat-img-failed{padding:10px 12px;font-size:12px;color:var(--text-muted);}
		`;
		$(`<style id="chat-media-styles">${css}</style>`).appendTo(document.head);
	},
};

// Decrypted images live only as blob: URLs — let them go with the page.
$(window).on("beforeunload", () => {
	for (const id of Object.keys(OBJECT_URLS)) {
		URL.revokeObjectURL(OBJECT_URLS[id]);
		delete OBJECT_URLS[id];
	}
});
