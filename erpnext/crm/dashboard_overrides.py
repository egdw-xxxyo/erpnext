# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Dashboard connection extensions for core doctypes, wired via the
`override_doctype_dashboards` hook in hooks.py."""

import frappe
from frappe import _


def get_contact_dashboard_data(data=None):
	"""Make Contact the CRM hub: surface its WhatsApp conversation and related
	Lead/Customer/Opportunity/Quotation/Sales Order documents."""
	data = data or frappe._dict()
	data.setdefault("fieldname", "contact")
	data.setdefault("transactions", [])
	data.setdefault("non_standard_fieldnames", {})

	# These doctypes reference a Contact through non-default fieldnames.
	data["non_standard_fieldnames"].update(
		{
			"WhatsApp Chat": "contact",
			"Opportunity": "contact_person",
			"Quotation": "contact_person",
			"Sales Order": "contact_person",
		}
	)

	existing = {item for group in data["transactions"] for item in group.get("items", [])}
	for group in (
		{"label": _("WhatsApp"), "items": ["WhatsApp Chat"]},
		{"label": _("Sales"), "items": ["Opportunity", "Quotation", "Sales Order"]},
	):
		group["items"] = [d for d in group["items"] if d not in existing]
		if group["items"]:
			data["transactions"].append(group)

	return data


def get_lead_dashboard_data(data=None):
	data = data or frappe._dict()
	data.setdefault("transactions", [])
	data.setdefault("non_standard_fieldnames", {})
	data.setdefault("internal_and_external_links", {})

	data["internal_and_external_links"]["Customer"] = "customer"
	data["non_standard_fieldnames"]["Customer"] = "lead_name"

	existing = {item for group in data["transactions"] for item in group.get("items", [])}
	if "Customer" not in existing:
		data["transactions"].insert(0, {"label": _("Customer"), "items": ["Customer"]})
	if "Lead Expense" not in existing:
		data["transactions"].append({"label": _("Expenses"), "items": ["Lead Expense"]})

	return data
