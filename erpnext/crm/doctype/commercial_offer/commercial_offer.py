import base64

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext.crm.commercial_offer_fields import price_in_words, resolve_rows, throw_if_unresolved


class CommercialOffer(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.crm.doctype.commercial_offer_field.commercial_offer_field import CommercialOfferField
		from erpnext.crm.doctype.commercial_offer_item.commercial_offer_item import CommercialOfferItem

		amended_from: DF.Link | None
		base_template: DF.Link | None
		classification_text: DF.SmallText | None
		company: DF.Link
		currency: DF.Link
		customer: DF.Link | None
		date: DF.Date
		delivery_days: DF.Int
		disabled: DF.Check
		spec_fields: DF.Table[CommercialOfferField]
		is_template: DF.Check
		item_name: DF.Data | None
		items: DF.Table[CommercialOfferItem]
		main_item: DF.Link
		naming_series: DF.Literal["КП-.YYYY.-.###"]
		pdf_title: DF.Data | None
		price: DF.Currency
		price_in_words: DF.SmallText | None
		product_type: DF.Data | None
		qty: DF.Int
		signer_name: DF.Data | None
		signer_title: DF.Data | None
		tagline: DF.SmallText | None
		template_name: DF.Data | None
		technical_state: DF.Data | None
		valid_days: DF.Int
	# end: auto-generated types

	def onload(self):
		if self.docstatus == 0:
			resolve_rows(self)

	def before_validate(self):
		self.company = self.company or frappe.defaults.get_user_default("Company")

	def validate(self):
		self.validate_positive("qty", "delivery_days", "valid_days")
		resolve_rows(self)
		self.price_in_words = price_in_words(self.price, self.currency)

	def before_submit(self):
		if self.is_template:
			frappe.throw(_("A template cannot be submitted. Create an offer from it first."))
		throw_if_unresolved(resolve_rows(self))
		if not self.items:
			frappe.throw(_("Add the delivery set before submitting."))

	def validate_positive(self, *fieldnames):
		for fieldname in fieldnames:
			if (self.get(fieldname) or 0) <= 0:
				frappe.throw(_("{0} must be greater than zero.").format(_(self.meta.get_label(fieldname))))


@frappe.whitelist()
def make_from_template(template):
	source = frappe.get_doc("Commercial Offer", template)
	source.check_permission("read")
	if not source.is_template:
		frappe.throw(_("{0} is not a template.").format(template))

	offer = frappe.copy_doc(source)
	offer.is_template = 0
	offer.template_name = None
	offer.base_template = template
	offer.date = frappe.utils.nowdate()
	offer.price_in_words = None
	return offer


@frappe.whitelist()
def preview_pdf(doc):
	frappe.has_permission("Commercial Offer", "read", throw=True)
	offer = frappe.get_doc(frappe.parse_json(doc))
	if offer.is_new():
		offer.name = "—"
	elif offer.docstatus == 0:
		frappe.get_doc("Commercial Offer", offer.name).check_permission("read")
	offer.company = offer.company or frappe.defaults.get_user_default("Company")
	resolve_rows(offer)
	offer.price_in_words = price_in_words(offer.price, offer.currency)

	lang = frappe.local.lang
	frappe.local.lang = "uk"
	try:
		pdf = frappe.get_print(
			"Commercial Offer",
			offer.name,
			print_format="Commercial Offer",
			as_pdf=True,
			doc=offer,
			no_letterhead=1,
		)
	finally:
		frappe.local.lang = lang
	return base64.b64encode(pdf).decode()
