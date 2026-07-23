// Notification sound for the chat pages and the floating chat bubble.
//
// Two independent switches: a device-level on/off (this browser, kept in
// localStorage — audio is a property of where you sit, not of your account) and a
// per-conversation mute stored server-side, so muting a noisy group follows the user
// to every device. Both must allow it for a sound to play.

frappe.provide("erpnext.chat_sound");

const SOUND_KEY = "erpnext_chat_sound_enabled";
const SOUND_NAME = "chime";
// Bursts of messages must not turn into a machine-gun of chimes.
const MIN_GAP_MS = 3000;

let last_played = 0;

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
	},

	// `muted` is the per-conversation flag; pass it straight from the chat row.
	play(muted) {
		if (muted || !this.enabled()) return;
		const now = Date.now();
		if (now - last_played < MIN_GAP_MS) return;
		last_played = now;
		try {
			frappe.utils.play_sound(SOUND_NAME);
		} catch (e) {
			// no audio device / autoplay blocked until the user interacts with the page
		}
	},

	// Shared 🔔 / 🔕 toggle markup for a chat header.
	button_html(muted, cls) {
		return `<span class="chat-mute-btn ${cls || ""}" title="${
			muted ? __("Unmute chat") : __("Mute chat")
		}">${muted ? "🔕" : "🔔"}</span>`;
	},

	inject_styles() {
		if (document.getElementById("chat-sound-styles")) return;
		const css = `
		.chat-mute-btn{cursor:pointer;margin-left:8px;font-size:14px;opacity:.75;}
		.chat-mute-btn:hover{opacity:1;}
		`;
		$(`<style id="chat-sound-styles">${css}</style>`).appendTo(document.head);
	},
};
