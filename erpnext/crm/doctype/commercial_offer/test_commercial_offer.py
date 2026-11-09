import frappe
from frappe.tests import IntegrationTestCase

from erpnext.crm.commercial_offer_fields import resolve_rows


class TestCommercialOffer(IntegrationTestCase):
	def make_offer(self, rows):
		offer = frappe.new_doc("Commercial Offer")
		offer.main_item = frappe.db.get_value("Item", {}, "name")
		for row in rows:
			offer.append("spec_fields", row)
		return offer

	def test_literal_and_override(self):
		offer = self.make_offer(
			[
				{"section": "Specification", "label": "Тип", "value": "оптичний"},
				{
					"section": "Specification",
					"label": "Висота",
					"value": "10",
					"override": 1,
					"custom_value": "50",
				},
			]
		)
		self.assertEqual(resolve_rows(offer), [])
		self.assertEqual([row.preview for row in offer.spec_fields], ["оптичний", "50"])

	def test_formula_reads_other_rows(self):
		offer = self.make_offer(
			[
				{"section": "Specification", "label": "Дальність", "value": "20"},
				{"section": "Specification", "label": "Подвійна", "value": "={Дальність}*2"},
			]
		)
		self.assertEqual(resolve_rows(offer), [])
		self.assertEqual(offer.spec_fields[1].preview, "40")

	def test_unsafe_formula_is_unresolved(self):
		offer = self.make_offer(
			[{"section": "Specification", "label": "X", "value": "=__import__('os').getcwd()"}]
		)
		self.assertEqual([row.label for row in resolve_rows(offer)], ["X"])

	def test_price_in_words_is_ukrainian(self):
		from erpnext.crm.commercial_offer_fields import price_in_words

		self.assertIn("тисяч", price_in_words(121000, "UAH"))

	def test_make_from_template_copies_tables(self):
		from erpnext.crm.doctype.commercial_offer.commercial_offer import make_from_template

		template = self.make_offer([{"section": "Specification", "label": "Тип", "value": "оптичний"}])
		template.update(
			{"is_template": 1, "template_name": "T", "company": frappe.db.get_value("Company", {}, "name")}
		)
		template.insert()

		offer = make_from_template(template.name)
		self.assertFalse(offer.is_template)
		self.assertEqual(offer.base_template, template.name)
		self.assertEqual([row.label for row in offer.spec_fields], ["Тип"])

	def test_template_cannot_be_submitted(self):
		template = self.make_offer([])
		template.update(
			{"is_template": 1, "template_name": "T2", "company": frappe.db.get_value("Company", {}, "name")}
		)
		template.insert()
		with self.assertRaises(frappe.ValidationError):
			template.submit()

	def test_price_in_words_without_price(self):
		from erpnext.crm.commercial_offer_fields import price_in_words

		self.assertEqual(price_in_words(None, "UAH"), "")
