"""Shared image handling for the chat pages (WhatsApp Chat Center + Employee Chat).

Chat threads can carry hundreds of photos; serving the originals inline makes the
thread heavy to load. Every image attachment therefore gets a downscaled copy
(a File doc of its own, inheriting the source file's privacy and owner document)
which the UI lazy-loads as bubbles scroll into view. The original is only fetched
when the user opens the lightbox and asks for it.
"""

import io
import os

import frappe
from frappe import _

# Longest edge of the generated preview, in pixels.
THUMB_MAX_PX = 640
# Images smaller than this are served as-is — a second copy would not pay off.
THUMB_MIN_BYTES = 80 * 1024

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff")


def _is_image_url(file_url):
	return bool(file_url) and file_url.lower().split("?")[0].endswith(IMAGE_EXTENSIONS)


def _source_file(file_url):
	"""The File doc behind an attachment URL, or None for remote/unknown URLs."""
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	return frappe.get_doc("File", name) if name else None


def ensure_thumbnail(file_url):
	"""Return the preview URL for an image attachment, generating it once and
	caching it on the source File's `thumbnail_url`. Falls back to the original
	URL when no smaller copy makes sense, and to None when the file is unknown."""
	if not _is_image_url(file_url):
		return None

	src = _source_file(file_url)
	if not src:
		return None
	if src.thumbnail_url:
		return src.thumbnail_url

	try:
		content = src.get_content()
	except Exception:
		return None
	if not content:
		return None

	if len(content) < THUMB_MIN_BYTES:
		src.db_set("thumbnail_url", file_url, update_modified=False)
		return file_url

	try:
		from PIL import Image

		image = Image.open(io.BytesIO(content))
		image.load()
	except Exception:
		return None

	if max(image.size) <= THUMB_MAX_PX:
		src.db_set("thumbnail_url", file_url, update_modified=False)
		return file_url

	has_alpha = image.mode in ("RGBA", "LA", "P")
	image = image.convert("RGBA" if has_alpha else "RGB")
	image.thumbnail((THUMB_MAX_PX, THUMB_MAX_PX), Image.Resampling.LANCZOS)

	buf = io.BytesIO()
	if has_alpha:
		image.save(buf, format="PNG", optimize=True)
		ext = ".png"
	else:
		image.save(buf, format="JPEG", quality=80, optimize=True)
		ext = ".jpg"

	stem = os.path.splitext(src.file_name or "image")[0]
	try:
		thumb = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{stem}_preview{ext}",
				"content": buf.getvalue(),
				"is_private": src.is_private,
				"attached_to_doctype": src.attached_to_doctype,
				"attached_to_name": src.attached_to_name,
				"folder": src.folder,
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="Chat thumbnail failed", message=frappe.get_traceback())
		return None

	src.db_set("thumbnail_url", thumb.file_url, update_modified=False)
	return thumb.file_url


# ---------------------------------------------------------------------------
# Access control — a preview must never be reachable by someone who cannot see
# the message the image was posted in.
# ---------------------------------------------------------------------------


def _may_view(source, file_url):
	if source == "whatsapp":
		if not frappe.has_permission("WhatsApp Message", "read"):
			return False
		return bool(frappe.db.exists("WhatsApp Message", {"attach": file_url}))

	if source == "chat":
		thread = frappe.db.get_value("Chat Message", {"attach": file_url}, "thread")
		if not thread:
			return False
		return bool(
			frappe.db.exists(
				"Chat Participant",
				{"parenttype": "Chat Thread", "parent": thread, "user": frappe.session.user},
			)
		)

	return False


@frappe.whitelist()
def get_thumbnails(source, files):
	"""Batch endpoint: map each attachment URL to its preview URL. Called by the
	chat pages for the images that just scrolled into view."""
	if source not in ("whatsapp", "chat"):
		frappe.throw(_("Unknown chat source"))
	files = frappe.parse_json(files) or []

	out = {}
	for file_url in files[:60]:
		if not _may_view(source, file_url):
			continue
		thumb = ensure_thumbnail(file_url)
		if thumb:
			out[file_url] = thumb
	return out


def queue_thumbnail(doc, method=None):
	"""doc_events hook: pre-generate the preview for a chat image in the background
	so the first viewer does not pay for the resize."""
	attach = doc.get("attach")
	content_type = (doc.get("content_type") or "").lower()
	if not attach or content_type not in ("image", "sticker"):
		return
	if doc.get("is_encrypted"):
		# The file on disk is ciphertext — only the sender's browser can produce a
		# preview, and it uploads that preview itself.
		return
	if not _is_image_url(attach):
		return
	if frappe.db.get_value("File", {"file_url": attach}, "thumbnail_url"):
		return
	frappe.enqueue(
		"erpnext.crm.chat_media.ensure_thumbnail",
		queue="short",
		enqueue_after_commit=True,
		file_url=attach,
	)
