"""Shared image library for labels.

Every image a label uses lives in one public File folder, so anyone who can open Label
Templates sees the same set in the designer gallery and every print can read it.
File names are unique inside the folder, because `<attachment name="...">` resolves by name.
"""

import os
from mimetypes import guess_type

import frappe
from frappe import _

FOLDER_NAME = "Label Images"
FOLDER = f"Home/{FOLDER_NAME}"
IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/svg+xml", "image/webp", "image/bmp")


def ensure_folder():
	if not frappe.db.exists("File", FOLDER):
		frappe.get_doc(
			{"doctype": "File", "file_name": FOLDER_NAME, "is_folder": 1, "folder": "Home"}
		).insert(ignore_permissions=True)
	return FOLDER


@frappe.whitelist()
def get_label_images():
	if not frappe.has_permission("Label Template", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	ensure_folder()
	return frappe.get_all(
		"File",
		filters={"folder": FOLDER, "is_folder": 0},
		fields=["name", "file_name", "file_url", "owner", "creation"],
		order_by="file_name asc",
	)


def _unique_name(file_name):
	base, ext = os.path.splitext(file_name)
	candidate, i = file_name, 1
	while frappe.db.exists("File", {"folder": FOLDER, "file_name": candidate}):
		i += 1
		candidate = f"{base}-{i}{ext}"
	return candidate


@frappe.whitelist()
def upload_label_image():
	"""Target of FileUploader `method`: frappe.handler.upload_file reads the file first."""
	if not frappe.has_permission("Label Template", "write"):
		frappe.throw(_("Only users who edit label templates can add label images"), frappe.PermissionError)
	return _save_image(frappe.local.uploaded_filename, frappe.local.uploaded_file)


@frappe.whitelist(methods=["POST"])
def add_label_image(file_name, content_base64):
	"""API / MCP entry: add an image to the library from base64 content."""
	import base64

	if not frappe.has_permission("Label Template", "write"):
		frappe.throw(_("Only users who edit label templates can add label images"), frappe.PermissionError)
	try:
		content = base64.b64decode(content_base64, validate=True)
	except ValueError:
		frappe.throw(_("Image content is not valid base64"))
	return _save_image(file_name, content)


def _save_image(file_name, content):
	file_name = os.path.basename((file_name or "").strip())
	if not content or not file_name:
		frappe.throw(_("No file uploaded"))
	if guess_type(file_name)[0] not in IMAGE_TYPES:
		frappe.throw(_("Only images can be added to the label image library"))

	ensure_folder()
	doc = frappe.get_doc(
		{
			"doctype": "File",
			"folder": FOLDER,
			"file_name": _unique_name(file_name),
			"is_private": 0,
			"content": content,
		}
	).insert(ignore_permissions=True)
	return {"name": doc.name, "file_name": doc.file_name, "file_url": doc.file_url}


def resolve_file(file_name):
	"""File row for an `<attachment name>`: the library copy first, then any file of that name."""
	fields = ["file_url", "is_private"]
	return frappe.db.get_value("File", {"folder": FOLDER, "file_name": file_name}, fields, as_dict=True) or (
		frappe.db.get_value("File", {"file_name": file_name, "is_folder": 0}, fields, as_dict=True)
	)


def file_path(file_row):
	from urllib.parse import unquote

	url = unquote(file_row.file_url or "")
	if url.startswith("/private/files/"):
		return frappe.get_site_path("private", "files", url[len("/private/files/") :])
	if url.startswith("/files/"):
		return frappe.get_site_path("public", "files", url[len("/files/") :])
	return None


def adopt(file_name):
	"""Put an existing image (any folder, public or private) into the library as a public copy.

	For templates written before the library existed: their `<attachment name>` keeps working
	and the image shows up in the designer gallery.
	"""
	ensure_folder()
	if frappe.db.exists("File", {"folder": FOLDER, "file_name": file_name}):
		return file_name
	src = frappe.db.get_value(
		"File", {"file_name": file_name, "is_folder": 0}, ["file_url", "is_private"], as_dict=True
	)
	path = src and file_path(src)
	if not path or not os.path.exists(path):
		return None
	with open(path, "rb") as f:
		content = f.read()
	frappe.get_doc(
		{"doctype": "File", "folder": FOLDER, "file_name": file_name, "is_private": 0, "content": content}
	).insert(ignore_permissions=True)
	return file_name
