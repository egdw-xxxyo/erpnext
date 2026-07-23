// End-to-end encryption for secret chats (Employee Chat + WhatsApp Chat Center).
//
// Everything secret happens here, in the browser. The server stores public keys, the
// private key *already wrapped* with a key derived from the user's passphrase, and the
// per-thread keys wrapped for each participant. It never receives a passphrase, an
// unwrapped private key, or a plaintext body — so a database dump is worthless, which is
// the whole point of the feature.
//
// Consequence to keep in mind while editing: there is no recovery path. Lose the
// passphrase and every registered device, and the history is gone for good.

frappe.provide("erpnext.chat_crypto");

const CRYPTO_API = "erpnext.crm.chat_crypto.";
const KDF_ITERATIONS = 600000;
// Must match SEAL_ALG in erpnext/crm/chat_crypto.py — it is the HKDF info string, so a
// mismatch silently produces a different key and nothing decrypts.
const WRAP_INFO = "ECDH-ES-P256-A256GCM";
const EC_PARAMS = { name: "ECDH", namedCurve: "P-256" };
const SIGN_PARAMS = { name: "ECDSA", namedCurve: "P-256" };

// Unlocked key material. Module-scoped on purpose: never localStorage, never
// sessionStorage, never on `window` — it dies with the tab.
let IDENTITY = null; // {ecdh: CryptoKeyPair-private, ecdsa: private, public_key: b64}
let MY_KEY = null; // cached Chat Encryption Key record
const THREAD_KEYS = {}; // thread -> CryptoKey (AES-GCM)
const subtle = () => window.crypto && window.crypto.subtle;

// --- encoding helpers ------------------------------------------------------

function to_b64(buf) {
	const bytes = new Uint8Array(buf);
	let s = "";
	for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
	return btoa(s);
}

function from_b64(text) {
	const s = atob(text);
	const bytes = new Uint8Array(s.length);
	for (let i = 0; i < s.length; i++) bytes[i] = s.charCodeAt(i);
	return bytes;
}

function random_bytes(n) {
	return window.crypto.getRandomValues(new Uint8Array(n));
}

// --- key derivation --------------------------------------------------------

async function derive_kek(passphrase, salt, iterations) {
	const base = await subtle().importKey(
		"raw",
		new TextEncoder().encode(passphrase),
		"PBKDF2",
		false,
		["deriveKey"]
	);
	return subtle().deriveKey(
		{ name: "PBKDF2", salt, iterations: iterations || KDF_ITERATIONS, hash: "SHA-256" },
		base,
		{ name: "AES-GCM", length: 256 },
		false,
		["encrypt", "decrypt"]
	);
}

// The two private keys travel as one blob so a single unlock restores both.
async function wrap_identity(kek, ecdh_private, ecdsa_private) {
	const payload = JSON.stringify({
		ecdh: to_b64(await subtle().exportKey("pkcs8", ecdh_private)),
		ecdsa: ecdsa_private ? to_b64(await subtle().exportKey("pkcs8", ecdsa_private)) : null,
	});
	const iv = random_bytes(12);
	const ct = await subtle().encrypt(
		{ name: "AES-GCM", iv },
		kek,
		new TextEncoder().encode(payload)
	);
	return to_b64(new Uint8Array([...iv, ...new Uint8Array(ct)]));
}

async function unwrap_identity(kek, wrapped) {
	const raw = from_b64(wrapped);
	const iv = raw.slice(0, 12);
	const plain = await subtle().decrypt({ name: "AES-GCM", iv }, kek, raw.slice(12));
	const blob = JSON.parse(new TextDecoder().decode(plain));
	const ecdh = await subtle().importKey("pkcs8", from_b64(blob.ecdh), EC_PARAMS, true, [
		"deriveBits",
	]);
	const ecdsa = blob.ecdsa
		? await subtle().importKey("pkcs8", from_b64(blob.ecdsa), SIGN_PARAMS, true, ["sign"])
		: null;
	return { ecdh, ecdsa };
}

