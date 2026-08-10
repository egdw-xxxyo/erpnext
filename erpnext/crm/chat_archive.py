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

Two semgrep rules are silenced throughout this module with a bare `# nosemgrep`:

* `frappe-manual-commit` — packing and unpacking are long background jobs that destroy and
  recreate rows in batches. They commit as they go on purpose: a worker killed halfway must
  leave the work it already finished behind, and the state transitions (`claim`, `_set_state`)
  must be visible to every other request immediately or two jobs would run on one thread.
* `frappe-security-file-traversal` — every path here comes from `archive_abs_path`, which builds
  it from the thread name plus a fixed layout, or from a `File` row's own `file_url`. No path is
  ever taken from a request.
"""

import datetime
import hashlib
import io
import json
import os
import shutil
import zipfile

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, get_files_path, now
from frappe.utils.synchronization import filelock

SCHEMA_VERSION = 1
ARCHIVE_DIR = "chat-archive"

# The Single ships empty (`tabSingles` has no row until someone saves the form), and
# `get_single_value` returns None in that state — so these are the real defaults and the form is
# only ever an override.
_DEFAULTS = {
	"auto_archive_entity_chats": 0,
	"archive_entity_after_days": 30,
	"archive_batch_size": 100,
	"auto_deep_archive": 0,
	"deep_archive_after_days": 180,
	"deep_archive_batch_size": 20,
	"restore_ttl_hours": 2,
	"restore_max_messages": 100000,
	"reap_batch_size": 50,
	"stale_job_minutes": 60,
}


def setting(key):
	# Read `tabSingles` directly: `get_single_value` casts by fieldtype, so an Int the user has
	# never saved comes back as 0, not None — which silently turned every limit here into zero
	# ("this chat is too large to unpack" for a two-message chat).
	# Raw SQL: `tabSingles` has no `modified` column, so the query builder's default ORDER BY
	# fails on it.
	rows = frappe.db.sql("select value from `tabSingles` where doctype = 'Chat Settings' and field = %s", key)
	value = rows[0][0] if rows else None
	if value in (None, ""):
		return _DEFAULTS[key]
	return int(value)


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


def touch(thread):
	"""Push an unpacked copy's expiry out. Called on every read of a restored chat, but only
	written when it actually moves the deadline — scrolling a thread must not be a write per page."""
	ttl_hours = int(setting("restore_ttl_hours"))
	current = frappe.db.get_value("Chat Thread", thread, "restore_expires_on")
	new = add_to_date(None, hours=ttl_hours)
	if current and get_datetime(current) > add_to_date(new, minutes=-5):
		return
	frappe.db.set_value("Chat Thread", thread, "restore_expires_on", new, update_modified=False)


def _sha256(path):
	digest = hashlib.sha256()
	with open(path, "rb") as fh:  # nosemgrep
		for chunk in iter(lambda: fh.read(1024 * 1024), b""):
			digest.update(chunk)
	return digest.hexdigest()


def _set_state(thread, values):
	"""State fields are read_only in the schema and must never bump `modified` — the age-based
	job and the archive banner both read it."""
	frappe.db.set_value("Chat Thread", thread, values, update_modified=False)


def claim(thread, from_status, to_status):
	"""Race-free state transition: lock the row, check the state we expect, move it. Returns
	True only for the caller that won — the loser subscribes to the winner's progress instead of
	starting a second job."""
	current = frappe.db.sql(
		"select ifnull(deep_archive_status, '') from `tabChat Thread` where name = %s for update",
		thread,
	)
	if not current or current[0][0] != (from_status or ""):
		return False
	_set_state(thread, {"deep_archive_status": to_status})
	frappe.db.commit()  # nosemgrep
	return True


# ---------------------------------------------------------------------------
# Pack
# ---------------------------------------------------------------------------


MESSAGE_COLUMNS = [
	"name",
	"creation",
	"modified",
	"modified_by",
	"owner",
	"docstatus",
	"idx",
	"thread",
	"sender",
	"content_type",
	"message",
	"attach",
	"link_data",
	"reply_to",
	"reactions",
	"is_encrypted",
	"enc_iv",
	"enc_version",
]

FILE_COLUMNS = [
	"name",
	"creation",
	"modified",
	"modified_by",
	"owner",
	"docstatus",
	"idx",
	"file_name",
	"file_url",
	"file_size",
	"file_type",
	"is_private",
	"content_hash",
	"folder",
	"attached_to_doctype",
	"attached_to_name",
	"attached_to_field",
	"thumbnail_url",
]


def _row_to_json(row):
	"""Datetimes must survive the round trip with microseconds — message pagination is
	keyset-on-creation and the client compares the cursors as strings."""
	out = {}
	for key, value in row.items():
		out[key] = str(value) if isinstance(value, datetime.datetime | datetime.date) else value
	return out


def pack(thread):
	"""Pack a thread into its archive and delete the originals. Runs as a background job.

	Nothing is destroyed until the zip exists, is closed, reopens cleanly and contains every
	blob it promises — a crash before that point leaves the chat untouched."""
	# Imported lazily: employee_chat calls into this module, so a top-level import would cycle.
	from erpnext.crm.page.employee_chat.employee_chat import _fanout, _thread_file_names

	with filelock(f"chat_archive_{thread}", timeout=5):
		doc = frappe.get_doc("Chat Thread", thread)
		if doc.deep_archive_status != "Packing":
			return

		try:
			path = archive_abs_path(thread)
			os.makedirs(os.path.dirname(path), exist_ok=True)
			tmp_path = path + ".part"
			file_names = _thread_file_names(thread)
			counts = _write_archive(tmp_path, doc, file_names)
			_check_archive(tmp_path, counts)
			os.replace(tmp_path, path)
			os.chmod(path, 0o600)
		except Exception:
			frappe.db.rollback()
			_set_state(thread, {"deep_archive_status": "Failed", "restore_error": frappe.get_traceback()})
			frappe.db.commit()
			frappe.log_error(title=f"Chat deep archive: packing {thread} failed")
			raise

		_delete_originals(thread, file_names)
		_set_state(
			thread,
			{
				"deep_archive_status": "Archived",
				"is_deep_archived": 1,
				"deep_archived_on": now(),
				"deep_archived_by": frappe.session.user,
				"archived_message_count": counts["messages"],
				"archived_file_count": counts["files"],
				"deep_archive_path": archive_rel_path(thread),
				"deep_archive_sha256": _sha256(path),
				"deep_archive_size": os.path.getsize(path),
				"restore_error": None,
				"restore_progress": 0,
				"restore_expires_on": None,
			},
		)
		frappe.db.commit()  # nosemgrep

	doc.reload()
	_fanout(
		doc,
		"chat_deep_archived",
		{"thread": thread, "message_count": counts["messages"], "file_count": counts["files"]},
	)


def _write_archive(tmp_path, doc, file_names):
	"""Stream the thread into a zip. Messages are paged, blobs are copied chunk by chunk —
	a long thread must not be held in memory."""
	counts = {"messages": 0, "files": 0, "blob_bytes": 0}
	first_message_on = None
	last_message_on = None

	with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
		with zf.open("messages.jsonl", "w") as member:
			after = None
			while True:
				filters = {"thread": doc.name}
				if after:
					filters["creation"] = (">", after)
				rows = frappe.db.get_all(
					"Chat Message",
					filters=filters,
					fields=MESSAGE_COLUMNS,
					order_by="creation asc",
					limit=5000,
				)
				if not rows:
					break
				for row in rows:
					if first_message_on is None:
						first_message_on = str(row["creation"])
					last_message_on = str(row["creation"])
					member.write((json.dumps(_row_to_json(row), ensure_ascii=False) + "\n").encode())
					counts["messages"] += 1
				after = rows[-1]["creation"]

		file_rows = []
		for name in file_names:
			row = frappe.db.get_value("File", name, FILE_COLUMNS, as_dict=True)
			if not row:
				continue
			blob = _blob_path(row)
			if not blob or not os.path.exists(blob):
				# The row outlived its bytes; keep the metadata so the loss is visible.
				row = _row_to_json(row)
				row["blob"] = None
				file_rows.append(row)
				continue
			member_name = f"blobs/{name}"
			with open(blob, "rb") as src, zf.open(member_name, "w") as dst:  # nosemgrep
				shutil.copyfileobj(src, dst, 1024 * 1024)
			row = _row_to_json(row)
			row["blob"] = member_name
			row["sha256"] = _sha256(blob)
			file_rows.append(row)
			counts["files"] += 1
			counts["blob_bytes"] += os.path.getsize(blob)

		zf.writestr(
			"files.jsonl",
			"".join(json.dumps(r, ensure_ascii=False) + "\n" for r in file_rows),
		)
		zf.writestr(
			"thread.json",
			json.dumps(
				_row_to_json(doc.as_dict(no_nulls=False, convert_dates_to_str=True)), ensure_ascii=False
			),
		)
		zf.writestr(
			"chat-archive.json",
			json.dumps(
				{
					"schema_version": SCHEMA_VERSION,
					"thread": doc.name,
					"thread_type": doc.thread_type,
					"is_secret": doc.is_secret,
					"packed_on": now(),
					"packed_by": frappe.session.user,
					"message_count": counts["messages"],
					"file_count": counts["files"],
					"total_blob_bytes": counts["blob_bytes"],
					"first_message_on": first_message_on,
					"last_message_on": last_message_on,
					"last_message_preview": doc.last_message_preview,
					"last_sender": doc.last_sender,
				},
				ensure_ascii=False,
			),
		)
	return counts


def _check_archive(path, counts):
	"""Reopen the finished zip and prove it holds what the manifest claims."""
	with zipfile.ZipFile(path) as zf:
		if zf.testzip() is not None:
			frappe.throw(_("The chat archive is corrupt"))
		manifest = json.loads(zf.read("chat-archive.json"))
		if manifest["schema_version"] != SCHEMA_VERSION:
			frappe.throw(_("Unexpected archive version"))
		names = set(zf.namelist())
		for line in zf.read("files.jsonl").decode().splitlines():
			row = json.loads(line)
			if row.get("blob") and row["blob"] not in names:
				frappe.throw(_("The chat archive is missing an attachment"))
		if manifest["message_count"] != counts["messages"]:
			frappe.throw(_("The chat archive is incomplete"))


def _blob_path(file_row):
	"""On-disk path of a File row, derived from its url so it also works for rows whose doc we
	never load (and, on restore, before the row exists at all)."""
	url = file_row.get("file_url")
	if not url:
		return None
	return get_files_path(os.path.basename(url), is_private=int(file_row.get("is_private") or 0))


def _delete_originals(thread, file_names):
	"""Drop what the archive now holds. Files first: a stray File row without messages is
	recoverable noise, an orphaned message pointing at nothing is not."""
	for name in file_names:
		try:
			frappe.delete_doc("File", name, ignore_permissions=True, force=True, delete_permanently=True)
		except Exception:
			frappe.log_error(title="Chat deep archive: could not delete file", message=frappe.get_traceback())
	while True:
		batch = frappe.get_all("Chat Message", filters={"thread": thread}, pluck="name", limit=2000)
		if not batch:
			break
		frappe.db.delete("Chat Message", {"name": ("in", batch)})
		frappe.db.commit()  # nosemgrep


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


def restore(thread, requested_by=None, promote=False):
	"""Unpack an archive back into real (read-only) rows. Runs as a background job.

	With `promote` the unpacked copy is kept for good — the zip is dropped and the chat goes back to
	being an ordinary archived chat (see `leave_deep_archive`). That is the path a Chat Manager takes
	on a thread that was never unpacked.

	Rows go in with `frappe.db.bulk_insert`, not `doc.insert()`: only a raw insert can restore
	`name`, `creation` and `owner` verbatim, and the document lifecycle is actively unwanted here —
	`Chat Message.after_insert` would queue a thumbnail job per image and overwrite the
	`thumbnail_url` we just restored, and `File.after_insert` would post a comment per attachment.
	These rows were valid when they were written; there is nothing left to validate."""
	from erpnext.crm.page.employee_chat.employee_chat import _fanout

	with filelock(f"chat_archive_{thread}", timeout=5):
		doc = frappe.get_doc("Chat Thread", thread)
		if doc.deep_archive_status != "Restoring":
			return
		path = archive_abs_path(thread)
		try:
			if not os.path.exists(path):
				frappe.throw(_("The chat archive is missing"))
			if doc.deep_archive_sha256 and _sha256(path) != doc.deep_archive_sha256:
				frappe.throw(_("The chat archive is corrupt"))

			with zipfile.ZipFile(path) as zf:
				manifest = json.loads(zf.read("chat-archive.json"))
				if manifest.get("schema_version") != SCHEMA_VERSION:
					frappe.throw(_("Unexpected archive version"))
				if manifest.get("message_count", 0) > int(setting("restore_max_messages")):
					frappe.throw(_("This chat is too large to unpack"))
				total = (manifest.get("message_count") or 0) + (manifest.get("file_count") or 0)
				done = _restore_files(zf, thread, total, doc)
				_restore_messages(zf, thread, total, done, doc)
		except Exception:
			frappe.db.rollback()
			_set_state(
				thread,
				{
					"deep_archive_status": "Failed",
					"restore_error": frappe.get_traceback(),
					"restore_progress": 0,
				},
			)
			frappe.db.commit()
			frappe.log_error(title=f"Chat deep archive: unpacking {thread} failed")
			doc.reload()
			_fanout(doc, "chat_restore_failed", {"thread": thread})
			raise

		# Only now does the chat become readable: until this flips, get_messages returns nothing,
		# so nobody can catch a half-unpacked conversation.
		_set_state(
			thread,
			{
				"deep_archive_status": "Restored",
				"restore_progress": 100,
				"restore_error": None,
				"restore_expires_on": add_to_date(None, hours=int(setting("restore_ttl_hours"))),
			},
		)
		frappe.db.commit()  # nosemgrep

		if promote:
			_leave_deep_archive(thread)

	doc.reload()
	if promote:
		_notify_left_deep_archive(thread, doc)
		return
	_fanout(doc, "chat_restore_done", {"thread": thread, "requested_by": requested_by})


def _restore_files(zf, thread, total, doc):
	"""Write the blobs back to their original paths, then insert the File rows.

	The url must come back byte-for-byte: in a secret chat the url of an encrypted preview lives
	inside the ciphertext, so a re-derived url would leave the picture unreachable forever."""
	rows = [json.loads(line) for line in zf.read("files.jsonl").decode().splitlines() if line.strip()]
	values = []
	done = 0
	for row in rows:
		done += 1
		_publish_progress(thread, doc, "files", done, total)
		member = row.get("blob")
		if not member:
			continue
		target = _blob_path(row)
		if not target:
			continue
		os.makedirs(os.path.dirname(target), exist_ok=True)
		if os.path.exists(target):
			if row.get("sha256") and _sha256(target) == row["sha256"]:
				pass  # already there from a previous, interrupted run
			elif frappe.db.exists("File", {"file_url": row["file_url"]}):
				# Something else owns this url now — leave both alone.
				continue
			else:
				frappe.log_error(
					title="Chat deep archive: attachment path taken",
					message=f"{thread}: {row['file_url']} exists with different content",
				)
				continue
		else:
			with zf.open(member) as src, open(target, "wb") as dst:  # nosemgrep
				shutil.copyfileobj(src, dst, 1024 * 1024)
		if frappe.db.exists("File", row["name"]):
			continue
		values.append(tuple(row.get(col) for col in FILE_COLUMNS))

	if values:
		frappe.db.bulk_insert("File", FILE_COLUMNS, values, ignore_duplicates=True)
		frappe.db.commit()  # nosemgrep
	return done


def _restore_messages(zf, thread, total, done, doc):
	batch = []
	with zf.open("messages.jsonl") as member:
		for line in io.TextIOWrapper(member, encoding="utf-8"):
			if not line.strip():
				continue
			row = json.loads(line)
			batch.append(tuple(row.get(col) for col in MESSAGE_COLUMNS))
			if len(batch) >= 2000:
				done += _flush_messages(batch)
				_publish_progress(thread, doc, "messages", done, total)
				batch = []
	if batch:
		done += _flush_messages(batch)
		_publish_progress(thread, doc, "messages", done, total)
	return done


def _flush_messages(batch):
	frappe.db.bulk_insert("Chat Message", MESSAGE_COLUMNS, batch, ignore_duplicates=True)
	frappe.db.commit()  # nosemgrep
	return len(batch)


def leave_deep_archive(thread):
	"""Make an unpacked copy permanent: drop the zip and clear the deep-archive state, leaving an
	ordinary archived chat behind (which can then be unarchived like any other).

	Only valid on a `Restored` thread — the rows have to be back in the database before the zip,
	which is the only other copy, is deleted."""
	with filelock(f"chat_archive_{thread}", timeout=5):
		doc = frappe.get_doc("Chat Thread", thread)
		if doc.deep_archive_status != "Restored":
			return False
		_leave_deep_archive(thread)

	doc.reload()
	_notify_left_deep_archive(thread, doc)
	return True


def _leave_deep_archive(thread):
	"""Body of `leave_deep_archive`, without the lock — `restore` calls it while it still holds one.

	Deleting the zip is the last step: if the state update fails the archive is still there and the
	thread is merely a restored copy that expires as usual."""
	_set_state(
		thread,
		{
			"is_deep_archived": 0,
			"deep_archive_status": "",
			"deep_archive_path": None,
			"deep_archive_sha256": None,
			"deep_archive_size": 0,
			"deep_archived_on": None,
			"deep_archived_by": None,
			"restore_expires_on": None,
			"restore_progress": 0,
			"restore_error": None,
		},
	)
	frappe.db.commit()  # nosemgrep
	drop_zip(thread)


def _notify_left_deep_archive(thread, doc):
	from erpnext.crm.page.employee_chat.employee_chat import _fanout, _is_read_only

	_fanout(
		doc,
		"chat_deep_archive_dropped",
		{
			"thread": thread,
			"status": "",
			"is_deep_archived": 0,
			"read_only": _is_read_only(doc.thread_type, doc.is_archived, 0),
		},
	)


def _publish_progress(thread, doc, phase, done, total):
	"""Progress must be visible while the job runs, so it is published directly rather than
	through `_fanout` — that one forces `after_commit=True`, which would hold every update back
	until the job ends. Persist it too: a Document-thread reader who never joined gets no realtime
	room and can only poll."""
	percent = int(done * 100 / total) if total else 100
	last = frappe.flags.get("chat_restore_percent") or {}
	if last.get(thread) == percent:
		return
	last[thread] = percent
	frappe.flags.chat_restore_percent = last

	frappe.db.set_value("Chat Thread", thread, "restore_progress", percent, update_modified=False)
	frappe.db.commit()  # nosemgrep
	payload = {"thread": thread, "percent": percent, "phase": phase, "done": done, "total": total}
	for user in {p.user for p in doc.participants if p.user}:
		frappe.publish_realtime("chat_restore_progress", payload, user=user, after_commit=False)


# ---------------------------------------------------------------------------
# Expiry + watchdog (scheduled)
# ---------------------------------------------------------------------------


def reap_expired_restores():
	"""Drop unpacked copies nobody has looked at for a while, and reset jobs that died.

	A reader is never reaped out from under: every read pushes the deadline out by a full TTL, and
	a request that loses the race sees the status flip back and gets the archive banner rather than
	half a conversation."""
	from erpnext.crm.page.employee_chat.employee_chat import _fanout

	expired = frappe.get_all(
		"Chat Thread",
		filters={
			"deep_archive_status": "Restored",
			"restore_expires_on": ("<", now()),
		},
		pluck="name",
		limit=int(setting("reap_batch_size")),
	)
	for thread in expired:
		try:
			with filelock(f"chat_archive_{thread}", timeout=0):
				# Re-read inside the lock: someone may have opened the chat since the query.
				expires = frappe.db.get_value("Chat Thread", thread, "restore_expires_on")
				if expires and get_datetime(expires) > get_datetime(now()):
					continue
				_drop_restored_rows(thread)
				_set_state(
					thread,
					{
						"deep_archive_status": "Archived",
						"restore_expires_on": None,
						"restore_progress": 0,
					},
				)
				frappe.db.commit()
			doc = frappe.get_doc("Chat Thread", thread)
			_fanout(doc, "chat_restore_expired", {"thread": thread})
		except Exception:
			frappe.log_error(title=f"Chat deep archive: reaping {thread} failed")

	_reset_stale_jobs()


def _drop_restored_rows(thread):
	"""Delete the unpacked copy. Safe by construction: a deep-archived chat cannot be written to,
	so every row it holds came out of the zip, which still has them."""
	for name in frappe.get_all(
		"File", filters={"attached_to_doctype": "Chat Thread", "attached_to_name": thread}, pluck="name"
	):
		try:
			frappe.delete_doc("File", name, ignore_permissions=True, force=True, delete_permanently=True)
		except Exception:
			frappe.log_error(title="Chat deep archive: could not drop restored file")
	while True:
		batch = frappe.get_all("Chat Message", filters={"thread": thread}, pluck="name", limit=2000)
		if not batch:
			break
		frappe.db.delete("Chat Message", {"name": ("in", batch)})
		frappe.db.commit()  # nosemgrep


def _reset_stale_jobs():
	"""A worker that died mid-job would otherwise leave a chat stuck forever."""
	cutoff = add_to_date(None, minutes=-int(setting("stale_job_minutes")))
	stuck = frappe.get_all(
		"Chat Thread",
		filters={"deep_archive_status": ("in", ["Packing", "Restoring"]), "modified": ("<", cutoff)},
		fields=["name", "deep_archive_status", "is_deep_archived"],
	)
	for row in stuck:
		if row.deep_archive_status == "Packing":
			# Packing destroys nothing before the zip is verified, so there is nothing to undo.
			_set_state(row.name, {"deep_archive_status": "" if not row.is_deep_archived else "Archived"})
		else:
			_drop_restored_rows(row.name)
			_set_state(row.name, {"deep_archive_status": "Archived", "restore_progress": 0})
		frappe.db.commit()  # nosemgrep
		frappe.log_error(
			title="Chat deep archive: stale job reset",
			message=f"{row.name} was stuck in {row.deep_archive_status}",
		)


def auto_archive_entity_chats():
	"""Daily: archive document chats that have gone quiet.

	Only Document threads — a chat about a record is finished when the record is, whereas a direct
	or group chat between people has no such end. Age is measured from the last message, falling
	back to the thread's creation for a chat where nobody ever wrote anything."""
	from erpnext.crm.page.employee_chat.employee_chat import _fanout

	if not int(setting("auto_archive_entity_chats") or 0):
		return
	cutoff = add_to_date(None, days=-int(setting("archive_entity_after_days")))
	threads = frappe.db.sql(
		"""select name from `tabChat Thread`
		where thread_type = 'Document' and ifnull(is_archived, 0) = 0
			and ifnull(disable_archive, 0) = 0
			and ifnull(last_message_on, creation) < %s
		order by ifnull(last_message_on, creation) asc
		limit %s""",
		(cutoff, int(setting("archive_batch_size"))),
		pluck=True,
	)
	for thread in threads:
		_set_state(thread, {"is_archived": 1, "archived_on": now()})
		frappe.db.commit()  # nosemgrep
		doc = frappe.get_doc("Chat Thread", thread)
		_fanout(doc, "chat_thread_archived", {"thread": thread, "is_archived": 1, "read_only": 1})


def auto_deep_archive():
	"""Daily: pack chats that have been sitting in the archive long enough."""
	if not int(setting("auto_deep_archive") or 0):
		return
	cutoff = add_to_date(None, days=-int(setting("deep_archive_after_days")))
	threads = frappe.get_all(
		"Chat Thread",
		filters={
			"is_archived": 1,
			"is_deep_archived": 0,
			"disable_deep_archive": 0,
			"deep_archive_status": ("in", ["", None]),
			"archived_on": ("<", cutoff),
		},
		pluck="name",
		limit=int(setting("deep_archive_batch_size")),
	)
	for thread in threads:
		if not claim(thread, "", "Packing"):
			continue
		frappe.enqueue(
			"erpnext.crm.chat_archive.pack",
			queue="long",
			timeout=3600,
			job_id=f"chat-pack::{thread}",
			deduplicate=True,
			thread=thread,
		)
