from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.buying.doctype.supplier_item_alias.supplier_item_alias import alias_key
from erpnext.buying.procurement_invoice_items import (
	header_columns,
	parse_number,
	parse_table,
	read_invoice_items,
)
from erpnext.buying.procurement_supplier_item_matching import (
	_check_order,
	_check_prefill_order,
	_fill_canonical,
	_prefill_context,
	confirm_matches,
	confirm_prefill_matches,
	get_prefill_preview,
	prepare_prefill_items,
	suggest_rows,
)

MODULE = "erpnext.buying.procurement_supplier_item_matching"


def make_invoice_pdf(with_text=True):
	"""Small valid vector PDF exercises actual pdfplumber, not a mocked table."""
	stream = ""
	if with_text:
		for x in (30, 110, 260, 320, 380):
			stream += f"{x} 660 m {x} 710 l S\n"
		for y in (660, 685, 710):
			stream += f"30 {y} m 380 {y} l S\n"
		for y, values in (
			(693, ("Part Number", "Item Name", "Qty", "Price")),
			(668, ("A-1", "Supplier cable", "10", "5.00")),
		):
			for x, value in zip((35, 115, 265, 325), values, strict=True):
				stream += f"BT /F1 9 Tf {x} {y} Td ({value}) Tj ET\n"
	objects = [
		b"<< /Type /Catalog /Pages 2 0 R >>",
		b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
		b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
		b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
		f"<< /Length {len(stream)} >>\nstream\n{stream}endstream".encode(),
	]
	content = b"%PDF-1.4\n"
	offsets = [0]
	for index, obj in enumerate(objects, 1):
		offsets.append(len(content))
		content += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
	xref = len(content)
	content += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
	content += b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets[1:])
	content += f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
	return content


