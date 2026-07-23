# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Key management for secret (end-to-end encrypted) chats.

The server is deliberately a dumb key directory: it stores public keys, the user's
private key *already wrapped* by a key derived from their passphrase in the browser,
and per-thread keys wrapped for each participant. It never sees a passphrase, an
unwrapped private key, or a plaintext message body — losing the passphrase means the
history is gone, by design (see plans/secret chats).

Sealing (`seal_for_users`) is the one place the server touches ciphertext: WhatsApp
messages arrive in the clear from Meta and are encrypted *to* the managers' public keys
before they are written. That needs public keys only — no private key ever lives here.
"""

import base64
import json
import os

import frappe
from frappe import _
from frappe.utils import now

ENC_VERSION = 1
SEAL_ALG = "ECDH-ES-P256-A256GCM"


# ---------------------------------------------------------------------------
# Enrolment
# ---------------------------------------------------------------------------


def _my_key_doc(user=None):
	user = user or frappe.session.user
	name = frappe.db.exists("Chat Encryption Key", {"user": user})
	return frappe.get_doc("Chat Encryption Key", name) if name else None


def is_enrolled(user):
	return bool(frappe.db.exists("Chat Encryption Key", {"user": user}))


@frappe.whitelist()
def enroll(public_key, wrapped_private_key, kdf_salt, signing_public_key=None, kdf_iterations=600000):
	"""Register the current user's key material. Re-enrolling replaces the identity and
	orphans every existing thread key — the old history becomes unreadable, so the UI
	must warn before calling this a second time."""
	me = frappe.session.user
	if me == "Guest":
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	doc = _my_key_doc(me)
	if not doc:
		doc = frappe.new_doc("Chat Encryption Key")
		doc.user = me
	else:
		doc.key_version = (doc.key_version or 1) + 1
		doc.devices = []

	doc.public_key = public_key
	doc.signing_public_key = signing_public_key
	doc.wrapped_private_key = wrapped_private_key
	doc.kdf_salt = kdf_salt
	doc.kdf_iterations = int(kdf_iterations or 600000)
	doc.enrolled_on = now()
	doc.save(ignore_permissions=True)
	return get_my_key()


@frappe.whitelist()
def get_my_key():
	"""Everything the browser needs to unlock: the wrapped private key, its KDF
	parameters, and the registered biometric devices."""
	doc = _my_key_doc()
	if not doc:
		return None
	return {
		"user": doc.user,
		"public_key": doc.public_key,
		"signing_public_key": doc.signing_public_key,
		"wrapped_private_key": doc.wrapped_private_key,
		"kdf_salt": doc.kdf_salt,
		"kdf_iterations": doc.kdf_iterations or 600000,
		"key_version": doc.key_version or 1,
		"enrolled_on": str(doc.enrolled_on) if doc.enrolled_on else None,
		"devices": [
			{
				"name": d.name,
				"label": d.label,
				"credential_id": d.credential_id,
				"prf_salt": d.prf_salt,
				"wrapped_private_key": d.wrapped_private_key,
				"last_used_on": str(d.last_used_on) if d.last_used_on else None,
			}
			for d in doc.devices
		],
	}


@frappe.whitelist()
def change_passphrase(wrapped_private_key, kdf_salt, kdf_iterations=600000):
	"""Store the private key re-wrapped under a new passphrase. The identity keypair is
	unchanged, so every existing thread key keeps working."""
	doc = _my_key_doc()
	if not doc:
		frappe.throw(_("Secret chats are not enabled for your account"))
	doc.wrapped_private_key = wrapped_private_key
	doc.kdf_salt = kdf_salt
	doc.kdf_iterations = int(kdf_iterations or 600000)
	doc.save(ignore_permissions=True)
	return {"ok": True}


@frappe.whitelist()
def get_public_keys(users):
	"""Public keys of the given users — the input for wrapping a thread key. Users who
	have not enabled secret chats are simply absent from the result."""
	if isinstance(users, str):
		users = frappe.parse_json(users)
	if not users:
		return {}
	rows = frappe.get_all(
		"Chat Encryption Key",
		filters={"user": ["in", list(users)]},
		fields=["user", "public_key", "signing_public_key", "key_version"],
	)
	return {r.user: r for r in rows}


@frappe.whitelist()
def get_enrolled_users():
	"""Users who can take part in a secret chat."""
	return frappe.get_all("Chat Encryption Key", pluck="user")


# ---------------------------------------------------------------------------
# Biometric devices (WebAuthn PRF)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def register_device(credential_id, prf_salt, wrapped_private_key, label=None):
	"""Add a per-device copy of the private key, wrapped with the secret the device's
	authenticator derives (Touch ID / Windows Hello). The passphrase stays the root."""
	doc = _my_key_doc()
	if not doc:
		frappe.throw(_("Secret chats are not enabled for your account"))

	for row in doc.devices:
		if row.credential_id == credential_id:
			row.prf_salt = prf_salt
			row.wrapped_private_key = wrapped_private_key
			row.label = label or row.label
			break
	else:
		doc.append(
			"devices",
			{
				"label": label or _("This device"),
				"credential_id": credential_id,
				"prf_salt": prf_salt,
				"wrapped_private_key": wrapped_private_key,
			},
		)
	doc.save(ignore_permissions=True)
	return get_my_key()


@frappe.whitelist()
def touch_device(credential_id):
	"""Record a successful biometric unlock (shown in the device list)."""
	doc = _my_key_doc()
	if not doc:
		return
	for row in doc.devices:
		if row.credential_id == credential_id:
			frappe.db.set_value(
				"Chat Device Key", row.name, "last_used_on", now(), update_modified=False
			)
			break


@frappe.whitelist()
def revoke_device(name):
	"""Drop a device's wrapped key — that device can no longer unlock without the
	passphrase."""
	doc = _my_key_doc()
	if not doc:
		return
	doc.devices = [d for d in doc.devices if d.name != name]
	doc.save(ignore_permissions=True)
	return get_my_key()


# ---------------------------------------------------------------------------
# Thread keys
# ---------------------------------------------------------------------------


def _assert_thread_member(thread, thread_doctype):
	"""Only a participant may read or hand out that thread's wrapped keys."""
	if thread_doctype == "WhatsApp Chat":
		from erpnext.crm.page.whatsapp_chat.whatsapp_chat import _require_wa_access

		_require_wa_access()
		return

	from erpnext.crm.page.employee_chat.employee_chat import _require_participant

	return _require_participant(thread)


