import os
import re

import frappe
from frappe import _
from frappe.model.document import Document

# Release notes live as markdown files in erpnext/release_notes/, one per
# version (filename stem = version, e.g. v2026.07.13.md). First `# ` heading is
# the title, the rest is the body. Files are the source of truth; on every
# migrate they are synced into Release Note docs so they can be shown in the UI.
RELEASE_NOTES_DIRNAME = "release_notes"

_DATE_RE = re.compile(r"^v(20\d\d)\.(\d\d)\.(\d\d)")


class ReleaseNote(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		body: DF.TextEditor | None
		environment: DF.Literal["Prod", "Dev"]
		release_date: DF.Date
		title: DF.Data
		version: DF.Data

	def validate(self):
		if not self.release_date:
			self.release_date = _date_from_version(self.version) or frappe.utils.today()
		if self.version and not self.version.startswith("v"):
			frappe.throw(_("Version must start with 'v', e.g. v2026.07.13"))


def _release_notes_dir():
	return os.path.join(frappe.get_app_path("erpnext"), RELEASE_NOTES_DIRNAME)


def _date_from_version(version):
	m = _DATE_RE.match(version or "")
	if not m:
		return None
	return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _parse_md(text):
	"""Return (title, body_html). First `# ` heading = title; rest = body."""
	title = None
	body_lines = []
	for line in text.splitlines():
		if title is None and line.startswith("# "):
			title = line[2:].strip()
			continue
		body_lines.append(line)
	body_md = "\n".join(body_lines).strip()
	body_html = frappe.utils.markdown(body_md) if body_md else ""
	return title, body_html


def sync_release_notes():
	"""Upsert a Release Note doc for each markdown file in release_notes/.
	Runs on `after_migrate`. Files are the source of truth — existing docs are
	updated to match their file. Idempotent."""
	directory = _release_notes_dir()
	if not os.path.isdir(directory):
		return

	for fname in sorted(os.listdir(directory)):
		if not fname.endswith(".md") or fname.startswith("_") or fname.upper() == "README.MD":
			continue
		version = fname[:-3]
		path = os.path.join(directory, fname)
		try:
			with open(path, encoding="utf-8") as f:
				text = f.read()
		except OSError:
			continue

		title, body_html = _parse_md(text)
		title = title or version
		release_date = _date_from_version(version) or frappe.utils.today()

		if frappe.db.exists("Release Note", version):
			doc = frappe.get_doc("Release Note", version)
			if doc.title != title or doc.body != body_html:
				doc.title = title
				doc.body = body_html
				doc.save(ignore_permissions=True)
		else:
			frappe.get_doc(
				{
					"doctype": "Release Note",
					"version": version,
					"title": title,
					"body": body_html,
					"release_date": release_date,
					"environment": "Prod",
				}
			).insert(ignore_permissions=True)

	frappe.db.commit()


@frappe.whitelist()
def get_current_version():
	"""Newest Release Note = the deployed version. None if none synced yet."""
	rows = frappe.get_all(
		"Release Note",
		fields=["version", "release_date", "title"],
		order_by="version desc",
		limit=1,
	)
	if not rows:
		return None
	r = rows[0]
	return {"version": r.version, "date": str(r.release_date) if r.release_date else None, "subject": r.title}
