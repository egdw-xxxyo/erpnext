import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from erpnext.manufacturing import uf2
from erpnext.manufacturing.doctype.firmware.firmware import update_latest_version

ATTRIBUTE = "Прошивка"


class FirmwareVersion(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		attribute_value: DF.Link | None
		block_count: DF.Int
		file: DF.Attach
		firmware: DF.Link
		image_size: DF.Int
		release_notes: DF.TextEditor | None
		released_on: DF.Datetime | None
		sha256: DF.Data | None
		status: DF.Literal["Draft", "Released", "Withdrawn"]
		version: DF.Data

	def validate(self):
		before = self.get_doc_before_save()
		locked = before and before.status != "Draft"

		if locked and before.file != self.file:
			frappe.throw(_("The file of a released version cannot be replaced. Create a new version instead"))

		if before and before.status == "Withdrawn" and self.status != "Withdrawn":
			frappe.throw(_("A withdrawn version cannot be released again. Create a new version instead"))

		if before and before.status == "Released" and self.status == "Draft":
			frappe.throw(_("A released version cannot go back to draft"))

		if not locked:
			self.inspect_file()

		if self.status == "Released" and not self.released_on:
			self.released_on = now_datetime()

	def inspect_file(self):
		data = self.read_image()
		profile = frappe.get_doc(
			"Flashing Profile", frappe.db.get_value("Firmware", self.firmware, "flashing_profile")
		)
		layout = profile.layout()
		info = uf2.check_firmware(data, layout["family_id"], layout["record_address"])
		self.sha256 = uf2.sha256(data)
		self.image_size = len(data)
		self.block_count = info["blocks"]

	def read_image(self):
		return read_image_file(self.file)

	def on_update(self):
		if self.status == "Released":
			self.ensure_attribute_value()
		update_latest_version(self.firmware)

	def on_trash(self):
		used = frappe.db.exists("Job Card", {"firmware_version": self.name})
		if used:
			frappe.throw(_("Version {0} is used by Job Card {1} and cannot be deleted").format(self.name, used))

	def after_delete(self):
		update_latest_version(self.firmware)

	def ensure_attribute_value(self):
		"""The value written to `Serial No` as «Прошивка» once a unit is flashed with this version."""
		if not frappe.db.exists("Additional Attribute", ATTRIBUTE):
			frappe.get_doc(
				{
					"doctype": "Additional Attribute",
					"attribute_name": ATTRIBUTE,
					"description": "Версія прошивки, встановлена на конкретному екземплярі",
				}
			).insert(ignore_permissions=True)

		value = f"{self.firmware} {self.version}"
		name = frappe.db.get_value("Additional Attribute Value", {"attribute": ATTRIBUTE, "value": value})
		if not name:
			name = (
				frappe.get_doc(
					{
						"doctype": "Additional Attribute Value",
						"attribute": ATTRIBUTE,
						"value": value,
						"abbr": self.version[:10],
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		if self.attribute_value != name:
			self.db_set("attribute_value", name, update_modified=False)


def read_image_file(file_url):
	if not file_url:
		frappe.throw(_("Attach the UF2 file first"))
	name = frappe.db.get_value("File", {"file_url": file_url})
	if not name:
		frappe.throw(_("File {0} not found").format(file_url))
	return frappe.get_doc("File", name).get_content()
