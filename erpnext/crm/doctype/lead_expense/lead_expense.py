# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
from frappe.model.document import Document
from frappe.utils import flt

import erpnext

MONEY = "Money"
MATERIALS = "Materials"
AWAITING_WAREHOUSE = "Awaiting Warehouse"
HAS_DRAFT = "Has Draft"
PARTIALLY_ISSUED = "Partially Issued"
FULLY_ISSUED = "Fully Issued"
CLOSED = "Partially Issued (Closed)"


class LeadExpense(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.crm.doctype.lead_expense_item.lead_expense_item import LeadExpenseItem

		amended_from: DF.Link | None
		amount: DF.Currency
		company: DF.Link
		currency: DF.Link | None
		description: DF.SmallText | None
		expense_date: DF.Date
		expense_kind: DF.Literal["", "Money", "Materials"]
		expense_type: DF.Link
		issue_closed: DF.Check
		items: DF.Table[LeadExpenseItem]
		lead: DF.Link
		military_unit: DF.Link | None
		stock_entry_status: DF.Literal[
			"",
			"Awaiting Warehouse",
			"Has Draft",
			"Partially Issued",
			"Fully Issued",
			"Partially Issued (Closed)",
		]
	# end: auto-generated types

	def before_validate(self):
		self.company = self.company or erpnext.get_default_company()
		self.expense_kind = frappe.db.get_value("Lead Expense Type", self.expense_type, "expense_kind")

	def validate(self):
		self.validate_expense_type()
		if self.expense_kind == MONEY:
			self.validate_money()
		else:
			self.validate_materials()

	def validate_expense_type(self):
		if frappe.db.get_value("Lead Expense Type", self.expense_type, "disabled"):
			frappe.throw(_("Expense Type {0} is disabled").format(frappe.bold(self.expense_type)))

	def validate_money(self):
		self.items = []
		if flt(self.amount) <= 0:
			frappe.throw(_("{0} must be greater than zero").format(frappe.bold(_("Amount"))))

	def validate_materials(self):
		self.amount = 0
		if not self.items:
			frappe.throw(_("Add at least one item to a materials expense"))

		non_stock = [
			row for row in self.items if not frappe.db.get_value("Item", row.item_code, "is_stock_item")
		]
		if non_stock:
			frappe.throw(
				_("Row #{0}: {1} is not a stock item").format(
					non_stock[0].idx, frappe.bold(non_stock[0].item_code)
				)
			)

		codes = [row.item_code for row in self.items]
		duplicate = next((row for i, row in enumerate(self.items) if row.item_code in codes[:i]), None)
		if duplicate:
			frappe.throw(
				_("Row #{0}: {1} is already listed").format(duplicate.idx, frappe.bold(duplicate.item_code))
			)

		zero_qty = [row for row in self.items if flt(row.qty) <= 0]
		if zero_qty:
			frappe.throw(_("Row #{0}: quantity must be greater than zero").format(zero_qty[0].idx))

	def onload(self):
		if self.docstatus != 1 or self.expense_kind != MATERIALS:
			return

		entries = stock_entries(self.name)
		self.set_onload("can_issue", not self.issue_closed and any(remaining_quantities(self).values()))
		self.set_onload(
			"can_close",
			not self.issue_closed
			and self.stock_entry_status != FULLY_ISSUED
			and not any(entry.docstatus == 0 for entry in entries),
		)

	def on_submit(self):
		if self.expense_kind != MATERIALS:
			return

		self.db_set("stock_entry_status", AWAITING_WAREHOUSE)
		notify_stock_managers(self)

	def on_cancel(self):
		drafts = frappe.get_all(
			"Stock Entry", filters={"lead_expense": self.name, "docstatus": 0}, pluck="name"
		)
		for name in drafts:
			frappe.delete_doc("Stock Entry", name, ignore_permissions=True)
		self.db_set("stock_entry_status", None)


def users_with_role(role):
	return set(
		frappe.get_all(
			"Has Role", filters={"parenttype": "User", "role": role}, pluck="parent", distinct=True
		)
	)


def stock_managers():
	enabled = set(frappe.get_all("User", filters={"enabled": 1, "user_type": "System User"}, pluck="name"))
	return sorted((users_with_role("Stock Manager") - users_with_role("System Manager")) & enabled)


def notify_stock_managers(expense):
	recipients = stock_managers()
	if not recipients:
		return

	enqueue_create_notification(
		recipients,
		{
			"type": "Alert",
			"document_type": "Lead Expense",
			"document_name": expense.name,
			"from_user": frappe.session.user,
			"subject": _("Materials expense {0} for Lead {1} is waiting for a warehouse").format(
				frappe.bold(expense.name), frappe.bold(expense.lead)
			),
		},
	)


def stock_entries(expense_name, exclude=None):
	filters = {"lead_expense": expense_name, "docstatus": ["<", 2]}
	if exclude:
		filters["name"] = ["!=", exclude]
	return frappe.get_all(
		"Stock Entry", filters=filters, fields=["name", "docstatus"], order_by="creation asc"
	)


def stock_entry_rows(entries):
	if not entries:
		return []
	return frappe.get_all(
		"Stock Entry Detail",
		filters={"parenttype": "Stock Entry", "parent": ["in", [entry.name for entry in entries]]},
		fields=["parent", "item_code", "transfer_qty"],
	)


def quantities_by_item(rows, qty_field):
	return {
		item_code: flt(sum(flt(row.get(qty_field)) for row in rows if row.item_code == item_code), 6)
		for item_code in {row.item_code for row in rows}
	}


def remaining_quantities(expense, exclude=None):
	taken = quantities_by_item(stock_entry_rows(stock_entries(expense.name, exclude)), "transfer_qty")
	return {
		item_code: max(flt(qty - taken.get(item_code, 0), 6), 0)
		for item_code, qty in quantities_by_item(expense.items, "qty").items()
	}


def issue_status(expense, entries, issued):
	required = quantities_by_item(expense.items, "qty")
	if all(issued.get(item_code, 0) >= qty for item_code, qty in required.items()):
		return FULLY_ISSUED
	if expense.issue_closed:
		return CLOSED
	if any(entry.docstatus == 0 for entry in entries):
		return HAS_DRAFT
	if any(issued.values()):
		return PARTIALLY_ISSUED
	return AWAITING_WAREHOUSE


def update_issue_status(expense_name, exclude=None):
	expense = frappe.get_doc("Lead Expense", expense_name)
	if expense.docstatus != 1 or expense.expense_kind != MATERIALS:
		return

	entries = stock_entries(expense.name, exclude)
	submitted = [entry for entry in entries if entry.docstatus == 1]
	issued = quantities_by_item(stock_entry_rows(submitted), "transfer_qty")

	for row in expense.items:
		row.db_set("issued_qty", issued.get(row.item_code, 0), update_modified=False)
	expense.db_set("stock_entry_status", issue_status(expense, entries, issued), update_modified=False)


def sync_stock_entry_status(doc, method=None):
	if not doc.get("lead_expense"):
		return

	update_issue_status(doc.lead_expense, exclude=doc.name if method == "on_trash" else None)


def validate_open_materials_expense(expense):
	if expense.docstatus != 1 or expense.expense_kind != MATERIALS:
		frappe.throw(_("A stock entry can only be created for a submitted materials expense"))
	if expense.issue_closed:
		frappe.throw(_("The remainder of expense {0} is closed").format(frappe.bold(expense.name)))


def validate_stock_entry(doc, method=None):
	if not doc.get("lead_expense"):
		return

	expense = frappe.get_doc("Lead Expense", doc.lead_expense)
	validate_open_materials_expense(expense)

	if doc.purpose != "Material Issue" or doc.company != expense.company:
		frappe.throw(
			_("A stock entry for expense {0} must be a Material Issue of company {1}").format(
				frappe.bold(expense.name), frappe.bold(expense.company)
			)
		)

	remaining = remaining_quantities(expense, exclude=doc.name)
	foreign = next((row for row in doc.items if row.item_code not in remaining), None)
	if foreign:
		frappe.throw(
			_("Row #{0}: {1} is not part of expense {2}").format(
				foreign.idx, frappe.bold(foreign.item_code), frappe.bold(expense.name)
			)
		)

	issuing = quantities_by_item(doc.items, "transfer_qty")
	excess = next((item for item, qty in issuing.items() if qty > remaining[item] + 1e-6), None)
	if excess:
		frappe.throw(
			_("Only {0} of {1} is left to issue for expense {2}").format(
				frappe.bold(f"{remaining[excess]:g}"), frappe.bold(excess), frappe.bold(expense.name)
			),
			title=_("Quantity Exceeded"),
		)


@frappe.whitelist()
def make_stock_entry(source_name: str, target_doc: object | None = None):
	frappe.only_for("Stock Manager")
	doc = frappe.get_doc("Lead Expense", source_name)
	doc.check_permission("read")
	validate_open_materials_expense(doc)

	remaining = remaining_quantities(doc)
	rows = [row for row in doc.items if remaining.get(row.item_code)]
	if not rows:
		frappe.throw(_("Nothing is left to issue for expense {0}").format(frappe.bold(doc.name)))

	stock_entry = frappe.new_doc("Stock Entry")
	stock_entry.stock_entry_type = "Material Issue"
	stock_entry.purpose = "Material Issue"
	stock_entry.company = doc.company
	stock_entry.lead_expense = doc.name
	stock_entry.remarks = _("Expense {0} for Lead {1}: {2}").format(doc.name, doc.lead, doc.expense_type)

	cost_center, expense_account = frappe.get_cached_value(
		"Company", doc.company, ["cost_center", "stock_adjustment_account"]
	)
	for row in rows:
		qty = remaining[row.item_code]
		stock_entry.append(
			"items",
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"qty": qty,
				"uom": row.uom,
				"stock_uom": row.uom,
				"conversion_factor": 1.0,
				"transfer_qty": qty,
				"cost_center": cost_center,
				"expense_account": expense_account,
			},
		)

	stock_entry.set_stock_entry_type()
	return stock_entry


