# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Update check and setup QR for the companion mobile apps.

Deliberately separate from `otdr_api.get_configuration`: that one only answers for a device
that has an OTDR configured, so chat-only users never learned their build was old.
"""

import frappe
from frappe import _
from frappe.utils import get_url

from erpnext.devices.doctype.mobile_app_release.mobile_app_release import (
	DEFAULT_APP,
	latest_release,
)
from erpnext.devices.doctype.otdr.otdr import _version_tuple, min_version_for
from erpnext.devices.doctype.otdr.otdr_api import _make_qr_data_uri


def _site_url():
	"""The address the visitor actually reached the site on.

	`get_url()` answers with site_config's `host_name`, which in our container stacks is
	the internal `http://frontend:8080` — a name no phone can resolve, so a QR built from
	it provisions a dead server profile. The request's own host is the address that
	provably works; `get_url()` stays the fallback for callers with no request (console,
	background jobs).
	"""
	request = getattr(frappe.local, "request", None)
	host_url = getattr(request, "host_url", None)
	if host_url:
		return host_url.rstrip("/")
	return get_url()


def _download_url(path):
	"""Same reason as `_site_url`: an APK link on the internal host name is undownloadable
	from the phone asking for the update."""
	if not path:
		return None
	if path.startswith("http://") or path.startswith("https://"):
		return path
	return _site_url() + ("" if path.startswith("/") else "/") + path


def _min_android_version():
	override = frappe.db.get_single_value("Mobile App Settings", "min_android_version")
	return (override or "").strip() or min_version_for("android")


@frappe.whitelist(methods=["GET"])
def get_app_update(client="android", app_version=None, app=DEFAULT_APP, **kwargs):
	"""What the given client should be running, and where to get it.

	`update_available` stays False whenever either version is unparseable — same rule as
	`is_app_compatible`: never nag on missing data.
	"""
	min_version = _min_android_version() if client != "desktop" else min_version_for(client)
	payload = {
		"client": client,
		"app_version": app_version or "",
		"min_app_version": min_version,
		"app_compatible": _version_tuple(app_version) >= _version_tuple(min_version)
		if _version_tuple(app_version)
		else True,
		"latest_version": None,
		"update_available": False,
		"download_url": None,
		"release_notes": None,
		"size": 0,
		"published_on": None,
	}

	release = latest_release(app)
	if not release:
		return payload

	payload.update(
		{
			"latest_version": release.version,
			"download_url": _download_url(release.apk),
			"release_notes": release.release_notes,
			"size": release.apk_size or 0,
			"published_on": str(release.published_on) if release.published_on else None,
		}
	)
	current = _version_tuple(app_version)
	payload["update_available"] = bool(current) and _version_tuple(release.version) > current
	return payload


MAX_LOGIN_LENGTH = 140


def _instance_name():
	configured = frappe.db.get_single_value("Mobile App Settings", "instance_name")
	if configured:
		return configured.strip()
	return _site_url().split("//", 1)[-1].split("/", 1)[0]


@frappe.whitelist(allow_guest=True)
def get_provisioning_qr(login=None, **kwargs):
	"""QR shown next to the desk login field, so a phone can be set up by scanning it.

	Guest-callable on purpose: it runs on the login page, before there is a session. The
	payload carries nothing secret — the site URL, the instance label and whatever login the
	visitor typed into the form — and the endpoint never says whether that login exists.
	"""
	login = (login or "").strip()[:MAX_LOGIN_LENGTH]
	payload = {
		"v": 3,
		"url": _site_url(),
		"name": _instance_name(),
		"user": login,
	}
	text = frappe.as_json(payload, indent=None)
	return {"payload": text, "instance_name": payload["name"], "qr_data_uri": _make_qr_data_uri(text)}


@frappe.whitelist()
def get_me():
	"""Who the caller is, for the app's own profile screen.

	`frappe.auth.get_logged_user` answers with the email alone, which is why every screen
	in the mobile app showed an address where a name belongs. Read from the session user's
	own User document — no permission juggling, a user may always read itself — and hand
	back an absolute image URL: `user_image` is stored site-relative (`/files/...`), and a
	phone has no base to resolve that against.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	row = (
		frappe.db.get_value(
			"User",
			user,
			["first_name", "last_name", "full_name", "user_image"],
			as_dict=True,
		)
		or frappe._dict()
	)

	image = (row.get("user_image") or "").strip()
	if image and not image.startswith(("http://", "https://")):
		image = _site_url() + ("" if image.startswith("/") else "/") + image

	return {
		"email": user,
		"first_name": row.get("first_name") or "",
		"last_name": row.get("last_name") or "",
		"full_name": (row.get("full_name") or "").strip() or user,
		"user_image": image or None,
	}
