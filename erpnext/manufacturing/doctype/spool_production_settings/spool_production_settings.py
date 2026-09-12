import frappe
from frappe.model.document import Document


class SpoolProductionSettings(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.manufacturing.doctype.spool_production_plan_item.spool_production_plan_item import (
			SpoolProductionPlanItem,
		)

		cleanup_enabled: DF.Check
		company: DF.Link | None
		delete_unused_serials: DF.Check
		enabled: DF.Check
		fg_warehouse: DF.Link | None
		last_result: DF.SmallText | None
		last_run_on: DF.Datetime | None
		overflow_qty: DF.Int
		plan: DF.Table[SpoolProductionPlanItem]
		wip_warehouse: DF.Link | None

	def validate(self):
		if not self.enabled:
			return

		for row in self.plan:
			if row.enabled and row.daily_qty < 0:
				frappe.throw(
					frappe._("Daily Qty cannot be negative (row {0})").format(row.idx),
				)
