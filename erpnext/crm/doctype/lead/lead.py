# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.contacts.address_and_contact import (
	delete_contact_and_address,
	load_address_and_contact,
)
from frappe.email.inbox import link_communication_to_document
from frappe.model.mapper import get_mapped_doc
from frappe.share import add_docshare
from frappe.utils import (
	comma_and,
	get_link_to_form,
	getdate,
	has_gravatar,
	now_datetime,
	nowdate,
	validate_email_address,
)

from erpnext.accounts.party import set_taxes
from erpnext.controllers.selling_controller import SellingController
from erpnext.crm.utils import CRMNote, copy_comments, link_communications, link_open_events
from erpnext.selling.doctype.customer.customer import parse_full_name

CONVERTED_STATUS = "Converted to Opportunity"

#: Statuses that close a Lead. A Lead in one of these is read-only for Sales Users and is
#: excluded from the default list view; only a Sales Manager can bring it back (see
#: `revert_from_final_status`).
FINAL_STATUSES = (CONVERTED_STATUS, "Not Relevant", "Lost")

#: Fields that become mandatory for a given status.
STATUS_REQUIRED_FIELDS = {
	"Awaiting Response": ("next_action", "next_action_date"),
	"Postponed": ("return_date", "hold_reason"),
	"Not Relevant": ("close_reason",),
	"Lost": ("close_reason",),
}


