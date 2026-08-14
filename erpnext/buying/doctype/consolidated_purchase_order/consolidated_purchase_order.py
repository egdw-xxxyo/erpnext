from collections import defaultdict
from urllib.parse import unquote, urlsplit

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import escape_html, flt, get_link_to_form, nowdate

PREPAID_PURCHASE_NOTE = (
	"The materials have already been purchased. Review the attached receipts and verify suppliers and prices."
)


class ConsolidatedPurchaseOrder(Document):
	def validate(self):
		self._set_company_currency()
		self._set_material_request()
		self._set_prepaid_purchase_note()
		self._apply_default_supplier()
		self._calculate_totals()
		self._validate_items()
		self._validate_supplier_invoices()

	def on_submit(self):
		self.create_purchase_orders()

	def before_cancel(self):
		linked_orders = self.get_linked_purchase_orders(submitted_only=True)
		if linked_orders:
			frappe.throw(
				_("Cancel the linked Purchase Orders before cancelling this consolidated order: {0}").format(
					", ".join(linked_orders)
				)
			)

	def _set_company_currency(self):
		if self.company:
			self.currency = frappe.get_cached_value("Company", self.company, "default_currency")

	def _set_material_request(self):
		material_requests = {row.material_request for row in self.items if row.material_request}
		self.material_request = next(iter(material_requests)) if len(material_requests) == 1 else None

	def _set_prepaid_purchase_note(self):
		self.prepaid_purchase_note = _(PREPAID_PURCHASE_NOTE) if self.items_already_purchased else None

	def _apply_default_supplier(self):
		if not self.set_supplier:
			return
		for row in self.items:
			if not row.supplier:
				row.supplier = self.set_supplier

	def _calculate_totals(self):
		self.total_qty = 0
		self.grand_total = 0
		for row in self.items:
			row.amount = flt(row.qty) * flt(row.rate)
			self.total_qty += flt(row.qty)
			self.grand_total += flt(row.amount)

	def _validate_items(self):
		if not self.items:
			frappe.throw(_("Add at least one item."))

		for row in self.items:
			if not row.supplier:
				frappe.throw(_("Row {0}: Supplier is required.").format(row.idx))
			if (
				row.item_code
				and frappe.get_cached_value("Item", row.item_code, "is_stock_item")
				and not row.warehouse
			):
				frappe.throw(
					_("Row #{1}: Warehouse is mandatory for stock Item {0}").format(
						frappe.bold(row.item_code), row.idx
					)
				)
			if flt(row.qty) <= 0:
				frappe.throw(_("Row {0}: Quantity must be greater than zero.").format(row.idx))
			if flt(row.rate) < 0:
				frappe.throw(_("Row {0}: Rate cannot be negative.").format(row.idx))
			if not row.schedule_date:
				frappe.throw(_("Row {0}: Required By date is required.").format(row.idx))

	def _validate_supplier_invoices(self):
		allowed_suppliers = {row.supplier for row in self.items if row.supplier}
		for row in self.supplier_invoices:
			row.invoice_document = self._get_supplier_invoice_file_name(row.invoice_pdf)
			if not row.invoice_pdf:
				frappe.throw(_("Row {0}: Attach a PDF receipt.").format(row.idx))
			if not row.supplier:
				frappe.throw(_("Row {0}: Supplier is required for the purchase receipt.").format(row.idx))
			if row.supplier not in allowed_suppliers:
				frappe.throw(
					_("Row {0}: Select a supplier used in the order items.").format(row.idx)
				)
			if row.invoice_pdf and not urlsplit(row.invoice_pdf).path.lower().endswith(".pdf"):
				frappe.throw(
					_("The supplier invoice must be a PDF file."),
					title=_("Unsupported File Format"),
				)

	@staticmethod
	def _get_supplier_invoice_file_name(file_url):
		if not file_url:
			return None
		return unquote(urlsplit(file_url).path.rsplit("/", 1)[-1])

	def create_purchase_orders(self):
		groups = defaultdict(list)
		for row in self.items:
			if not row.purchase_order:
				groups[row.supplier].append(row)

		for supplier, rows in groups.items():
			purchase_order = self._make_purchase_order(supplier, rows)
			for source_row, target_row in zip(rows, purchase_order.items, strict=True):
				frappe.db.set_value(
					source_row.doctype,
					source_row.name,
					{
						"purchase_order": purchase_order.name,
						"purchase_order_item": target_row.name,
					},
					update_modified=False,
				)
				source_row.purchase_order = purchase_order.name
				source_row.purchase_order_item = target_row.name

			order_link = get_link_to_form("Purchase Order", purchase_order.name, purchase_order.name)
			self.add_comment(
				"Info",
				text=_("Created and submitted Purchase Order {0} for supplier {1}.").format(
					order_link, escape_html(supplier)
				),
			)

	def _make_purchase_order(self, supplier, rows):
		purchase_order = frappe.get_doc(
			{
				"doctype": "Purchase Order",
				"supplier": supplier,
				"company": self.company,
				"transaction_date": self.transaction_date or nowdate(),
				"schedule_date": max(row.schedule_date for row in rows),
				"currency": self.currency,
				"conversion_rate": 1,
				"custom_consolidated_purchase_order": self.name,
				"custom_items_already_purchased": self.items_already_purchased,
				"custom_prepaid_purchase_note": self.prepaid_purchase_note,
			}
		)
		for row in rows:
			purchase_order.append(
				"items",
				{
					"item_code": row.item_code,
					"item_name": row.item_name,
					"description": row.description,
					"qty": row.qty,
					"uom": row.uom,
					"schedule_date": row.schedule_date,
					"warehouse": row.warehouse,
					"rate": row.rate,
					"project": row.project,
					"material_request": row.material_request,
					"material_request_item": row.material_request_item,
					"custom_consolidated_purchase_order_item": row.name,
				},
			)

		purchase_order.flags.ignore_permissions = True
		purchase_order.insert()
		purchase_order.submit()
		return purchase_order

	def get_linked_purchase_orders(self, submitted_only=False):
		filters = {"custom_consolidated_purchase_order": self.name}
		if submitted_only:
			filters["docstatus"] = 1
		return frappe.get_all("Purchase Order", filters=filters, pluck="name")


