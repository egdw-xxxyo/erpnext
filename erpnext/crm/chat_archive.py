# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Deep archive for the internal Employee Chat.

An archived chat can be packed into a single zip: every message row and every attachment goes
into the archive, the originals are deleted, and the thread keeps nothing but its title, its
last-message metadata and a pointer to the zip. Anyone who may read the chat can unpack it again;
the restored copy is shared, read-only, and reaped a couple of hours after it was last opened.

**The zip is deliberately not a `File` record.** Frappe's private-file route
(`frappe/app.py` -> `utils/response.py:download_private_file` -> `File.is_downloadable`) checks the
module-level `has_permission` in `core/doctype/file/file.py`, which consults neither the
`has_permission` hooks nor `permission_query_conditions`, and it resolves the url with
`frappe.get_all` (permissions ignored). So a `File` attached to the Chat Thread would be
downloadable by any participant and there is no hook that could stop it. With no `File` row at all,
url resolution simply fails and the route returns 403 even for a guessed path. The blob still lives
under `private/files/`, so `bench backup --with-files` keeps it — it is the only copy of the
conversation.

Layout of the archive (schema version 1):

    chat-archive.json   manifest (counts, timestamps, thread metadata)
    thread.json         snapshot of the Chat Thread doc, participants included
    messages.jsonl      one Chat Message row per line, oldest first, all columns
    files.jsonl         one File row per line, plus its blob path and sha256
    blobs/<File.name>   the raw bytes, keyed by File name so nothing can collide
"""

import json
import os
import shutil
import zipfile

import frappe
from frappe import _
from frappe.utils import now

SCHEMA_VERSION = 1
ARCHIVE_DIR = "chat-archive"

# The Single ships empty (`tabSingles` has no row until someone saves the form), and
# `get_single_value` returns None in that state — so these are the real defaults and the form is
# only ever an override.
_DEFAULTS = {
	"auto_deep_archive": 0,
	"deep_archive_after_days": 180,
	"deep_archive_batch_size": 20,
	"restore_ttl_hours": 2,
	"restore_max_messages": 100000,
	"reap_batch_size": 50,
	"stale_job_minutes": 60,
}


def setting(key):
	value = frappe.db.get_single_value("Chat Settings", key)
	if value in (None, ""):
		return _DEFAULTS[key]
	return value


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def archive_rel_path(thread):
	"""Site-relative path of a thread's archive. Kept out of every API payload."""
	return os.path.join("private", "files", ARCHIVE_DIR, thread, f"{thread}.v{SCHEMA_VERSION}.zip")


def archive_abs_path(thread):
	return frappe.get_site_path(archive_rel_path(thread))


def drop_zip(thread):
	"""Delete a thread's archive and its directory. Called when the thread is purged."""
	path = archive_abs_path(thread)
	try:
		if os.path.exists(path):
			os.unlink(path)
		parent = os.path.dirname(path)
		if os.path.isdir(parent) and not os.listdir(parent):
			os.rmdir(parent)
	except OSError:
		frappe.log_error(title="Chat deep archive: could not delete zip", message=frappe.get_traceback())


def verify():
	"""Bench helper: deep-archived threads whose zip is missing on disk."""
	missing = []
	for name in frappe.get_all("Chat Thread", filters={"is_deep_archived": 1}, pluck="name"):
		if not os.path.exists(archive_abs_path(name)):
			missing.append(name)
	return missing