// ECDH-ES: one ephemeral keypair per wrap, HKDF over the shared secret. Mirrors
// seal_for_users() in chat_crypto.py so server-sealed WhatsApp messages open here too.
async function derive_wrap_key(private_key, peer_public_key) {
	const shared = await subtle().deriveBits(
		{ name: "ECDH", public: peer_public_key },
		private_key,
		256
	);
	const hkdf = await subtle().importKey("raw", shared, "HKDF", false, ["deriveKey"]);
	return subtle().deriveKey(
		{
			name: "HKDF",
			hash: "SHA-256",
			salt: new Uint8Array(0),
			info: new TextEncoder().encode(WRAP_INFO),
		},
		hkdf,
		{ name: "AES-GCM", length: 256 },
		false,
		["encrypt", "decrypt"]
	);
}

async function import_public(b64) {
	return subtle().importKey("spki", from_b64(b64), EC_PARAMS, true, []);
}

// --- WebAuthn PRF (biometric unlock) ---------------------------------------
//
// The passkey is not used to authenticate against the server — it is used purely as a
// key vault: the PRF extension returns a stable 32-byte secret that never leaves the
// device, and we wrap a second copy of the private key with it. That is why a locally
// generated challenge is fine here; there is nothing for the server to verify.

async function prf_secret(credential_id, salt_b64) {
	const assertion = await navigator.credentials.get({
		publicKey: {
			challenge: random_bytes(32),
			allowCredentials: credential_id
				? [{ id: from_b64(credential_id), type: "public-key" }]
				: [],
			userVerification: "required",
			timeout: 60000,
			extensions: { prf: { eval: { first: from_b64(salt_b64) } } },
		},
	});
	if (!assertion) throw new Error("no assertion");
	const results = assertion.getClientExtensionResults();
	if (!results || !results.prf || !results.prf.results || !results.prf.results.first) {
		throw new Error("prf-unsupported");
	}
	return { secret: results.prf.results.first, credential_id: to_b64(assertion.rawId) };
}

async function kek_from_prf(secret) {
	const hkdf = await subtle().importKey("raw", secret, "HKDF", false, ["deriveKey"]);
	return subtle().deriveKey(
		{
			name: "HKDF",
			hash: "SHA-256",
			salt: new Uint8Array(0),
			info: new TextEncoder().encode("chat-device-kek"),
		},
		hkdf,
		{ name: "AES-GCM", length: 256 },
		false,
		["encrypt", "decrypt"]
	);
}

