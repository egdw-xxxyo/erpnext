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

STOCK_ENTRY_STATUS_BY_EVENT = {
	"on_submit": "Submitted",
	"on_cancel": "Cancelled",
	"on_trash": "Deleted",
}


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
		items: DF.Table[LeadExpenseItem]
		lead: DF.Link
		military_unit: DF.Link | None
		stock_entry: DF.Data | None
		stock_entry_status: DF.Literal["", "Awaiting Warehouse", "Draft", "Submitted", "Cancelled", "Deleted"]
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

		zero_qty = [row for row in self.items if flt(row.qty) <= 0]
		if zero_qty:
			frappe.throw(_("Row #{0}: quantity must be greater than zero").format(zero_qty[0].idx))

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


@frappe.whitelist()
def make_stock_entry(expense: str, warehouse: str):
	frappe.only_for("Stock Manager")
	doc = frappe.get_doc("Lead Expense", expense)
	doc.check_permission("read")
	validate_stock_entry_request(doc, warehouse)

	stock_entry = frappe.new_doc("Stock Entry")
	stock_entry.stock_entry_type = "Material Issue"
	stock_entry.purpose = "Material Issue"
	stock_entry.company = doc.company
	stock_entry.lead_expense = doc.name
	stock_entry.from_warehouse = warehouse
	stock_entry.remarks = _("Expense {0} for Lead {1}: {2}").format(doc.name, doc.lead, doc.expense_type)

	cost_center, expense_account = frappe.get_cached_value(
		"Company", doc.company, ["cost_center", "stock_adjustment_account"]
	)
	for row in doc.items:
		stock_entry.append(
			"items",
			{
				"item_code": row.item_code,
				"qty": row.qty,
				"uom": row.uom,
				"stock_uom": row.uom,
				"conversion_factor": 1.0,
				"transfer_qty": row.qty,
				"s_warehouse": warehouse,
				"cost_center": cost_center,
				"expense_account": expense_account,
			},
		)

	stock_entry.set_stock_entry_type()
	stock_entry.insert()
	doc.db_set({"stock_entry": stock_entry.name, "stock_entry_status": "Draft"})
	return stock_entry.name


def validate_stock_entry_request(doc, warehouse):
	if doc.docstatus != 1 or doc.expense_kind != MATERIALS:
		frappe.throw(_("A stock entry can only be created for a submitted materials expense"))

	active = frappe.db.get_value("Stock Entry", {"lead_expense": doc.name, "docstatus": ["<", 2]}, "name")
	if active:
		frappe.throw(
			_("Expense {0} already has stock entry {1}").format(frappe.bold(doc.name), frappe.bold(active))
		)

	frappe.has_permission("Warehouse", "read", doc=warehouse, throw=True)
	company, is_group, disabled = frappe.db.get_value(
		"Warehouse", warehouse, ["company", "is_group", "disabled"]
	)
	if company != doc.company or is_group or disabled:
		frappe.throw(
			_("Warehouse {0} cannot be used to issue materials for company {1}").format(
				frappe.bold(warehouse), frappe.bold(doc.company)
			)
		)


def sync_stock_entry_status(doc, method=None):
	if not doc.get("lead_expense"):
		return

	frappe.db.set_value(
		"Lead Expense",
		doc.lead_expense,
		{"stock_entry": doc.name, "stock_entry_status": STOCK_ENTRY_STATUS_BY_EVENT[method]},
	)


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
			"stock_entry",
			"stock_entry_status",
		],
		order_by="expense_date desc, creation desc",
	)

	items = frappe.get_all(
		"Lead Expense Item",
		filters={"parenttype": "Lead Expense", "parent": ["in", [e.name for e in expenses]]},
		fields=["parent", "item_name", "item_code", "qty", "uom"],
		order_by="idx asc",
	)

	def with_items(expense):
		return {**expense, "items": [row for row in items if row.parent == expense.name]}

	return {
		"money": [e for e in expenses if e.expense_kind == MONEY],
		"materials": [with_items(e) for e in expenses if e.expense_kind == MATERIALS],
	}
