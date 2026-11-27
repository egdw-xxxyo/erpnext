import re

import frappe
from frappe import _
from frappe.model.document import Document


def _hex(value, label):
	try:
		return int(str(value).strip(), 16)
	except ValueError:
		frappe.throw(_("{0} must be a hexadecimal number, got {1}").format(label, frappe.bold(value)))


class FlashingProfile(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		description: DF.SmallText | None
		disabled: DF.Check
		family_id: DF.Data
		flash_base: DF.Data
		instructions: DF.TextEditor | None
		profile_name: DF.Data
		serial_magic: DF.Data
		serial_max_length: DF.Int
		serial_offset: DF.Data
		verify_baud: DF.Int
		verify_mode: DF.Literal["Console", "Operator"]
		verify_pattern: DF.Data | None
		verify_timeout: DF.Int

	def validate(self):
		_hex(self.family_id, _("UF2 Family ID"))
		_hex(self.flash_base, _("Flash Base Address"))
		_hex(self.serial_offset, _("Serial Record Offset"))

		if not re.fullmatch(r"[\x20-\x7e]{1,8}", self.serial_magic or ""):
			frappe.throw(_("Serial Record Magic must be 1-8 printable ASCII characters"))

		if not 1 <= (self.serial_max_length or 0) <= 200:
			frappe.throw(_("Serial Max Length must be between 1 and 200"))

		if self.verify_mode == "Console":
			if "{serial}" not in (self.verify_pattern or ""):
				frappe.throw(_("Console Line Pattern must contain {0}").format("{serial}"))
			if not self.verify_baud:
				frappe.throw(_("Console Baud Rate is required for console verification"))

	def layout(self):
		"""The numbers `erpnext.manufacturing.uf2` needs, parsed."""
		return {
			"family_id": _hex(self.family_id, _("UF2 Family ID")),
			"record_address": _hex(self.flash_base, _("Flash Base Address"))
			+ _hex(self.serial_offset, _("Serial Record Offset")),
			"magic": (self.serial_magic or "").encode("ascii"),
			"max_length": self.serial_max_length,
		}
