"""Minimum compatible companion-app versions, per client.

Lived in `otdr.py` while the OTDR doctype was the only thing that asked. It is not an
OTDR concept: `mobile_app_api.get_app_update` answers the same question for chat-only
phones that have no measurement hardware at all, and the measurement endpoint answers it
for benches. Kept here so deleting the OTDR doctype does not take the version gate with it.

BUMP the relevant constant whenever a server change requires a matching client update
(config shape, BLE protocol, submit_measurement contract). Clients report their own
version and type; older ones get a soft "please update" warning, never a hard refusal.

The clients version independently — do NOT assume the same number.
  android: ~/git/erpnext-mobile-kalheon
  desktop: ~/git/otdr-sync (unsupported since the workplace measurement cutover)
"""

import frappe

# 0.7.7 is where the scan journal lists the labels each scan printed and prints one again
# (`labels` in the scan log, `reprint_scan_label`), and the CMD-PRINT-AGAIN button left the
# session screen; an older build still offers that button, which repeats a whole batch blind.
# It also stops showing nginx's HTML page on a restart and retries instead.
# 0.7.6 is where the session screen learned to draw the step's command barcodes as buttons
# (`commands` in the session payload); an older build simply does not show them, so the
# operator has to reach for the printed barcode sheet.
# 0.7.5 is where the scanner session screen learned `editable_now`: a context key is writable
# only at the step that asks for it, so an older build still offers a picker for the packing
# template after the order is chosen and the server refuses that write.
# 0.7.1 is where `next_spool` started handing back an already measured spool (`resumed`) and
# `release_spool` started refusing one (`reason: "measured"`). A 0.7.0 build ignores both: it
# clears the spool off the screen on a refused release, which is exactly how measured spools
# ended up stranded out of stock with nothing pointing back at them.
# Before that, 0.6.0 was the floor — where the spool stopped being scanned and started being
# handed out by `spool_production.next_spool`.
MIN_ANDROID_APP_VERSION = "0.7.7"
MIN_DESKTOP_APP_VERSION = "0.1.0"


def min_version_for(client):
	"""Minimum compatible version for a client type. Defaults to android."""
	return MIN_DESKTOP_APP_VERSION if client == "desktop" else MIN_ANDROID_APP_VERSION


def _version_tuple(v):
	"""Parse leading dotted numeric part of a version string ('1.2.3-dev' -> (1,2,3))."""
	if not v:
		return ()
	head = str(v).strip().lstrip("vV").split("-", 1)[0].split("+", 1)[0]
	parts = []
	for chunk in head.split("."):
		if chunk.isdigit():
			parts.append(int(chunk))
		else:
			break
	return tuple(parts)


def is_app_compatible(app_version, client=None):
	"""True if reported app_version >= minimum for its client type.

	Unknown or unparseable version -> True: never nag on missing data, only warn when the
	client can be proven older.
	"""
	cur = _version_tuple(app_version)
	if not cur:
		return True
	return cur >= _version_tuple(min_version_for(client))


def sync_required_app_version():
	"""Copy the code constant onto Mobile App Settings. Runs on `after_migrate`.

	The APK itself lives in `Mobile App Release`, mirrored from GitHub — but that mirror can
	fail (a poll error, a token that expired, a release published without an APK), and then
	the site holds an old build while the server already requires a newer one and nothing
	says so. The constant is deployed with the server, so writing it into the database on
	every migrate gives the desk something to compare the uploaded APK against.
	"""
	if not frappe.db.exists("DocType", "Mobile App Settings"):
		return
	current = frappe.db.get_single_value("Mobile App Settings", "required_android_version")
	if (current or "") == MIN_ANDROID_APP_VERSION:
		return
	frappe.db.set_single_value("Mobile App Settings", "required_android_version", MIN_ANDROID_APP_VERSION)
	frappe.db.commit()


def required_android_version():
	"""What this server build needs the Android app to be, operator override winning."""
	override = frappe.db.get_single_value("Mobile App Settings", "min_android_version")
	return (override or "").strip() or MIN_ANDROID_APP_VERSION


@frappe.whitelist()
def android_version_status():
	"""Whether the APK this site hands out is new enough for the server running here.

	`missing` and `stale` are the two ways the bench ends up unable to update: no APK
	mirrored at all, or one older than the server requires.
	"""
	from erpnext.devices.doctype.mobile_app_release.mobile_app_release import latest_release

	required = required_android_version()
	release = latest_release()
	available = release.version if release else None

	if not available:
		state = "missing"
	elif _version_tuple(available) < _version_tuple(required):
		state = "stale"
	else:
		state = "ok"

	return {
		"required": required,
		"available": available,
		"state": state,
		"ok": state == "ok",
		"last_error": frappe.db.get_single_value("Mobile App Settings", "last_error"),
		"last_polled_on": str(frappe.db.get_single_value("Mobile App Settings", "last_polled_on") or ""),
	}
