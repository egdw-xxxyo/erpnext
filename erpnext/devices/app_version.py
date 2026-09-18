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

# 0.6.0 is where the spool stopped being scanned and started being handed out by
# `spool_production.next_spool`. An older build asks the operator to type a serial that does
# not exist yet, so it cannot measure anything on this server. The 0.5.x line shipped before
# that change, which is why the floor is a minor bump rather than 0.5.0.
MIN_ANDROID_APP_VERSION = "0.6.0"
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
