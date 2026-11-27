import frappe
from frappe.model.document import Document


class Firmware(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		attribute_name: DF.Data | None
		description: DF.SmallText | None
		disabled: DF.Check
		firmware_name: DF.Data
		flashing_profile: DF.Link
		latest_version: DF.Link | None

	def validate(self):
		self.attribute_name = "Прошивка"

	def refresh_latest_version(self):
		"""Newest Released version, or none when every version is a draft or withdrawn."""
		self.latest_version = latest_released(self.name)


def latest_released(firmware):
	return frappe.db.get_value(
		"Firmware Version",
		{"firmware": firmware, "status": "Released"},
		"name",
		order_by="released_on desc, creation desc",
	)


def update_latest_version(firmware):
	frappe.db.set_value(
		"Firmware", firmware, "latest_version", latest_released(firmware), update_modified=False
	)