@frappe.whitelist()
def get_purchase_invoice_options(source_name):
	doc = frappe.get_doc("Consolidated Purchase Order", source_name)
	doc.check_permission("read")
	return frappe.get_all(
		"Purchase Order",
		filters={
			"custom_consolidated_purchase_order": source_name,
			"docstatus": 1,
			"status": ["not in", ["Closed", "Cancelled"]],
			"per_billed": ["<", 100],
		},
		fields=["name", "supplier", "supplier_name", "grand_total", "currency", "per_billed"],
		order_by="supplier_name asc, name asc",
	)


@frappe.whitelist()
def make_purchase_invoice(source_name, supplier=None):
	supplier = supplier or (frappe.flags.args or {}).get("supplier")
	if not supplier:
		frappe.throw(_("Supplier is required for all selected Items"))

	doc = frappe.get_doc("Consolidated Purchase Order", source_name)
	doc.check_permission("read")
	if doc.docstatus != 1:
		frappe.throw(_("Submit the consolidated order before creating a Purchase Invoice."))

	purchase_order = frappe.db.get_value(
		"Purchase Order",
		{
			"custom_consolidated_purchase_order": source_name,
			"supplier": supplier,
			"docstatus": 1,
			"status": ["not in", ["Closed", "Cancelled"]],
			"per_billed": ["<", 100],
		},
		"name",
	)
	if not purchase_order:
		frappe.throw(_("No billable Purchase Order was found for supplier {0}.").format(supplier))

	from erpnext.buying.doctype.purchase_order.purchase_order import get_mapped_purchase_invoice

	invoice = get_mapped_purchase_invoice(purchase_order)
	invoice.custom_consolidated_purchase_order = source_name
	if doc.items_already_purchased:
		invoice.is_paid = 1
	return invoice
