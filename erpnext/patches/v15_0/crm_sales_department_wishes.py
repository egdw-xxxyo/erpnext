"""Rework the CRM around the Military Unit, as asked by the sales department.

The Unit becomes the entry point of a Lead instead of a mirrored attribute of the linked
organization, the contact person moves into a Link field, and the person-name fields are
retired. Property Setters left over from desk edits would pin the old definitions, so they
are dropped here.
"""

import frappe

from erpnext.patches.v15_0.rework_lead_status import rebuild_lead_kanban_boards

MILITARY_UNIT_PROPERTIES = ("title_field", "search_fields", "show_title_field_in_link")

REWORKED_LEAD_FIELDS = (
	"military_unit",
	"contact_person",
	"contact_display",
	"first_name",
	"middle_name",
	"last_name",
	"company_name",
	"status",
	"lead_owner",
	"required_month",
	"next_action_date",
)

OVERRIDDEN_PROPERTIES = (
	"options",
	"label",
	"hidden",
	"read_only",
	"reqd",
	"mandatory_depends_on",
	"in_list_view",
	"description",
)


def execute():
	frappe.reload_doc("crm", "doctype", "military_unit", force=True)
	frappe.reload_doctype("Lead")

	drop_stale_property_setters()
	backfill_lead_contact_person()
	rebuild_lead_kanban_boards()

	frappe.db.commit()
	frappe.clear_cache(doctype="Military Unit")
	frappe.clear_cache(doctype="Lead")


def drop_stale_property_setters():
	stale = frappe.get_all(
		"Property Setter",
		filters={
			"doc_type": "Military Unit",
			"doctype_or_field": "DocType",
			"property": ["in", MILITARY_UNIT_PROPERTIES],
		},
		pluck="name",
	)
	stale += frappe.get_all(
		"Property Setter",
		filters={
			"doc_type": "Lead",
			"field_name": ["in", REWORKED_LEAD_FIELDS],
			"property": ["in", OVERRIDDEN_PROPERTIES],
		},
		pluck="name",
	)

	for name in stale:
		frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)


def backfill_lead_contact_person():
	"""Existing Leads carry their contact only as a Dynamic Link on the Contact."""
	if not frappe.db.has_column("Lead", "contact_person"):
		return

	rows = frappe.db.sql(
		"""
		select dl.link_name as lead, min(dl.parent) as contact
		from `tabDynamic Link` dl
		inner join `tabLead` l on l.name = dl.link_name
		where dl.parenttype = 'Contact'
			and dl.link_doctype = 'Lead'
			and coalesce(l.contact_person, '') = ''
		group by dl.link_name
		""",
		as_dict=True,
	)

	for row in rows:
		contact = frappe.db.get_value("Contact", row.contact, ["full_name", "name"], as_dict=True)
		if not contact:
			continue

		frappe.db.set_value(
			"Lead",
			row.lead,
			{"contact_person": contact.name, "contact_display": contact.full_name},
			update_modified=False,
		)