class Lead(SellingController, CRMNote):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.crm.doctype.crm_note.crm_note import CRMNote
		from erpnext.crm.doctype.lead_requirement.lead_requirement import LeadRequirement
		from erpnext.crm.doctype.lead_status_reversal.lead_status_reversal import LeadStatusReversal

		annual_revenue: DF.Currency
		blog_subscriber: DF.Check
		campaign_name: DF.Link | None
		city: DF.Data | None
		close_reason: DF.SmallText | None
		company: DF.Link | None
		company_name: DF.Data | None
		conversion_probability: DF.Literal["", "Low Probability", "Medium Probability", "High Probability"]
		country: DF.Link | None
		customer: DF.Link | None
		customer_need: DF.SmallText | None
		disabled: DF.Check
		email_id: DF.Data | None
		fax: DF.Data | None
		first_name: DF.Data | None
		gender: DF.Link | None
		hold_reason: DF.SmallText | None
		image: DF.AttachImage | None
		industry: DF.Link | None
		job_title: DF.Data | None
		language: DF.Link | None
		last_name: DF.Data | None
		lead_name: DF.Data | None
		lead_owner: DF.Link | None
		market_segment: DF.Link | None
		middle_name: DF.Data | None
		military_unit: DF.Link | None
		mobile_no: DF.Data | None
		naming_series: DF.Literal["CRM-LEAD-.YYYY.-"]
		next_action: DF.SmallText | None
		next_action_date: DF.Date | None
		next_action_overdue: DF.Check
		no_of_employees: DF.Literal["1-10", "11-50", "51-200", "201-500", "501-1000", "1000+"]
		notes: DF.Table[CRMNote]
		phone: DF.Data | None
		phone_ext: DF.Data | None
		prospect: DF.Link | None
		qualification_status: DF.Literal["Unqualified", "In Process", "Qualified"]
		qualified_by: DF.Link | None
		qualified_on: DF.Date | None
		request_type: DF.Literal[
			"",
			"Product Purchase",
			"Quotation Request",
			"Technical Information",
			"Demonstration",
			"Testing",
			"Consultation",
			"Partnership",
			"Training",
			"Other",
		]
		requirement: DF.Table[LeadRequirement]
		return_date: DF.Date | None
		salutation: DF.Link | None
		source: DF.Link | None
		state: DF.Data | None
		status: DF.Literal[
			"New Request",
			"Contacted",
			"Requirement Gathering",
			"Awaiting Response",
			"Postponed",
			"Converted to Opportunity",
			"Not Relevant",
			"Lost",
		]
		status_reversals: DF.Table[LeadStatusReversal]
		territory: DF.Link | None
		title: DF.Data | None
		type: DF.Literal["", "Client", "Channel Partner", "Consultant"]
		unsubscribed: DF.Check
		website: DF.Data | None
		whatsapp_no: DF.Data | None
	# end: auto-generated types

	def onload(self):
		customer = frappe.db.get_value("Customer", {"lead_name": self.name})
		self.get("__onload").is_customer = customer
		load_address_and_contact(self)
		self.set_onload("linked_prospects", self.get_linked_prospects())

	def validate(self):
		self.set_full_name()
		self.set_lead_name()
		self.set_title()
		self.check_email_id_is_unique()
		self.validate_email_id()
		self.validate_party_link()
		self.set_military_unit()
		self.validate_conversion_status()
		self.validate_status_requirements()
		self.set_next_action_overdue()

	def before_insert(self):
		self.contact_doc = None
		if frappe.db.get_single_value("CRM Settings", "auto_creation_of_contact"):
			if self.source == "Existing Customer" and self.customer:
				contact = frappe.db.get_value(
					"Dynamic Link",
					{"link_doctype": "Customer", "parenttype": "Contact", "link_name": self.customer},
					"parent",
				)
				if contact:
					self.contact_doc = frappe.get_doc("Contact", contact)
					return
			self.contact_doc = self.create_contact()

		# leads created by email inbox only have the full name set
		if self.lead_name and not any([self.first_name, self.middle_name, self.last_name]):
			self.first_name, self.middle_name, self.last_name = parse_full_name(self.lead_name)

	def after_insert(self):
		self.link_to_contact()

	def on_update(self):
		self.update_prospect()
		self.share_with_lead_owner()

	def on_trash(self):
		frappe.db.set_value("Issue", {"lead": self.name}, "lead", None)
		delete_contact_and_address(self.doctype, self.name)
		self.remove_link_from_prospect()

	def set_full_name(self):
		if self.first_name:
			self.lead_name = " ".join(
				filter(None, [self.salutation, self.first_name, self.middle_name, self.last_name])
			)

	def set_lead_name(self):
		if not self.lead_name:
			# Check for leads being created through data import
			if not self.company_name and not self.email_id and not self.flags.ignore_mandatory:
				frappe.throw(_("A Lead requires either a person's name or an organization's name"))
			elif self.company_name:
				self.lead_name = self.company_name
			else:
				self.lead_name = self.email_id.split("@")[0]

	def set_title(self):
		self.title = self.company_name or self.lead_name

	def check_email_id_is_unique(self):
		if self.email_id:
			# validate email is unique
			if not frappe.db.get_single_value("CRM Settings", "allow_lead_duplication_based_on_emails"):
				duplicate_leads = frappe.get_all(
					"Lead", filters={"email_id": self.email_id, "name": ["!=", self.name]}
				)
				duplicate_leads = [
					frappe.bold(get_link_to_form("Lead", lead.name)) for lead in duplicate_leads
				]

				if duplicate_leads:
					frappe.throw(
						_("Email Address must be unique, it is already used in {0}").format(
							comma_and(duplicate_leads)
						),
						frappe.DuplicateEntryError,
					)

	def validate_email_id(self):
		if self.email_id:
			if not self.flags.ignore_email_validation:
				validate_email_address(self.email_id, throw=True)

			if self.email_id == self.lead_owner:
				frappe.throw(_("Lead Owner cannot be same as the Lead Email Address"))

			if self.is_new() or not self.image:
				self.image = has_gravatar(self.email_id)

	def link_to_contact(self):
		# update contact links
		if self.contact_doc:
			self.contact_doc.append(
				"links", {"link_doctype": "Lead", "link_name": self.name, "link_title": self.lead_name}
			)
			self.contact_doc.save()

	def update_prospect(self):
		lead_row_name = frappe.db.get_value("Prospect Lead", filters={"lead": self.name}, fieldname="name")
		if lead_row_name:
			lead_row = frappe.get_doc("Prospect Lead", lead_row_name)
			lead_row.update(
				{
					"lead_name": self.lead_name,
					"email": self.email_id,
					"mobile_no": self.mobile_no,
					"lead_owner": self.lead_owner,
					"status": self.status,
				}
			)
			lead_row.db_update()

	def remove_link_from_prospect(self):
		prospects = self.get_linked_prospects()

		for d in prospects:
			prospect = frappe.get_doc("Prospect", d.parent)
			if len(prospect.get("leads")) == 1:
				prospect.delete(ignore_permissions=True)
			else:
				to_remove = None
				for d in prospect.get("leads"):
					if d.lead == self.name:
						to_remove = d

				if to_remove:
					prospect.remove(to_remove)
					prospect.save(ignore_permissions=True)

	def get_linked_prospects(self):
		return frappe.get_all(
			"Prospect Lead",
			filters={"lead": self.name},
			fields=["parent"],
		)

	def validate_party_link(self):
		"""A Lead describes one organization, which is either a Prospect or a Customer."""
		if self.prospect and self.customer:
			frappe.throw(
				_("A Lead can be linked to either a Prospect or a Customer, but not to both"),
				title=_("Conflicting Links"),
			)

	def set_military_unit(self):
		"""Mirror the Military Unit of the linked organization. Never edited on the Lead itself."""
		military_unit = None
		if self.prospect:
			military_unit = frappe.db.get_value("Prospect", self.prospect, "military_unit")
		elif self.customer:
			military_unit = frappe.db.get_value("Customer", self.customer, "military_unit")

		self.military_unit = military_unit or None

	def validate_conversion_status(self):
		"""`Converted to Opportunity` is set by the system only, when an Opportunity is created."""
		if self.status != CONVERTED_STATUS:
			return

		if self.flags.converting_to_opportunity or self.has_opportunity():
			return

		frappe.throw(
			_(
				"Status {0} is set automatically when an Opportunity is created and cannot be selected manually"
			).format(frappe.bold(_(CONVERTED_STATUS)))
		)

	def validate_status_requirements(self):
		for fieldname in STATUS_REQUIRED_FIELDS.get(self.status, ()):
			if self.get(fieldname):
				continue

			frappe.throw(
				_("{0} is mandatory when the status is {1}").format(
					frappe.bold(_(self.meta.get_label(fieldname))), frappe.bold(_(self.status))
				),
				title=_("Missing Value"),
			)

	def set_next_action_overdue(self):
		"""Persist the overdue flag so the list view can filter and indicate on it."""
		overdue = (
			self.next_action_date
			and getdate(self.next_action_date) < getdate(nowdate())
			and self.status not in FINAL_STATUSES
		)
		self.next_action_overdue = 1 if overdue else 0

	def share_with_lead_owner(self):
		"""Give the responsible manager individual access, since Sales Users only see their own Leads."""
		if not self.lead_owner or self.lead_owner == self.owner:
			return

		if not self.has_value_changed("lead_owner"):
			return

		if not frappe.db.get_value("User", self.lead_owner, "enabled"):
			return

		add_docshare(
			self.doctype,
			self.name,
			self.lead_owner,
			read=1,
			write=1,
			flags={"ignore_share_permission": True},
			notify=0,
		)

	def has_customer(self):
		return frappe.db.get_value("Customer", {"lead_name": self.name})

	def has_opportunity(self):
		return frappe.db.get_value("Opportunity", {"party_name": self.name, "status": ["!=", "Lost"]})

	def has_quotation(self):
		return frappe.db.get_value(
			"Quotation", {"party_name": self.name, "docstatus": 1, "status": ["!=", "Lost"]}
		)

	def has_lost_quotation(self):
		return frappe.db.get_value("Quotation", {"party_name": self.name, "docstatus": 1, "status": "Lost"})

	@frappe.whitelist()
	def create_prospect_and_contact(self, data):
		data = frappe._dict(data)
		if data.create_contact:
			self.create_contact()

		if data.create_prospect:
			self.create_prospect(data.prospect_name)

	def create_contact(self):
		if not self.lead_name:
			self.set_full_name()
			self.set_lead_name()

		contact = frappe.new_doc("Contact")
		contact.update(
			{
				"first_name": self.first_name or self.lead_name,
				"last_name": self.last_name,
				"salutation": self.salutation,
				"gender": self.gender,
				"designation": self.job_title,
				"company_name": self.company_name,
			}
		)

		if self.email_id:
			contact.append("email_ids", {"email_id": self.email_id, "is_primary": 1})

		if self.phone:
			contact.append("phone_nos", {"phone": self.phone, "is_primary_phone": 1})

		if self.mobile_no:
			contact.append("phone_nos", {"phone": self.mobile_no, "is_primary_mobile_no": 1})

		contact.insert(ignore_permissions=True)
		contact.reload()  # load changes by hooks on contact

		return contact

	def create_prospect(self, company_name):
		try:
			prospect = frappe.new_doc("Prospect")

			prospect.company_name = company_name or self.company_name
			prospect.no_of_employees = self.no_of_employees
			prospect.industry = self.industry
			prospect.market_segment = self.market_segment
			prospect.annual_revenue = self.annual_revenue
			prospect.territory = self.territory
			prospect.fax = self.fax
			prospect.website = self.website
			prospect.prospect_owner = self.lead_owner
			prospect.company = self.company
			prospect.notes = self.notes

			prospect.append(
				"leads",
				{
					"lead": self.name,
					"lead_name": self.lead_name,
					"email": self.email_id,
					"mobile_no": self.mobile_no,
					"lead_owner": self.lead_owner,
					"status": self.status,
				},
			)
			prospect.flags.ignore_permissions = True
			prospect.flags.ignore_mandatory = True
			prospect.save()
		except frappe.DuplicateEntryError:
			frappe.throw(_("Prospect {0} already exists").format(company_name or self.company_name))


