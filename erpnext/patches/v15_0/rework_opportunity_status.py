"""Move Opportunity onto the «Пропозиція» status set agreed with the sales department."""

import frappe
from frappe.query_builder.functions import Coalesce

from erpnext.patches.setup_custom_fields import (
	OPPORTUNITY_STATUS_MIGRATION,
	OPPORTUNITY_STATUSES,
)

#: Fields reworked by setup_custom_fields. A Customize Form override on any of them would
#: win over our Property Setters and re-introduce the stock labels or options.
REWORKED_FIELDS = [
	"status",
	"sales_stage",
	"probability",
	"opportunity_owner",
	"opportunity_amount",
	"base_opportunity_amount",
	"order_lost_reason",
	"utm_source",
	"organization_details_section",
	"no_of_employees",
	"annual_revenue",
	"industry",
	"market_segment",
]

OVERRIDDEN_PROPERTIES = [
	"options",
	"label",
	"hidden",
	"depends_on",
	"default",
	"in_list_view",
	"reqd",
	"mandatory_depends_on",
]


def execute():
	ensure_opportunity_custom_fields()

	stale = frappe.get_all(
		"Property Setter",
		filters={
			"doc_type": "Opportunity",
			"field_name": ["in", REWORKED_FIELDS],
			"property": ["in", OVERRIDDEN_PROPERTIES],
		},
		pluck="name",
	)
	for name in stale:
		frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)

	for old_status, new_status in OPPORTUNITY_STATUS_MIGRATION.items():
		frappe.db.sql("update `tabOpportunity` set status = %s where status = %s", (new_status, old_status))

	opportunity = frappe.qb.DocType("Opportunity")
	(
		frappe.qb.update(opportunity)
		.set(opportunity.status, "New")
		.where(Coalesce(opportunity.status, "").notin(list(OPPORTUNITY_STATUSES)))
	).run()

	# Unlike `Prospect Lead`, `Prospect Opportunity` carries no status column — nothing to mirror.

	backfill_overdue_flags()
	rebuild_opportunity_kanban_boards()


def ensure_opportunity_custom_fields():
	"""`bench migrate` runs patches before ./deploy calls setup_custom_fields, so a site that
	has never had the fields would hit "Unknown column 'next_action_overdue'". The creator is
	idempotent."""
	from erpnext.patches.setup_custom_fields import create_custom_fields_on_opportunity_process

	create_custom_fields_on_opportunity_process()
	frappe.reload_doctype("Opportunity")


def backfill_overdue_flags():
	if not frappe.db.has_column("Opportunity", "next_action_overdue"):
		return

	from erpnext.crm.opportunity_rules import refresh_overdue_flags

	refresh_overdue_flags()


def rebuild_opportunity_kanban_boards():
	"""Kanban columns are generated from the status options, drop the stale ones."""
	boards = frappe.get_all(
		"Kanban Board",
		filters={"reference_doctype": "Opportunity", "field_name": "status"},
		pluck="name",
	)
	for board in boards:
		doc = frappe.get_doc("Kanban Board", board)
		existing = {column.column_name: column for column in doc.columns}
		doc.columns = []
		for option in OPPORTUNITY_STATUSES:
			column = existing.get(option)
			doc.append(
				"columns",
				{
					"column_name": option,
					"status": column.status if column else "Active",
					"indicator": column.indicator if column else "Gray",
				},
			)
		doc.save(ignore_permissions=True)
