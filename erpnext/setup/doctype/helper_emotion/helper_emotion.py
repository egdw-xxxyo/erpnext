from pathlib import PurePosixPath

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext.setup.helper_guides import BUILTIN_EMOTIONS, KEY_PATTERN

IMAGE_EXTENSIONS = {".png", ".webp", ".gif", ".avif", ".jpg", ".jpeg"}


class HelperEmotion(Document):
	def validate(self):
		if not KEY_PATTERN.fullmatch(self.emotion_key or ""):
			frappe.throw(_("Use a lowercase emotion key with letters, numbers, hyphens, or underscores."))
		if not self.is_new() and self.has_value_changed("emotion_key"):
			frappe.throw(_("A saved emotion key cannot be changed."))
		if self.image and self.image == BUILTIN_EMOTIONS.get(self.emotion_key):
			return
		image = self.image or ""
		if (
			not image.startswith("/files/")
			or PurePosixPath(image).suffix.lower() not in IMAGE_EXTENSIONS
			or not frappe.db.exists("File", {"file_url": image, "is_private": 0})
		):
			frappe.throw(_("Upload a public PNG, WebP, GIF, AVIF or JPEG image for this emotion."))

	def before_rename(self, old, new, merge=False):
		frappe.throw(_("A saved emotion key cannot be changed."))

	def on_trash(self):
		frappe.throw(
			_("Helper emotions can be reused by other guides. Replace the image to update an emotion.")
		)
