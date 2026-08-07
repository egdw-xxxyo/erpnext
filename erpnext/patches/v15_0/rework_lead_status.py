"""Move Lead onto the «Запит» status set agreed with the sales department."""

import frappe
from frappe.query_builder.functions import Coalesce

NEW_OPTIONS = [
	"New Request",
	"Contacted",
	"Requirement Gathering",
	"Awaiting Response",
	"Postponed",
	"Converted to Opportunity",
	"Not Relevant",
	"Lost",
]

FINAL_STATUSES = ("Converted to Opportunity", "Not Relevant", "Lost")

STATUS_MAP = {
	"Lead": "New Request",
	"Open": "Contacted",
	"Replied": "Awaiting Response",
	"Interested": "Requirement Gathering",
	"Opportunity": "Converted to Opportunity",
	"Quotation": "Converted to Opportunity",
	"Converted": "Converted to Opportunity",
	"Lost Quotation": "Lost",
	"Do Not Contact": "Not Relevant",
}

# Fields reworked in lead.json. A Customize Form override on any of them would win over
# the shipped definition and re-introduce the old labels or options.
REWORKED_FIELDS = [
	"status",
	"request_type",
	"source",
	"customer",
	"lead_owner",
	"job_title",
	"salutation",
	"gender",
	"annual_revenue",
	"no_of_employees",
	"industry",
	"fax",
	"market_segment",
	"territory",
	"company_name",
	"qualification_tab",
	"qualification_status",
	"column_break_64",
	"qualified_by",
	"qualified_on",
]

OVERRIDDEN_PROPERTIES = [
	"options",
	"label",
	"hidden",
	"depends_on",
	"default",
	"in_list_view",
	"reqd",
]


def execute():
	frappe.reload_doctype("Lead")

	stale = frappe.get_all(
		"Property Setter",
		filters={
			"doc_type": "Lead",
			"field_name": ["in", REWORKED_FIELDS],
			"property": ["in", OVERRIDDEN_PROPERTIES],
		},
		pluck="name",
	)
	for name in stale:
		frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)

	for old_status, new_status in STATUS_MAP.items():
		frappe.db.sql("update `tabLead` set status = %s where status = %s", (new_status, old_status))

	lead = frappe.qb.DocType("Lead")
	(
		frappe.qb.update(lead)
		.set(lead.status, "New Request")
		.where(Coalesce(lead.status, "").notin(NEW_OPTIONS))
	).run()

	# Prospect Lead rows mirror Lead.status (see Lead.update_prospect).
	frappe.db.sql(
		"""
		update `tabProspect Lead` pl
		inner join `tabLead` l on l.name = pl.lead
		set pl.status = l.status
		"""
	)

	backfill_overdue_flags()
	rebuild_lead_kanban_boards()


def backfill_overdue_flags():
	frappe.db.sql(
		"""
		update `tabLead`
		set next_action_overdue = case
			when next_action_date is not null
				and next_action_date < CURDATE()
				and status not in %(final)s
			then 1 else 0 end
		""",
		{"final": list(FINAL_STATUSES)},
	)


def rebuild_lead_kanban_boards():
	"""Kanban columns are generated from the status options, drop the stale ones."""
	boards = frappe.get_all(
		"Kanban Board",
		filters={"reference_doctype": "Lead", "field_name": "status"},
		pluck="name",
	)
	if not boards:
		return

	for board in boards:
		doc = frappe.get_doc("Kanban Board", board)
		existing = {column.column_name: column for column in doc.columns}
		doc.columns = []
		for option in NEW_OPTIONS:
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