class TestProcurementSupplierItemMatching(IntegrationTestCase):
	def test_prefill_exact_aliases_preselect_but_conflicts_and_unknowns_do_not(self):
		aliases = [
			frappe._dict(item_code="ITEM-A", supplier_item_name=" SUPPLIER  cable ", supplier_part_no="A-1"),
			frappe._dict(item_code="ITEM-B", supplier_item_name="Another product", supplier_part_no="B-2"),
		]
		rows = [
			self.invoice_row(),
			{**self.invoice_row(), "supplier_item_name": "New name", "supplier_part_no": "a-1"},
			{**self.invoice_row(), "supplier_part_no": "B-2"},
			{**self.invoice_row(), "supplier_item_name": "Unknown", "supplier_part_no": "Unknown"},
		]
		with (
			patch(f"{MODULE}._prefill_context"),
			patch(f"{MODULE}._known_items", return_value=aliases) as known,
			patch(
				f"{MODULE}.read_invoice_items", side_effect=lambda _: {"rows": [row.copy() for row in rows]}
			),
			patch(f"{MODULE}.frappe.get_list", return_value=["ITEM-A", "ITEM-B"]) as allowed,
		):
			preview = get_prefill_preview("SUP", "/invoice.pdf", {})
			self.assertEqual(
				[row["suggested_item_code"] for row in preview["rows"]], ["ITEM-A", "ITEM-A", None, None]
			)
			known.assert_called_once_with("SUP")
			allowed.return_value = []
			self.assertTrue(
				all(
					row["suggested_item_code"] is None
					for row in get_prefill_preview("SUP", "/invoice.pdf", {})["rows"]
				)
			)

	def test_prefill_is_draft_only_and_requires_write_permission(self):
		for status, state in (
			(1, "Проведено"),
			(0, "Фінальне погодження"),
			(0, "Перевірка підрозділу"),
			(0, "Погоджено"),
		):
			doc = MagicMock(docstatus=status, workflow_state=state)
			with self.assertRaises(frappe.ValidationError):
				_check_prefill_order(doc)
			doc.check_permission.assert_called_once_with("write")
		doc = MagicMock(docstatus=0, workflow_state="Чернетка")
		doc.check_permission.side_effect = frappe.PermissionError
		with self.assertRaises(frappe.PermissionError):
			_check_prefill_order(doc)

	def test_new_draft_prefill_requires_create_and_own_file(self):
		doc = MagicMock(docstatus=0, workflow_state="Чернетка")
		doc.is_new.return_value = True
		doc.supplier_invoices = [frappe._dict(supplier="SUP", invoice_pdf="/invoice.pdf")]
		file = MagicMock(attached_to_doctype=None, owner="buyer@example.com")
		with (
			patch(
				f"{MODULE}.frappe.get_doc",
				side_effect=lambda *args: doc if isinstance(args[0], dict) else file,
			),
			patch(f"{MODULE}.frappe.session", frappe._dict(user="buyer@example.com")),
			patch(f"{MODULE}.frappe.get_roles", return_value=["Закупівельник"]),
		):
			self.assertIs(
				_prefill_context("SUP", "/invoice.pdf", {"doctype": "Consolidated Purchase Order"}), doc
			)
			doc.check_permission.assert_called_once_with("create")
			file.owner = "other@example.com"
			with self.assertRaises(frappe.PermissionError):
				_prefill_context("SUP", "/invoice.pdf", {"doctype": "Consolidated Purchase Order"})
			file.owner = "buyer@example.com"
			file.attached_to_doctype = "Purchase Invoice"
			with self.assertRaises(frappe.PermissionError):
				_prefill_context("SUP", "/invoice.pdf", {"doctype": "Consolidated Purchase Order"})

	def test_prefill_returns_only_our_item_data_and_invoice_supplier(self):
		doc = MagicMock(
			docstatus=0, workflow_state="Чернетка", set_schedule_date="2026-10-09", set_warehouse="WH"
		)
		doc.items = [frappe._dict(supplier="SUP", related_supplier="RELATED")]
		item = MagicMock(disabled=0, has_variants=0, is_purchase_item=1)
		item.name = "ITEM-A"
		item.item_name = "Our name"
		item.description = "Our description"
		item.stock_uom = "Nos"
		with (
			patch(f"{MODULE}._prefill_context", return_value=doc),
			patch(f"{MODULE}.read_invoice_items", return_value={"rows": [self.invoice_row()]}),
			patch(f"{MODULE}.frappe.get_doc", return_value=item),
			patch(
				"erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.get_allowed_related_supplier_names",
				return_value=["RELATED"],
			),
		):
			result = prepare_prefill_items(
				"SUP",
				"/invoice.pdf",
				{"doctype": "Consolidated Purchase Order"},
				[
					{
						"invoice_row": "1:0:1",
						"item_code": "ITEM-A",
						"supplier": "FAKE",
						"qty": 100,
						"rate": 500,
					}
				],
			)
			imported = prepare_prefill_items(
				"SUP",
				"/invoice.pdf",
				{},
				[{"invoice_row": "1:0:1", "item_code": "ITEM-A", "qty": 999, "rate": 999}],
				import_values="1",
			)
			self.assertEqual(imported["items"][0]["qty"], 10)
			self.assertEqual(imported["items"][0]["rate"], 5)
			self.assertFalse(imported["missing_values"])
			with patch(f"{MODULE}.frappe.db.get_value", return_value=1):
				for basis, confirmation, expected in (
					("exclusive", "", 6),
					("inclusive", "", 5),
					("unknown", "exclusive", 6),
					("unknown", "inclusive", 5),
					("unknown", "", None),
				):
					with patch(
						f"{MODULE}.read_invoice_items",
						return_value={"rows": [{**self.invoice_row(), "price_basis": basis}]},
					):
						vat_result = prepare_prefill_items(
							"SUP",
							"/invoice.pdf",
							{},
							[{"invoice_row": "1:0:1", "item_code": "ITEM-A"}],
							import_values=True,
							unknown_price_basis=confirmation,
						)
						self.assertEqual(vat_result["items"][0].get("rate"), expected)
						self.assertEqual(vat_result["missing_values"], expected is None)
			with patch(
				f"{MODULE}.read_invoice_items", return_value={"rows": [{**self.invoice_row(), "rate": None}]}
			):
				missing = prepare_prefill_items(
					"SUP",
					"/invoice.pdf",
					{},
					[{"invoice_row": "1:0:1", "item_code": "ITEM-A"}],
					import_values=True,
				)
				self.assertNotIn("rate", missing["items"][0])
				self.assertEqual(missing["items"][0]["qty"], 10)
				self.assertTrue(missing["missing_values"])
		self.assertEqual(
			result["items"][0],
			{
				"supplier": "SUP",
				"related_supplier": "RELATED",
				"item_code": "ITEM-A",
				"item_name": "Our name",
				"description": "Our description",
				"uom": "Nos",
				"schedule_date": "2026-10-09",
				"warehouse": "WH",
			},
		)
		item.save.assert_not_called()
		doc.save.assert_not_called()

	def test_prefill_rejects_unknown_pdf_rows_and_disabled_items(self):
		doc = MagicMock(docstatus=0, workflow_state="Чернетка")
		doc.items = []
		with (
			patch(f"{MODULE}._prefill_context", return_value=doc),
			patch(f"{MODULE}.read_invoice_items", return_value={"rows": [self.invoice_row()]}),
			patch(f"{MODULE}.frappe.get_doc", return_value=MagicMock(disabled=1)),
			patch(
				"erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.get_allowed_related_supplier_names",
				return_value=[],
			),
		):
			for mappings in (
				[{"invoice_row": "FAKE", "item_code": "ITEM-A"}],
				[{"invoice_row": "1:0:1", "item_code": "ITEM-A"}],
				{"invoice_row": "FAKE"},
			):
				with self.assertRaises(frappe.ValidationError):
					prepare_prefill_items("SUP", "/invoice.pdf", {}, mappings)

	@patch("erpnext.buying.procurement_invoice_items.frappe.get_doc")
	def test_actual_text_pdf_and_empty_pdf(self, get_doc):
		get_doc.return_value.get_content.return_value = make_invoice_pdf()
		result = read_invoice_items("/private/files/invoice.pdf")
		self.assertEqual(result["status"], "read")
		self.assertEqual(len(result["rows"]), 1)
		self.assertEqual(result["rows"][0]["supplier_item_name"], "Supplier cable")
		self.assertEqual(result["rows"][0]["qty"], 10)
		get_doc.return_value.get_content.return_value = make_invoice_pdf(with_text=False)
		self.assertEqual(read_invoice_items("/private/files/image.pdf")["status"], "unreadable")

	def test_locale_numbers_and_invalid_cells(self):
		for value in ("1 234,56", "1\u00a0234,56 грн", "1,234.56", "1.234,56"):
			self.assertEqual(parse_number(value), 1234.56)
		for value in ("", "—", "10 шт", "1,2,3"):
			self.assertIsNone(parse_number(value))

	def test_header_article_and_price_are_not_name_or_unit(self):
		self.assertEqual(
			header_columns(["Код товару", "Найменування товару", "Кількість", "Unit price", "Сума"]),
			{"supplier_part_no": 0, "supplier_item_name": 1, "qty": 2, "rate": 3, "amount": 4},
		)
		self.assertEqual(
			header_columns(
				[
					"№",
					"Найменування товару",
					"Од.ви\nм.",
					"К-ть",
					"Ціна за\nодиницю\nбез ПДВ",
					"Загальна\nвартість",
				]
			),
			{"supplier_item_name": 1, "uom": 2, "qty": 3, "rate": 4, "rate_exclusive": 4, "amount": 5},
		)

	def test_table_multiline_names_repeated_headers_and_totals(self):
		header = ["Артикул", "Найменування", "Кількість", "Ціна", "Сума"]
		rows, columns = parse_table(
			[header, ["A-1", "Кабель\nсиловий", "10", "2,50", "25"], header, ["", "Всього", "10", "", "25"]],
			1,
			0,
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["supplier_item_name"], "Кабель силовий")
		self.assertEqual(rows[0]["rate"], 2.5)
		continued, _ = parse_table([["B", "Товар", "2", "3", "6"]], 2, 0, columns)
		self.assertEqual(continued[0]["qty"], 2)

	def test_unknown_layout_never_guesses_rows(self):
		rows, _ = parse_table([["Random", "Document"], ["Cable", "100"]], 1, 0)
		self.assertEqual(rows, [])

	def invoice_row(self):
		return {
			"id": "1:0:1",
			"supplier_item_name": "Supplier cable",
			"supplier_part_no": "A-1",
			"qty": 10,
			"rate": 5,
			"uom": "Nos",
		}

	def order_row(self, name="ROW-A", code="ITEM-A", item_name="Our cable"):
		return frappe._dict(
			name=name, item_code=code, item_name=item_name, qty=10, rate=5, uom="Nos", supplier="SUP"
		)

	def test_quantity_and_price_alone_do_not_select_an_item(self):
		result = suggest_rows(self.invoice_row(), [self.order_row(item_name="Bolt")], [])
		self.assertIsNone(result["suggested_order_row"])

	def test_saved_alias_and_tied_rows(self):
		alias = frappe._dict(item_code="ITEM-A", supplier_item_name="Supplier cable", supplier_part_no="A-1")
		result = suggest_rows(self.invoice_row(), [self.order_row()], [alias])
		self.assertEqual(result["suggested_order_row"], "ROW-A")
		result = suggest_rows(self.invoice_row(), [self.order_row(), self.order_row(name="ROW-B")], [alias])
		self.assertIsNone(result["suggested_order_row"])

	def test_alias_key_normalizes_spacing_and_is_supplier_scoped(self):
		self.assertEqual(alias_key("SUP", " Cable  A ", "a-1"), alias_key("SUP", "cable a", "A-1"))
		self.assertNotEqual(alias_key("SUP", "Cable", "A"), alias_key("OTHER", "Cable", "A"))

	@patch(f"{MODULE}.frappe.get_roles", return_value=["Закупівельник"])
	@patch(f"{MODULE}.frappe.get_doc")
	def test_other_buyers_and_wrong_invoice_are_rejected(self, get_doc, roles):
		doc = MagicMock(owner="owner@example.com", initiator_user="buyer@example.com", docstatus=0)
		doc.supplier_invoices = [frappe._dict(supplier="SUP", invoice_pdf="/private/files/invoice.pdf")]
		get_doc.return_value = doc
		with patch(f"{MODULE}.frappe.session", frappe._dict(user="other@example.com")):
			with self.assertRaises(frappe.PermissionError):
				_check_order("ORDER", "SUP", "/private/files/invoice.pdf")
		with patch(f"{MODULE}.frappe.session", frappe._dict(user="buyer@example.com")):
			with self.assertRaises(frappe.PermissionError):
				_check_order("ORDER", "OTHER", "/private/files/invoice.pdf")

	@patch(f"{MODULE}.frappe.get_roles", return_value=["Закупівельник"])
	def test_matching_later_and_completed_orders_only_saves_aliases(self, _roles):
		for status, stage, completion in (
			(0, "Перевірка підрозділу", "Погодження"),
			(0, "Фінальне погодження", "Погодження"),
			(1, "Погоджено", "Очікує оплату"),
			(1, "Погоджено", "Завершено"),
		):
			with self.subTest(stage=stage, completion=completion):
				doc = MagicMock(
					owner="owner@example.com",
					initiator_user="buyer@example.com",
					docstatus=status,
					workflow_state=stage,
					procurement_completion_status=completion,
				)
				doc.name = "ORDER"
				doc.items = [self.order_row()]
				doc.supplier_invoices = [
					frappe._dict(supplier="SUP", invoice_pdf="/private/files/invoice.pdf")
				]
				with (
					patch(f"{MODULE}.frappe.session", frappe._dict(user="buyer@example.com")),
					patch(f"{MODULE}.frappe.get_doc", side_effect=[doc, MagicMock()]),
					patch(f"{MODULE}.read_invoice_items", return_value={"rows": [self.invoice_row()]}),
					patch(f"{MODULE}._save_confirmed_matches", return_value={"saved": 1}) as save,
				):
					result = confirm_matches(
						"ORDER",
						"SUP",
						"/private/files/invoice.pdf",
						[{"invoice_row": "1:0:1", "order_row": "ROW-A"}],
					)
				self.assertEqual(result, {"saved": 1})
				save.assert_called_once_with(
					[(self.invoice_row(), "ITEM-A")], "SUP", "/private/files/invoice.pdf", "ORDER"
				)
				doc.check_permission.assert_called_once_with("read")
				doc.save.assert_not_called()
				doc.db_set.assert_not_called()
				doc.submit.assert_not_called()

	def test_cancelled_order_cannot_be_used_for_matching(self):
		with (
			patch(f"{MODULE}.frappe.session", frappe._dict(user="Administrator")),
			patch(f"{MODULE}.frappe.get_doc", return_value=MagicMock(docstatus=2)),
			self.assertRaises(frappe.ValidationError),
		):
			_check_order("ORDER", "SUP", "/private/files/invoice.pdf")

	def test_prefill_confirmation_uses_pdf_text_and_does_not_save_order(self):
		doc = MagicMock()
		doc.name = "ORDER"
		doc.is_new.return_value = False
		doc.items = [self.order_row()]
		item = MagicMock(disabled=0, has_variants=0, is_purchase_item=1)
		with (
			patch(f"{MODULE}._prefill_context", return_value=doc),
			patch(f"{MODULE}.read_invoice_items", return_value={"rows": [self.invoice_row()]}),
			patch(f"{MODULE}.frappe.get_doc", return_value=item),
			patch(f"{MODULE}._save_confirmed_matches", return_value={"saved": 1}) as save,
		):
			result = confirm_prefill_matches(
				"SUP",
				"/private/files/invoice.pdf",
				{},
				[{"invoice_row": "1:0:1", "item_code": "ITEM-A", "supplier_item_name": "Forged name"}],
			)
		self.assertEqual(result, {"saved": 1})
		save.assert_called_once_with(
			[(self.invoice_row(), "ITEM-A")], "SUP", "/private/files/invoice.pdf", "ORDER"
		)
		doc.save.assert_not_called()
		item.check_permission.assert_called_once_with("read")

	def test_prefill_confirmation_rejects_unknown_duplicate_and_foreign_items(self):
		doc = MagicMock()
		doc.items = [self.order_row()]
		item = MagicMock(disabled=0, has_variants=0, is_purchase_item=1)
		with (
			patch(f"{MODULE}._prefill_context", return_value=doc),
			patch(f"{MODULE}.read_invoice_items", return_value={"rows": [self.invoice_row()]}),
			patch(f"{MODULE}.frappe.get_doc", return_value=item),
			patch(f"{MODULE}._save_confirmed_matches") as save,
		):
			for mappings in (
				[],
				[{"invoice_row": "FAKE", "item_code": "ITEM-A"}],
				[{"invoice_row": "1:0:1", "item_code": "FOREIGN"}],
				[{"invoice_row": "1:0:1", "item_code": "ITEM-A"}] * 2,
			):
				with self.subTest(mappings=mappings), self.assertRaises(frappe.ValidationError):
					confirm_prefill_matches("SUP", "/private/files/invoice.pdf", {}, mappings)
			save.assert_not_called()

	def call_confirmation(self, mappings, existing=None):
		doc = MagicMock(name="ORDER")
		doc.items = [self.order_row()]
		item = MagicMock(disabled=0)
		canonical = frappe._dict(
			supplier="SUP", custom_supplier_item_name="Existing name", supplier_part_no="Existing code"
		)
		item.supplier_items = [canonical]
		with (
			patch(f"{MODULE}._check_order", return_value=doc),
			patch(f"{MODULE}.read_invoice_items", return_value={"rows": [self.invoice_row()]}),
			patch(f"{MODULE}._known_items", return_value=[]),
			patch(f"{MODULE}.frappe.db.get_value", return_value=existing),
			patch(f"{MODULE}.frappe.get_doc", return_value=item) as get_doc,
		):
			result = confirm_matches("ORDER", "SUP", "/private/files/invoice.pdf", mappings)
		return result, item, canonical, get_doc

	def test_confirmation_rejects_foreign_rows_and_duplicates(self):
		for mappings in (
			[{"invoice_row": "FAKE", "order_row": "ROW-A"}],
			[{"invoice_row": "1:0:1", "order_row": "FOREIGN"}],
			[{"invoice_row": "1:0:1", "order_row": "ROW-A"}] * 2,
		):
			with self.assertRaises(frappe.ValidationError):
				self.call_confirmation(mappings)

	def test_confirmation_never_replaces_existing_canonical_data(self):
		result, item, canonical, get_doc = self.call_confirmation(
			[{"invoice_row": "1:0:1", "order_row": "ROW-A"}]
		)
		self.assertEqual(result["saved"], 1)
		self.assertEqual(canonical.custom_supplier_item_name, "Existing name")
		self.assertEqual(canonical.supplier_part_no, "Existing code")
		item.save.assert_not_called()
		payload = next(call.args[0] for call in get_doc.call_args_list if isinstance(call.args[0], dict))
		self.assertEqual(payload["supplier_item_name"], "Supplier cable")
		self.assertEqual(payload["item_code"], "ITEM-A")

	def test_canonical_pair_is_filled_only_when_compatible(self):
		canonical = frappe._dict(custom_supplier_item_name=None, supplier_part_no="OLD")
		self.assertFalse(_fill_canonical(canonical, self.invoice_row()))
		self.assertIsNone(canonical.custom_supplier_item_name)
		canonical = frappe._dict(custom_supplier_item_name=None, supplier_part_no="A-1")
		self.assertTrue(_fill_canonical(canonical, self.invoice_row()))
		self.assertEqual(canonical.custom_supplier_item_name, "Supplier cable")
		# Real child documents expose attributes, unlike frappe._dict fixtures.
		from erpnext.stock.doctype.item_supplier.item_supplier import ItemSupplier

		child = ItemSupplier({"doctype": "Item Supplier", "supplier_part_no": "A-1"})
		self.assertTrue(_fill_canonical(child, self.invoice_row()))
		self.assertEqual(child.custom_supplier_item_name, "Supplier cable")

	def test_repeated_confirmation_is_noop_and_conflict_is_blocked(self):
		mappings = [{"invoice_row": "1:0:1", "order_row": "ROW-A"}]
		result, item, _, _ = self.call_confirmation(mappings, existing="ITEM-A")
		self.assertEqual(result, {"saved": 0, "already_saved": 1})
		item.insert.assert_not_called()
		item.save.assert_not_called()
		with self.assertRaises(frappe.ValidationError):
			self.call_confirmation(mappings, existing="OTHER")
