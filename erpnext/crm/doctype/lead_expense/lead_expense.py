# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

import erpnext
from erpnext.stock.doctype.item.item import get_item_defaults

MONEY = "Money"
MATERIALS = "Materials"

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
		stock_entry_status: DF.Literal["", "Draft", "Submitted", "Cancelled", "Deleted"]
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

		stock_entry = make_stock_entry(self)
		self.db_set({"stock_entry": stock_entry.name, "stock_entry_status": "Draft"})

	def on_cancel(self):
		drafts = frappe.get_all(
			"Stock Entry", filters={"lead_expense": self.name, "docstatus": 0}, pluck="name"
		)
		for name in drafts:
			frappe.delete_doc("Stock Entry", name, ignore_permissions=True)


def make_stock_entry(expense):
	stock_entry = frappe.new_doc("Stock Entry")
	stock_entry.stock_entry_type = "Material Issue"
	stock_entry.purpose = "Material Issue"
	stock_entry.company = expense.company
	stock_entry.lead_expense = expense.name
	stock_entry.remarks = _("Expense {0} for Lead {1}: {2}").format(
		expense.name, expense.lead, expense.expense_type
	)

	cost_center, expense_account = frappe.get_cached_value(
		"Company", expense.company, ["cost_center", "stock_adjustment_account"]
	)
	for row in expense.items:
		stock_entry.append(
			"items",
			{
				"item_code": row.item_code,
				"qty": row.qty,
				"uom": row.uom,
				"stock_uom": row.uom,
				"conversion_factor": 1.0,
				"transfer_qty": row.qty,
				"s_warehouse": default_warehouse(row.item_code, expense.company),
				"cost_center": cost_center,
				"expense_account": expense_account,
			},
		)

	stock_entry.set_stock_entry_type()
	stock_entry.insert(ignore_permissions=True)
	return stock_entry


def default_warehouse(item_code, company):
	settings_warehouse = frappe.db.get_single_value("Stock Settings", "default_warehouse")
	candidates = (
		get_item_defaults(item_code, company).get("default_warehouse"),
		settings_warehouse
		if settings_warehouse and frappe.db.get_value("Warehouse", settings_warehouse, "company") == company
		else None,
		frappe.db.get_value(
			"Warehouse", {"company": company, "is_group": 0, "disabled": 0}, "name", order_by="name asc"
		),
	)
	warehouse = next((w for w in candidates if w), None)
	if not warehouse:
		frappe.throw(
			_("Company {0} has no warehouse to issue {1} from").format(
				frappe.bold(company), frappe.bold(item_code)
			)
		)
	return warehouse


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