@frappe.whitelist()
def make_customer(source_name, target_doc=None):
	return _make_customer(source_name, target_doc)


def _make_customer(source_name, target_doc=None, ignore_permissions=False):
	def set_missing_values(source, target):
		if source.company_name:
			target.customer_type = "Company"
			target.customer_name = source.company_name
		else:
			target.customer_type = "Individual"
			target.customer_name = source.lead_name

		if not target.customer_group:
			target.customer_group = frappe.db.get_default("Customer Group")

	doclist = get_mapped_doc(
		"Lead",
		source_name,
		{
			"Lead": {
				"doctype": "Customer",
				"field_map": {
					"name": "lead_name",
					"company_name": "customer_name",
					"contact_no": "phone_1",
					"fax": "fax_1",
				},
				"field_no_map": ["disabled"],
			}
		},
		target_doc,
		set_missing_values,
		ignore_permissions=ignore_permissions,
	)

	return doclist


@frappe.whitelist()
def make_opportunity(source_name, target_doc=None):
	def set_missing_values(source, target):
		_set_missing_values(source, target)

	target_doc = get_mapped_doc(
		"Lead",
		source_name,
		{
			"Lead": {
				"doctype": "Opportunity",
				"field_map": {
					"campaign_name": "campaign",
					"doctype": "opportunity_from",
					"name": "party_name",
					"lead_name": "contact_display",
					"company_name": "customer_name",
					"email_id": "contact_email",
					"mobile_no": "contact_mobile",
					"lead_owner": "opportunity_owner",
					"notes": "notes",
				},
			}
		},
		target_doc,
		set_missing_values,
	)

	return target_doc


