import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class LabelSize(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		description: DF.SmallText | None
		height_mm: DF.Float
		label_size_name: DF.Data | None
		width_mm: DF.Float

	def validate(self):
		if flt(self.width_mm) <= 0:
			frappe.throw(_("Width must be greater than 0"))
		if flt(self.height_mm) <= 0:
			frappe.throw(_("Height must be greater than 0"))
