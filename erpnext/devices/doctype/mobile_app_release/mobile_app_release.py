# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Published builds of the companion mobile apps.

The APK lives on this site, not on GitHub: the mobile app talks to ERPNext only, and the
release repository is private, so a device could not fetch a GitHub asset even if it wanted
to. `poll_github_releases` mirrors the newest release here once an hour; attaching an APK to
a release by hand works just as well and needs no token.
"""

import logging

import frappe
import requests
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime
from frappe.utils.file_manager import save_file

from erpnext.devices.app_version import _version_tuple

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
FETCH_TIMEOUT = 60
DEFAULT_APP = "kalheon-android"


class MobileAppRelease(Document):
	def validate(self):
		self.version = (self.version or "").strip().lstrip("vV")


def latest_release(app=DEFAULT_APP):
	"""Newest active release with an APK, by version number.

	Sorted in Python rather than SQL: "0.4.9" sorts after "0.4.10" as a string, and these
	version numbers are already past that point.
	"""
	rows = frappe.get_all(
		"Mobile App Release",
		filters={"app": app, "is_active": 1},
		fields=["name", "version", "apk", "apk_size", "release_notes", "published_on"],
	)
	rows = [r for r in rows if r.apk and _version_tuple(r.version)]
	if not rows:
		return None
	return max(rows, key=lambda r: _version_tuple(r.version))


def poll_github_releases():
	"""Hourly: mirror the newest GitHub Release's APK into a Mobile App Release.

	Never raises — a scheduler job that throws just fills the error log with the same
	traceback every hour, so failures land in Mobile App Settings where an admin sees them.
	"""
	settings = frappe.get_single("Mobile App Settings")
	if not settings.enabled:
		return
	repo = (settings.github_repo or "").strip().strip("/")
	token = settings.token()
	if not repo or not token:
		_record(error="GitHub repository or token is not configured")
		return

	try:
		release = _fetch_latest_release(repo, token)
		version = (release.get("tag_name") or "").strip().lstrip("vV")
		if not version:
			_record(error="Latest GitHub release has no tag")
			return

		name = f"{DEFAULT_APP}-{version}"
		if frappe.db.exists("Mobile App Release", name) and frappe.db.get_value(
			"Mobile App Release", name, "apk"
		):
			# Already mirrored — the poll is a no-op until a newer release shows up.
			_record(latest=version)
			return

		asset = next((a for a in release.get("assets") or [] if (a.get("name") or "").endswith(".apk")), None)
		if not asset:
			_record(error=f"Release {version} has no .apk asset")
			return

		content = _download_asset(asset["url"], token)
		doc = _upsert_release(name, version, release, asset, content)
		_record(latest=doc.version)
		log.info("mobile app release %s mirrored (%s bytes)", doc.version, doc.apk_size)
	except Exception as e:
		frappe.log_error(title="Mobile app release poll failed", message=frappe.get_traceback())
		_record(error=str(e)[:500])


def _fetch_latest_release(repo, token):
	resp = requests.get(
		f"{GITHUB_API}/repos/{repo}/releases/latest",
		headers={
			"Authorization": f"Bearer {token}",
			"Accept": "application/vnd.github+json",
			"X-GitHub-Api-Version": "2022-11-28",
		},
		timeout=FETCH_TIMEOUT,
	)
	resp.raise_for_status()
	return resp.json()


def _download_asset(asset_url, token):
	"""Assets of a private repo are only reachable through the API url with an
	octet-stream Accept header; browser_download_url would answer 404."""
	resp = requests.get(
		asset_url,
		headers={"Authorization": f"Bearer {token}", "Accept": "application/octet-stream"},
		timeout=FETCH_TIMEOUT,
	)
	resp.raise_for_status()
	return resp.content


def _published_on(value):
	"""GitHub timestamps are ISO-8601 UTC with a trailing `Z`, which MariaDB rejects for a
	Datetime column (\"Incorrect datetime value\"), taking the whole release insert with
	it. Store it as a naive UTC datetime."""
	if not value:
		return None
	parsed = get_datetime(str(value).replace("Z", "+00:00"))
	if parsed is None:
		return None
	return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _upsert_release(name, version, release, asset, content):
	if frappe.db.exists("Mobile App Release", name):
		doc = frappe.get_doc("Mobile App Release", name)
	else:
		doc = frappe.new_doc("Mobile App Release")
		doc.app = DEFAULT_APP
		doc.version = version
	doc.tag = release.get("tag_name")
	doc.release_notes = (release.get("body") or "")[:5000]
	doc.published_on = _published_on(release.get("published_at"))
	doc.github_asset_id = str(asset.get("id") or "")
	doc.is_active = 1
	doc.save(ignore_permissions=True)

	# Public on purpose: the device downloads the APK before it has any session with the
	# file, and the installer follows redirects a login page would break.
	file_doc = save_file(asset["name"], content, doc.doctype, doc.name, is_private=0)
	doc.db_set("apk", file_doc.file_url, update_modified=False)
	doc.db_set("apk_size", len(content), update_modified=False)
	doc.reload()
	return doc


def _record(latest=None, error=None):
	"""Poller bookkeeping on the single doctype (set_single_value, not db_set — a Single
	has no row of its own to update)."""
	values = {"last_polled_on": now_datetime(), "last_error": error}
	if latest:
		values["latest_version"] = latest
	for field, value in values.items():
		frappe.db.set_single_value("Mobile App Settings", field, value)