@frappe.whitelist()
def make_quotation(source_name, target_doc=None):
	def set_missing_values(source, target):
		_set_missing_values(source, target)

	target_doc = get_mapped_doc(
		"Lead",
		source_name,
		{"Lead": {"doctype": "Quotation", "field_map": {"name": "party_name"}}},
		target_doc,
		set_missing_values,
	)

	target_doc.quotation_to = "Lead"
	target_doc.run_method("set_missing_values")
	target_doc.run_method("set_other_charges")
	target_doc.run_method("calculate_taxes_and_totals")

	return target_doc


def _set_missing_values(source, target):
	address = frappe.get_all(
		"Dynamic Link",
		{
			"link_doctype": source.doctype,
			"link_name": source.name,
			"parenttype": "Address",
		},
		["parent"],
		limit=1,
	)

	contact = frappe.get_all(
		"Dynamic Link",
		{
			"link_doctype": source.doctype,
			"link_name": source.name,
			"parenttype": "Contact",
		},
		["parent"],
		limit=1,
	)

	if address:
		target.customer_address = address[0].parent

	if contact:
		target.contact_person = contact[0].parent


@frappe.whitelist()
def get_lead_details(lead, posting_date=None, company=None, doctype=None):
	if not lead:
		return {}

	from erpnext.accounts.party import set_address_details

	out = frappe._dict()

	lead_doc = frappe.get_doc("Lead", lead)
	lead = lead_doc

	out.update(
		{
			"territory": lead.territory,
			"customer_name": lead.company_name or lead.lead_name,
			"contact_display": " ".join(filter(None, [lead.lead_name])),
			"contact_email": lead.email_id,
			"contact_mobile": lead.mobile_no,
			"contact_phone": lead.phone,
		}
	)

	set_address_details(out, lead, "Lead", doctype=doctype, company=company)

	taxes_and_charges = set_taxes(
		None,
		"Lead",
		posting_date,
		company,
		billing_address=out.get("customer_address"),
		shipping_address=out.get("shipping_address_name"),
	)
	if taxes_and_charges:
		out["taxes_and_charges"] = taxes_and_charges

	return out


@frappe.whitelist()
def make_lead_from_communication(communication, ignore_communication_links=False):
	"""raise a issue from email"""

	doc = frappe.get_doc("Communication", communication)
	lead_name = None
	if doc.sender:
		lead_name = frappe.db.get_value("Lead", {"email_id": doc.sender})
	if not lead_name and doc.phone_no:
		lead_name = frappe.db.get_value("Lead", {"mobile_no": doc.phone_no})
	if not lead_name:
		lead = frappe.get_doc(
			{
				"doctype": "Lead",
				"lead_name": doc.sender_full_name,
				"email_id": doc.sender,
				"mobile_no": doc.phone_no,
			}
		)
		lead.flags.ignore_mandatory = True
		lead.flags.ignore_permissions = True
		lead.insert()

		lead_name = lead.name

	link_communication_to_document(doc, "Lead", lead_name, ignore_communication_links)
	return lead_name


