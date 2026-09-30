// Notification sound + browser notification for the chat pages and the floating chat bubble.
//
// Two independent switches: a device-level on/off (this browser, kept in
// localStorage — audio is a property of where you sit, not of your account) and a
// per-conversation mute stored server-side, so muting a noisy group follows the user
// to every device. Both must allow it for a sound to play.
//
// The chime is played from our own <audio>, not frappe.utils.play_sound: that helper
// silently returns when the user has "Mute Sounds" ticked in their User settings, which
// is meant for the desk click/submit sounds and made chat notifications disappear.

frappe.provide("erpnext.chat_sound");

const SOUND_KEY = "erpnext_chat_sound_enabled";
const SOUND_URL = "/assets/frappe/sounds/chime.mp3";
// Bursts of messages must not turn into a machine-gun of chimes.
const MIN_GAP_MS = 3000;

let last_played = 0;
let audio = null;
let unlocked = false;
let title_timer = null;
let base_title = null;
let unseen = 0;

function get_audio() {
	if (!audio) {
		audio = new Audio(SOUND_URL);
		audio.preload = "auto";
		audio.volume = 0.6;
	}
	return audio;
}

// Browsers block audio until the page got a user gesture. Prime the element on the first
// click/key so a message arriving later can actually be heard, and ask for the desktop
// notification permission at the same moment (Chrome wants a gesture for the prompt).
function unlock_on_gesture() {
	const handler = () => {
		document.removeEventListener("pointerdown", handler, true);
		document.removeEventListener("keydown", handler, true);
		if (unlocked) return;
		unlocked = true;
		const a = get_audio();
		a.muted = true;
		a.play()
			.then(() => {
				a.pause();
				a.currentTime = 0;
				a.muted = false;
			})
			.catch(() => {
				a.muted = false;
			});
		erpnext.chat_sound.request_permission();
	};
	document.addEventListener("pointerdown", handler, true);
	document.addEventListener("keydown", handler, true);
}

// "(3) New message" in the tab title while the tab is in the background. Works on plain
// HTTP where desktop notifications are unavailable.
function flash_title(text) {
	if (!document.hidden) return;
	if (base_title === null) base_title = document.title;
	unseen += 1;
	clearInterval(title_timer);
	let on = true;
	const tick = () => {
		document.title = on ? `(${unseen}) ${text}` : base_title;
		on = !on;
	};
	tick();
	title_timer = setInterval(tick, 1200);
}

function stop_flash() {
	if (document.hidden) return;
	clearInterval(title_timer);
	title_timer = null;
	unseen = 0;
	if (base_title !== null) {
		document.title = base_title;
		base_title = null;
	}
}

document.addEventListener("visibilitychange", stop_flash);
window.addEventListener("focus", stop_flash);
unlock_on_gesture();

erpnext.chat_sound = {
	enabled() {
		try {
			return localStorage.getItem(SOUND_KEY) !== "0";
		} catch (e) {
			return true;
		}
	},

	set_enabled(on) {
		try {
			localStorage.setItem(SOUND_KEY, on ? "1" : "0");
		} catch (e) {
			// storage disabled — the setting simply does not stick
		}
		if (on) this.request_permission();
	},

	// Desktop notifications exist only in a secure context (HTTPS or localhost).
	notifications_supported() {
		return "Notification" in window && window.isSecureContext;
	},

	request_permission() {
		if (!this.notifications_supported() || Notification.permission !== "default") return;
		try {
			Notification.requestPermission();
		} catch (e) {
			// older Safari: callback-only API, ignore
		}
	},

	// `muted` is the per-conversation flag; pass it straight from the chat row.
	// `info` = {title, body, tag, route} describes the message for the desktop notification.
	play(muted, info) {
		if (muted) return;
		if (info) this.notify(info);
		if (!this.enabled()) return;
		const now = Date.now();
		if (now - last_played < MIN_GAP_MS) return;
		last_played = now;
		const a = get_audio();
		try {
			a.currentTime = 0;
			const p = a.play();
			if (p && p.catch) {
				p.catch((e) => console.warn("[chat] notification sound blocked by the browser", e && e.name));
			}
		} catch (e) {
			console.warn("[chat] notification sound failed", e);
		}
	},

	// Only when the user is not looking at the page — otherwise the chat itself is the signal.
	notify(info) {
		if (!document.hidden && document.hasFocus()) return;
		flash_title(info.title || __("New message"));
		if (!this.enabled() || !this.notifications_supported()) return;
		if (Notification.permission !== "granted") return;
		try {
			const n = new Notification(info.title || __("New message"), {
				body: info.body || __("New message"),
				tag: info.tag,
				icon: "/assets/erpnext/images/erpnext-logo.svg",
			});
			n.onclick = () => {
				window.focus();
				if (info.route) window.location.assign(`/app/${info.route}`);
				n.close();
			};
		} catch (e) {
			// Notification constructor is unavailable on some mobile browsers
		}
	},

	// Plain-text notification body for a message (no HTML, secret messages stay hidden).
	message_body(content_type, text, is_encrypted) {
		if (is_encrypted) return __("Encrypted message");
		const media = {
			image: __("Photo"),
			video: __("Video"),
			audio: __("Audio"),
			document: __("Document"),
			file: __("File"),
			sticker: __("Sticker"),
			link: __("Link"),
		}[content_type];
		const plain = (text || "")
			.replace(/<[^>]*>/g, "")
			.trim()
			.slice(0, 120);
		if (media) return plain ? `${media}: ${plain}` : media;
		return plain || __("New message");
	},

	// Shared bell / bell-slash toggle markup for a chat header.
	button_html(muted, cls) {
		return `<span class="chat-mute-btn ${cls || ""}" title="${
			muted
				? __("Play the notification sound for this chat again.")
				: __("Silence the notification sound for this chat on all your devices.")
		}"><i class="fa fa-bell${muted ? "-slash-o" : "-o"}"></i></span>`;
	},

	inject_styles() {
		if (document.getElementById("chat-sound-styles-v2")) return;
		const css = `
		.chat-mute-btn{cursor:pointer;margin-left:8px;font-size:15px;color:var(--text-muted);display:inline-flex;
			align-items:center;justify-content:center;width:30px;height:30px;border-radius:50%;}
		.chat-mute-btn:hover{color:var(--text-color);background:var(--bg-light-gray);}
		`;
		$(`<style id="chat-sound-styles-v2">${css}</style>`).appendTo(document.head);
	},
};