@frappe.whitelist()
def get_thread_key(thread, thread_doctype="Chat Thread"):
	"""The current user's wrapped copy of a thread key."""
	_assert_thread_member(thread, thread_doctype)
	row = frappe.db.get_value(
		"Chat Thread Key",
		{"thread": thread, "user": frappe.session.user},
		["name", "wrapped_thread_key", "ephemeral_public_key", "alg"],
		as_dict=True,
	)
	return row


@frappe.whitelist()
def get_thread_keys(threads, thread_doctype="Chat Thread"):
	"""Batch form of `get_thread_key` — used when the chat list opens."""
	if isinstance(threads, str):
		threads = frappe.parse_json(threads)
	if not threads:
		return {}
	rows = frappe.get_all(
		"Chat Thread Key",
		filters={"thread": ["in", list(threads)], "user": frappe.session.user},
		fields=["thread", "wrapped_thread_key", "ephemeral_public_key", "alg"],
	)
	return {r.thread: r for r in rows}


def store_thread_key(thread, user, wrapped_thread_key, ephemeral_public_key, thread_doctype="Chat Thread", granted_by=None):
	"""Upsert one participant's wrapped copy of a thread key."""
	existing = frappe.db.exists("Chat Thread Key", {"thread": thread, "user": user})
	doc = (
		frappe.get_doc("Chat Thread Key", existing)
		if existing
		else frappe.new_doc("Chat Thread Key")
	)
	doc.thread = thread
	doc.thread_doctype = thread_doctype
	doc.user = user
	doc.wrapped_thread_key = wrapped_thread_key
	doc.ephemeral_public_key = ephemeral_public_key
	doc.alg = SEAL_ALG
	doc.granted_by = granted_by or frappe.session.user
	doc.save(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def grant_thread_key(thread, keys, thread_doctype="Chat Thread"):
	"""Hand out a thread key to participants. `keys` is a JSON list of
	{user, wrapped_thread_key, ephemeral_public_key} produced in the granter's browser —
	the plaintext thread key never reaches the server."""
	_assert_thread_member(thread, thread_doctype)
	if isinstance(keys, str):
		keys = frappe.parse_json(keys)

	granted = []
	for k in keys or []:
		user = k.get("user")
		if not user or not k.get("wrapped_thread_key"):
			continue
		store_thread_key(
			thread,
			user,
			k["wrapped_thread_key"],
			k.get("ephemeral_public_key"),
			thread_doctype=thread_doctype,
		)
		granted.append(user)
	return {"granted": granted}


def drop_thread_keys(thread, user):
	"""Revoke a user's access to a thread (e.g. removed from a group). Past messages they
	already read are of course beyond recall."""
	for name in frappe.get_all(
		"Chat Thread Key", filters={"thread": thread, "user": user}, pluck="name"
	):
		frappe.delete_doc("Chat Thread Key", name, ignore_permissions=True, force=True)


# ---------------------------------------------------------------------------
# Server-side sealing (WhatsApp ingest)
# ---------------------------------------------------------------------------


def _b64(raw):
	return base64.b64encode(raw).decode()


def _unb64(text):
	return base64.b64decode(text)


def seal_for_users(payload, users):
	"""Encrypt `payload` (a JSON-serialisable dict) so that only `users` can read it.

	A fresh AES-256-GCM content key is generated, and wrapped for every recipient with
	ECDH-ES against their public key — which needs the *public* half only, so the server
	stays unable to decrypt what it just wrote. Returns None when nobody can receive it
	(no enrolled recipient), so callers can decide to drop or keep the message.
	"""
	from cryptography.hazmat.primitives import hashes, serialization
	from cryptography.hazmat.primitives.asymmetric import ec
	from cryptography.hazmat.primitives.ciphers.aead import AESGCM
	from cryptography.hazmat.primitives.kdf.hkdf import HKDF

	recipients = get_public_keys(list(users or []))
	if not recipients:
		return None

	content_key = AESGCM.generate_key(bit_length=256)
	iv = os.urandom(12)
	ciphertext = AESGCM(content_key).encrypt(iv, json.dumps(payload).encode(), None)

	wrapped = []
	for user, row in recipients.items():
		peer = serialization.load_der_public_key(_unb64(row.public_key))
		ephemeral = ec.generate_private_key(ec.SECP256R1())
		shared = ephemeral.exchange(ec.ECDH(), peer)
		kek = HKDF(
			algorithm=hashes.SHA256(), length=32, salt=None, info=SEAL_ALG.encode()
		).derive(shared)
		wrap_iv = os.urandom(12)
		wrapped_key = AESGCM(kek).encrypt(wrap_iv, content_key, None)
		wrapped.append(
			{
				"user": user,
				# iv || ciphertext, so the browser can split it without extra fields
				"wrapped_thread_key": _b64(wrap_iv + wrapped_key),
				"ephemeral_public_key": _b64(
					ephemeral.public_key().public_bytes(
						serialization.Encoding.DER,
						serialization.PublicFormat.SubjectPublicKeyInfo,
					)
				),
			}
		)

	return {
		"ciphertext": _b64(ciphertext),
		"iv": _b64(iv),
		"enc_version": ENC_VERSION,
		"keys": wrapped,
	}