def get_lead_with_phone_number(number):
	if not number:
		return

	leads = frappe.get_all(
		"Lead",
		or_filters={
			"phone": ["like", f"%{number}"],
			"whatsapp_no": ["like", f"%{number}"],
			"mobile_no": ["like", f"%{number}"],
		},
		limit=1,
		order_by="creation DESC",
	)

	lead = leads[0].name if leads else None

	return lead


@frappe.whitelist()
def add_lead_to_prospect(lead, prospect):
	prospect = frappe.get_doc("Prospect", prospect)
	prospect.append("leads", {"lead": lead})
	prospect.save(ignore_permissions=True)

	carry_forward_communication_and_comments = frappe.db.get_single_value(
		"CRM Settings", "carry_forward_communication_and_comments"
	)

	if carry_forward_communication_and_comments:
		copy_comments("Lead", lead, prospect)
		link_communications("Lead", lead, prospect)
	link_open_events("Lead", lead, prospect)

	frappe.msgprint(
		_("Lead {0} has been added to prospect {1}.").format(frappe.bold(lead), frappe.bold(prospect.name)),
		title=_("Lead -> Prospect"),
		indicator="green",
	)


def mark_converted_to_opportunity(lead_name):
	"""Move a Lead to its converted status. Called when an Opportunity is created from it.

	Uses `db_set` on purpose: conversion must not fail because of the conditional mandatory
	rules that apply to the status the Lead is leaving, and the status must stay
	system-only (`validate_conversion_status` rejects it when a user sets it by hand).
	"""
	if not lead_name or not frappe.db.exists("Lead", lead_name):
		return

	if frappe.db.get_value("Lead", lead_name, "status") == CONVERTED_STATUS:
		return

	lead = frappe.get_doc("Lead", lead_name)
	lead.db_set("status", CONVERTED_STATUS, update_modified=False)
	lead.add_comment("Label", _(CONVERTED_STATUS))


@frappe.whitelist()
def revert_from_final_status(lead, reason, comment, return_date):
	"""Return a closed Lead to `Postponed`, keeping a journal of who did it and why.

	The linked Opportunity is deliberately left untouched — this only reopens the Lead so
	it can be corrected or completed.
	"""
	if "Sales Manager" not in frappe.get_roles():
		frappe.throw(_("Only a Sales Manager can return a Lead from a final status"), frappe.PermissionError)

	doc = frappe.get_doc("Lead", lead)

	if doc.status not in FINAL_STATUSES:
		frappe.throw(_("Lead {0} is not in a final status").format(frappe.bold(doc.name)))

	if not (reason and comment and return_date):
		frappe.throw(_("Reason, comment and return date are mandatory"))

	previous_status = doc.status

	doc.append(
		"status_reversals",
		{
			"previous_status": previous_status,
			"reason": reason,
			"comment": comment,
			"reverted_by": frappe.session.user,
			"reverted_on": now_datetime(),
		},
	)
	doc.status = "Postponed"
	doc.return_date = return_date
	doc.hold_reason = reason
	doc.save()

	doc.add_comment(
		"Comment",
		_("Returned from final status {0}. Reason: {1}. Comment: {2}").format(
			_(previous_status), reason, comment
		),
	)

	return doc.name


def has_permission(doc, ptype, user=None, debug=False):
	"""Make Leads in a final status read-only for everyone but a Sales Manager.

	Returns None to defer to the standard role permissions.
	"""
	if ptype not in ("write", "create", "delete"):
		return None

	if doc.get("status") not in FINAL_STATUSES:
		return None

	user = user or frappe.session.user
	if user == "Administrator":
		return None

	roles = frappe.get_roles(user)
	if "Sales Manager" in roles or "System Manager" in roles:
		return None

	return False


def refresh_overdue_flags():
	"""Daily job keeping `next_action_overdue` accurate without touching each Lead."""
	today = nowdate()
	final = list(FINAL_STATUSES)

	frappe.db.sql(
		"""
		update `tabLead`
		set next_action_overdue = 1
		where ifnull(next_action_overdue, 0) = 0
			and next_action_date is not null
			and next_action_date < %(today)s
			and status not in %(final)s
		""",
		{"today": today, "final": final},
	)

	frappe.db.sql(
		"""
		update `tabLead`
		set next_action_overdue = 0
		where ifnull(next_action_overdue, 0) = 1
			and (next_action_date is null or next_action_date >= %(today)s or status in %(final)s)
		""",
		{"today": today, "final": final},
	)
