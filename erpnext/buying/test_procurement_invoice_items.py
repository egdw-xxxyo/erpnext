from unittest import TestCase

from erpnext.buying.procurement_invoice_items import invoice_rate, parse_table


class TestInvoiceVATParsing(TestCase):
	def test_mixed_alphabet_invoice_headers_preserve_item_text(self):
		name = 'Третя рука JM-501 тримач плат з двума "крокодилами" та лупою'
		rows, _ = parse_table(
			[
				["№", "Артиkул", "Нaзвa", "Oд.вим.", "Кiлькiсть", "Цiна", "Cума"],
				["1", "06978-АB", name, "шт.", "10", "188,60", "1886,00"],
			],
			1,
			0,
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["supplier_item_name"], name)
		self.assertEqual(rows[0]["supplier_part_no"], "06978-АB")
		self.assertEqual((rows[0]["qty"], rows[0]["rate"], rows[0]["amount"]), (10, 188.6, 1886))

	def test_english_headers_with_cyrillic_letters(self):
		rows, _ = parse_table(
			[["Itеm Nаmе", "Qtу", "Рriсе еxсl. VАT"], ["Cable", "2", "100"]],
			1,
			0,
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["price_basis"], "exclusive")
		self.assertEqual(invoice_rate(rows[0], True), 120)

	def test_mixed_alphabet_split_vat_header(self):
		rows, _ = parse_table(
			[["Тoвар", "Кiлькiсть", "Цiна бeз"], ["", "", "ПДB"], ["Cable", "2", "100"]],
			1,
			0,
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["price_basis"], "exclusive")

	def test_split_ukrainian_header(self):
		table = [
			["", "", "", "", "", "Ціна без", "Сума без"],
			["№", "Код УКТЗЕД", "Товари (роботи, послуги)", "Кіл-сть", "Од.", "ПДВ", "ПДВ"],
			["1", "8544 49 91 00", "Кабель 8 AWG", "5", "м", "173,00", "865,00"],
		]
		rows, columns = parse_table(table, 1, 0)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["qty"], 5)
		self.assertEqual(rows[0]["rate"], 173)
		self.assertEqual(rows[0]["price_basis"], "exclusive")
		self.assertEqual(rows[0]["supplier_part_no"], "")  # UKTZED is not a supplier article.
		self.assertEqual(invoice_rate(rows[0], True), 207.6)
		continued, _ = parse_table([table[-1]], 2, 0, columns)
		self.assertEqual(continued[0]["price_basis"], "exclusive")

	def test_inclusive_column_is_preferred(self):
		rows, _ = parse_table(
			[
				["Товар", "Кількість", "Ціна без ПДВ", "Ціна з ПДВ"],
				["Кабель", "5", "100", "120"],
			],
			1,
			0,
		)
		self.assertEqual(invoice_rate(rows[0], True), 120)
		self.assertEqual(rows[0]["price_basis"], "inclusive")

	def test_unknown_price_requires_explicit_basis_for_payer(self):
		rows, _ = parse_table([["Item Name", "Qty", "Price"], ["Cable", "2", "100"]], 1, 0)
		self.assertIsNone(invoice_rate(rows[0], True))
		self.assertEqual(invoice_rate(rows[0], True, "inclusive"), 100)
		self.assertEqual(invoice_rate(rows[0], True, "exclusive"), 120)
		self.assertEqual(invoice_rate(rows[0], False), 100)

	def test_missing_rate_and_non_payer(self):
		self.assertIsNone(invoice_rate({"rate": None}, True))
		self.assertEqual(invoice_rate({"rate": 100, "price_basis": "exclusive"}, False), 100)

	def test_header_tax_label_on_next_line(self):
		rows, _ = parse_table(
			[
				["Товар", "К-сть", "Ціна без"],
				["", "", "ПДВ"],
				["Кабель", "2", "100"],
			],
			1,
			0,
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(invoice_rate(rows[0], True), 120)