erpnext.chat_crypto = {
	// --- state -------------------------------------------------------------

	is_unlocked() {
		return !!IDENTITY;
	},

	async is_enrolled() {
		return !!(await this.my_key());
	},

	async my_key(force) {
		if (MY_KEY && !force) return MY_KEY;
		MY_KEY = await frappe.xcall(CRYPTO_API + "get_my_key");
		return MY_KEY;
	},

	lock() {
		IDENTITY = null;
		for (const k of Object.keys(THREAD_KEYS)) delete THREAD_KEYS[k];
	},

	supported() {
		return !!subtle() && !!window.isSecureContext;
	},

	supports_biometric() {
		return !!(window.PublicKeyCredential && navigator.credentials && window.isSecureContext);
	},

	has_biometric() {
		return !!(MY_KEY && (MY_KEY.devices || []).length);
	},

	// --- enrolment ---------------------------------------------------------

	async enroll(passphrase) {
		if (!this.supported()) frappe.throw(__("This browser cannot do encrypted chats"));
		const salt = random_bytes(16);
		const kek = await derive_kek(passphrase, salt, KDF_ITERATIONS);

		const ecdh = await subtle().generateKey(EC_PARAMS, true, ["deriveBits"]);
		const ecdsa = await subtle().generateKey(SIGN_PARAMS, true, ["sign", "verify"]);

		const payload = {
			public_key: to_b64(await subtle().exportKey("spki", ecdh.publicKey)),
			signing_public_key: to_b64(await subtle().exportKey("spki", ecdsa.publicKey)),
			wrapped_private_key: await wrap_identity(kek, ecdh.privateKey, ecdsa.privateKey),
			kdf_salt: to_b64(salt),
			kdf_iterations: KDF_ITERATIONS,
		};
		MY_KEY = await frappe.xcall(CRYPTO_API + "enroll", payload);
		IDENTITY = { ecdh: ecdh.privateKey, ecdsa: ecdsa.privateKey };
		return MY_KEY;
	},

	async unlock(passphrase) {
		const key = await this.my_key(true);
		if (!key) frappe.throw(__("Secret chats are not enabled for your account"));
		const kek = await derive_kek(
			passphrase,
			from_b64(key.kdf_salt),
			key.kdf_iterations || KDF_ITERATIONS
		);
		try {
			IDENTITY = await unwrap_identity(kek, key.wrapped_private_key);
		} catch (e) {
			throw new Error("bad-passphrase");
		}
		return true;
	},

	async unlock_with_biometric() {
		const key = await this.my_key();
		const device = (key && key.devices && key.devices[0]) || null;
		if (!device) throw new Error("no-device");
		const { secret, credential_id } = await prf_secret(device.credential_id, device.prf_salt);
		const kek = await kek_from_prf(secret);
		IDENTITY = await unwrap_identity(kek, device.wrapped_private_key);
		frappe.xcall(CRYPTO_API + "touch_device", { credential_id }).catch(() => {});
		return true;
	},

	// Registering needs an unlocked identity: we re-wrap the private key with the
	// device secret and hand only the wrapped blob to the server.
	async register_biometric(label) {
		if (!IDENTITY) frappe.throw(__("Unlock secret chats first"));
		if (!this.supports_biometric()) frappe.throw(__("This device has no biometric support"));

		const user = frappe.session.user;
		const created = await navigator.credentials.create({
			publicKey: {
				rp: { id: window.location.hostname, name: "ERPNext" },
				user: {
					id: new TextEncoder().encode(user),
					name: user,
					displayName: frappe.session.user_fullname || user,
				},
				challenge: random_bytes(32),
				pubKeyCredParams: [
					{ type: "public-key", alg: -7 },
					{ type: "public-key", alg: -257 },
				],
				authenticatorSelection: {
					authenticatorAttachment: "platform",
					userVerification: "required",
					residentKey: "preferred",
				},
				timeout: 60000,
				extensions: { prf: {} },
			},
		});
		if (!created) throw new Error("no-credential");

		// The PRF output is only available from an assertion, so ask for one right away.
		const salt = random_bytes(32);
		const credential_id = to_b64(created.rawId);
		const { secret } = await prf_secret(credential_id, to_b64(salt));
		const kek = await kek_from_prf(secret);

		MY_KEY = await frappe.xcall(CRYPTO_API + "register_device", {
			credential_id,
			prf_salt: to_b64(salt),
			wrapped_private_key: await wrap_identity(kek, IDENTITY.ecdh, IDENTITY.ecdsa),
			label: label || __("This device"),
		});
		return MY_KEY;
	},

	async revoke_biometric(name) {
		MY_KEY = await frappe.xcall(CRYPTO_API + "revoke_device", { name });
		return MY_KEY;
	},

	async change_passphrase(new_passphrase) {
		if (!IDENTITY) frappe.throw(__("Unlock secret chats first"));
		const salt = random_bytes(16);
		const kek = await derive_kek(new_passphrase, salt, KDF_ITERATIONS);
		await frappe.xcall(CRYPTO_API + "change_passphrase", {
			wrapped_private_key: await wrap_identity(kek, IDENTITY.ecdh, IDENTITY.ecdsa),
			kdf_salt: to_b64(salt),
			kdf_iterations: KDF_ITERATIONS,
		});
		// Devices keep their own wrapping, but they were bound to the old passphrase's
		// trust decision — make the user re-register deliberately.
		await this.my_key(true);
		return true;
	},

	// --- thread keys -------------------------------------------------------

	// Fresh AES-256-GCM key plus a wrapped copy for every participant.
	async new_thread_key(users) {
		const key = await subtle().generateKey({ name: "AES-GCM", length: 256 }, true, [
			"encrypt",
			"decrypt",
		]);
		return { key, wrapped: await this.wrap_for_users(key, users) };
	},

	async wrap_for_users(key, users) {
		const pubs = await frappe.xcall(CRYPTO_API + "get_public_keys", {
			users: JSON.stringify(users),
		});
		const raw = await subtle().exportKey("raw", key);
		const out = [];
		for (const user of users) {
			const row = pubs[user];
			if (!row) continue;
			const ephemeral = await subtle().generateKey(EC_PARAMS, true, ["deriveBits"]);
			const wrap_key = await derive_wrap_key(
				ephemeral.privateKey,
				await import_public(row.public_key)
			);
			const iv = random_bytes(12);
			const ct = await subtle().encrypt({ name: "AES-GCM", iv }, wrap_key, raw);
			out.push({
				user,
				wrapped_thread_key: to_b64(new Uint8Array([...iv, ...new Uint8Array(ct)])),
				ephemeral_public_key: to_b64(
					await subtle().exportKey("spki", ephemeral.publicKey)
				),
			});
		}
		return out;
	},

	async thread_key(thread) {
		if (THREAD_KEYS[thread]) return THREAD_KEYS[thread];
		if (!IDENTITY) throw new Error("locked");

		const row = await frappe.xcall(CRYPTO_API + "get_thread_key", { thread });
		if (!row) throw new Error("no-key");
		const wrap_key = await derive_wrap_key(
			IDENTITY.ecdh,
			await import_public(row.ephemeral_public_key)
		);
		const blob = from_b64(row.wrapped_thread_key);
		const raw = await subtle().decrypt(
			{ name: "AES-GCM", iv: blob.slice(0, 12) },
			wrap_key,
			blob.slice(12)
		);
		THREAD_KEYS[thread] = await subtle().importKey("raw", raw, { name: "AES-GCM" }, true, [
			"encrypt",
			"decrypt",
		]);
		return THREAD_KEYS[thread];
	},

	// Share an existing thread key with someone who joins later.
	async grant_thread_key(thread, users) {
		const key = await this.thread_key(thread);
		const wrapped = await this.wrap_for_users(key, users);
		await frappe.xcall(CRYPTO_API + "grant_thread_key", {
			thread,
			keys: JSON.stringify(wrapped),
		});
		return wrapped;
	},

	// --- message payloads --------------------------------------------------

	async encrypt(thread, obj) {
		const key = await this.thread_key(thread);
		const iv = random_bytes(12);
		const ct = await subtle().encrypt(
			{ name: "AES-GCM", iv },
			key,
			new TextEncoder().encode(JSON.stringify(obj))
		);
		return { ciphertext: to_b64(ct), iv: to_b64(iv) };
	},

	async decrypt(thread, ciphertext, iv) {
		const key = await this.thread_key(thread);
		const plain = await subtle().decrypt(
			{ name: "AES-GCM", iv: from_b64(iv) },
			key,
			from_b64(ciphertext)
		);
		return JSON.parse(new TextDecoder().decode(plain));
	},

	// --- attachments -------------------------------------------------------
	//
	// Files get their own random key so the bytes can be re-shared without handing out
	// the thread key; that key rides inside the encrypted message payload.

	async encrypt_blob(blob) {
		const key = await subtle().generateKey({ name: "AES-GCM", length: 256 }, true, [
			"encrypt",
			"decrypt",
		]);
		const iv = random_bytes(12);
		const ct = await subtle().encrypt(
			{ name: "AES-GCM", iv },
			key,
			await blob.arrayBuffer()
		);
		return {
			blob: new Blob([ct], { type: "application/octet-stream" }),
			key: to_b64(await subtle().exportKey("raw", key)),
			iv: to_b64(iv),
		};
	},

	async decrypt_blob(array_buffer, key_b64, iv_b64, mime) {
		const key = await subtle().importKey(
			"raw",
			from_b64(key_b64),
			{ name: "AES-GCM" },
			false,
			["decrypt"]
		);
		const plain = await subtle().decrypt(
			{ name: "AES-GCM", iv: from_b64(iv_b64) },
			key,
			array_buffer
		);
		return new Blob([plain], { type: mime || "application/octet-stream" });
	},

	// --- UI ----------------------------------------------------------------

	// Resolves once the identity is unlocked, prompting only if needed. Tries biometrics
	// first when the device has a registered passkey.
	async ensure_unlocked() {
		if (IDENTITY) return true;
		const key = await this.my_key(true);
		if (!key) {
			await this.setup_dialog();
			return this.is_unlocked();
		}
		if (this.has_biometric() && this.supports_biometric()) {
			try {
				await this.unlock_with_biometric();
				return true;
			} catch (e) {
				// Cancelled, unsupported PRF, or a different device — fall back below.
			}
		}
		return this.unlock_dialog();
	},

	unlock_dialog() {
		return new Promise((resolve) => {
			const d = new frappe.ui.Dialog({
				title: __("Unlock secret chats"),
				fields: [
					{
						fieldtype: "Password",
						fieldname: "passphrase",
						label: __("Passphrase"),
						reqd: 1,
					},
					{
						fieldtype: "HTML",
						fieldname: "hint",
						options: `<p class="text-muted small">${__(
							"Your passphrase never leaves this browser. It cannot be reset — if you forget it, the history is lost."
						)}</p>`,
					},
				],
				primary_action_label: __("Unlock"),
				primary_action: async (values) => {
					try {
						await this.unlock(values.passphrase);
					} catch (e) {
						frappe.msgprint(__("Wrong passphrase"));
						return;
					}
					d.hide();
					if (this.supports_biometric() && !this.has_biometric()) {
						this.offer_biometric();
					}
					resolve(true);
				},
			});
			d.onhide = () => resolve(this.is_unlocked());
			d.show();
		});
	},

	setup_dialog() {
		return new Promise((resolve) => {
			const d = new frappe.ui.Dialog({
				title: __("Enable secret chats"),
				fields: [
					{
						fieldtype: "HTML",
						fieldname: "intro",
						options: `<p>${__(
							"Secret chats are encrypted in your browser. Nobody else — not a system manager, not someone with database access — can read them."
						)}</p><p class="text-danger">${__(
							"There is no recovery. If you forget this passphrase and lose your devices, the messages are gone forever."
						)}</p>`,
					},
					{
						fieldtype: "Password",
						fieldname: "passphrase",
						label: __("Passphrase"),
						reqd: 1,
					},
					{
						fieldtype: "Password",
						fieldname: "confirm",
						label: __("Repeat passphrase"),
						reqd: 1,
					},
				],
				primary_action_label: __("Enable"),
				primary_action: async (values) => {
					if (values.passphrase !== values.confirm) {
						frappe.msgprint(__("The passphrases do not match"));
						return;
					}
					if ((values.passphrase || "").length < 8) {
						frappe.msgprint(__("Use at least 8 characters"));
						return;
					}
					await this.enroll(values.passphrase);
					d.hide();
					frappe.show_alert({ message: __("Secret chats enabled"), indicator: "green" });
					if (this.supports_biometric()) this.offer_biometric();
					resolve(true);
				},
			});
			d.onhide = () => resolve(this.is_unlocked());
			d.show();
		});
	},

	offer_biometric() {
		frappe.confirm(
			__("Use biometrics on this device instead of typing the passphrase every time?"),
			async () => {
				try {
					await this.register_biometric();
					frappe.show_alert({
						message: __("Biometric unlock enabled"),
						indicator: "green",
					});
				} catch (e) {
					frappe.msgprint(__("This device does not support biometric unlock"));
				}
			}
		);
	},
};

// The key must not outlive the tab.
$(window).on("beforeunload", () => erpnext.chat_crypto.lock());