@frappe.whitelist()
def close_remainder(expense: str):
	frappe.only_for("Stock Manager")
	doc = frappe.get_doc("Lead Expense", expense)
	doc.check_permission("read")
	validate_open_materials_expense(doc)

	if any(entry.docstatus == 0 for entry in stock_entries(doc.name)):
		frappe.throw(
			_("Submit or delete the draft stock entries of expense {0} first").format(frappe.bold(doc.name))
		)

	doc.db_set("issue_closed", 1)
	update_issue_status(doc.name)


@frappe.whitelist()
def get_lead_expenses(lead: str):
	frappe.has_permission("Lead", "read", doc=lead, throw=True)

	expenses = frappe.get_all(
		"Lead Expense",
		filters={"lead": lead, "docstatus": ["<", 2]},
		fields=[
			"name",
			"docstatus",
			"expense_date",
			"expense_type",
			"expense_kind",
			"amount",
			"currency",
			"description",
			"stock_entry_status",
		],
		order_by="expense_date desc, creation desc",
	)

	items = frappe.get_all(
		"Lead Expense Item",
		filters={"parenttype": "Lead Expense", "parent": ["in", [e.name for e in expenses]]},
		fields=["parent", "item_name", "item_code", "qty", "issued_qty", "uom"],
		order_by="idx asc",
	)

	entries = frappe.get_all(
		"Stock Entry",
		filters={"lead_expense": ["in", [e.name for e in expenses]], "docstatus": ["<", 2]},
		fields=["name", "docstatus", "lead_expense"],
		order_by="creation asc",
	)

	def with_items(expense):
		return {
			**expense,
			"items": [row for row in items if row.parent == expense.name],
			"stock_entries": [entry for entry in entries if entry.lead_expense == expense.name],
		}

	return {
		"money": [e for e in expenses if e.expense_kind == MONEY],
		"materials": [with_items(e) for e in expenses if e.expense_kind == MATERIALS],
	}
