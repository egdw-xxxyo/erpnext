# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Update check for the companion mobile apps.

Deliberately separate from `otdr_api.get_configuration`: that one only answers for a device
that has an OTDR configured, so chat-only users never learned their build was old.
"""

import frappe
from frappe.utils import get_url

from erpnext.devices.doctype.mobile_app_release.mobile_app_release import (
	DEFAULT_APP,
	latest_release,
)
from erpnext.devices.doctype.otdr.otdr import _version_tuple, min_version_for


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
			"download_url": get_url(release.apk),
			"release_notes": release.release_notes,
			"size": release.apk_size or 0,
			"published_on": str(release.published_on) if release.published_on else None,
		}
	)
	current = _version_tuple(app_version)
	payload["update_available"] = bool(current) and _version_tuple(release.version) > current
	return payload
