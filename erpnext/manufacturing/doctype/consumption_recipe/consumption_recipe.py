import frappe
from frappe import _
from frappe.model.document import Document

from erpnext.manufacturing.consumption import SAMPLE_VARIABLES, evaluate


class ConsumptionRecipe(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.manufacturing.doctype.consumption_recipe_item.consumption_recipe_item import (
			ConsumptionRecipeItem,
		)

		calculate: DF.Button | None
		description: DF.SmallText | None
		is_active: DF.Check
		items: DF.Table[ConsumptionRecipeItem]
		preview_html: DF.HTML | None
		preview_values: DF.Data | None
		recipe_name: DF.Data

	def validate(self):
		if not self.items:
			frappe.throw(_("Add at least one item to the recipe"))

		for row in self.items:
			self._validate_formula(row, "qty_formula", row.qty_formula or "1")
			if row.condition:
				self._validate_formula(row, "condition", row.condition)

	def _validate_formula(self, row, fieldname, expression):
		"""Run the formula once with sample values, so a typo fails on save and not at the packing bench."""
		try:
			evaluate(expression, SAMPLE_VARIABLES)
		except Exception as e:
			frappe.throw(
				_("Row {0}: {1} {2} is not valid: {3}").format(
					row.idx, _(row.meta.get_label(fieldname)), frappe.bold(expression), str(e)
				)
			)
