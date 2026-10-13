"""Read invoice tables conservatively. Unrecognised layouts remain manual."""

import io
import re
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _

from erpnext.buying.doctype.supplier_item_alias.supplier_item_alias import normalize_alias

HEADERS = {
	"supplier_item_name": (
		"найменування",
		"наименование",
		"назва",
		"номенклатура",
		"товар",
		"description",
		"item name",
	),
	"supplier_part_no": ("артикул", "код товару", "код товара", "sku", "part number", "item code"),
	"qty": ("кількість", "количество", "к-сть", "к-во", "к-ть", "кіл-ть", "кол-во", "quantity", "qty"),
	"rate": ("ціна", "цена", "price", "unit price"),
	"amount": ("сума", "сумма", "вартість", "стоимость", "amount", "total"),
	"uom": ("од. вим", "одиниця", "ед. изм", "од.", "uom", "unit"),
}


def parse_number(value):
	value = re.sub(r"[\s\u00a0₴]", "", str(value or ""))
	value = re.sub(r"(?:грн\.?|uah)$", "", value, flags=re.I)
	if "," in value and "." in value:
		decimal = "," if value.rfind(",") > value.rfind(".") else "."
		value = value.replace("." if decimal == "," else ",", "").replace(decimal, ".")
	else:
		value = value.replace(",", ".")
	if not re.fullmatch(r"\d+(?:\.\d+)?", value):
		return None
	try:
		return float(Decimal(value))
	except InvalidOperation:
		return None


def header_columns(cells):
	columns = {}
	for index, cell in enumerate(cells):
		label = normalize_alias(cell).replace("–", "-").replace("−", "-")
		compact = re.sub(r"[\s.]", "", label)
		# "Код товару" is an article, not the name; "unit price" is not a UOM.
		for key in ("supplier_part_no", "qty", "rate", "amount", "uom", "supplier_item_name"):
			patterns = HEADERS[key]
			if any(pattern in label for pattern in patterns) or (
				key == "uom" and any(pattern in compact for pattern in ("одвим", "едизм"))
			):
				columns.setdefault(key, index)
				break
	return columns if "supplier_item_name" in columns and "qty" in columns else None


def parse_table(table, page, table_index, previous_columns=None):
	columns = previous_columns
	rows = []
	for index, cells in enumerate(table):
		found = header_columns(cells)
		if found:
			columns = found
			continue
		if not columns:
			continue
		values = {key: cells[column] if column < len(cells) else None for key, column in columns.items()}
		name = " ".join(str(values.get("supplier_item_name") or "").split())
		qty = parse_number(values.get("qty"))
		if not name or qty is None or qty <= 0:
			continue
		if re.match(r"^(всього|всего|разом|итого|total|пдв\b|ндс\b)", normalize_alias(name)):
			continue
		rows.append(
			{
				"id": f"{page}:{table_index}:{index}",
				"page": page,
				"supplier_item_name": name,
				"supplier_part_no": " ".join(str(values.get("supplier_part_no") or "").split()),
				"uom": " ".join(str(values.get("uom") or "").split()),
				"qty": qty,
				"rate": parse_number(values.get("rate")),
				"amount": parse_number(values.get("amount")),
			}
		)
	return rows, columns


def read_invoice_items(file_url):
	import pdfplumber

	file = frappe.get_doc("File", {"file_url": file_url})
	file.check_permission("read")
	content = file.get_content()
	if not isinstance(content, bytes) or len(content) > 10 * 1024 * 1024:
		frappe.throw(_("Select a PDF smaller than 10 MB."))
	rows = []
	text_found = False
	with pdfplumber.open(io.BytesIO(content)) as pdf:
		if len(pdf.pages) > 50:
			frappe.throw(_("Select a PDF with no more than 50 pages."))
		columns = None
		for page_number, page in enumerate(pdf.pages, 1):
			text_found = text_found or bool(page.extract_text())
			tables = page.extract_tables()
			if not tables:
				tables = page.extract_tables({"vertical_strategy": "text", "horizontal_strategy": "text"})
			for table_index, table in enumerate(tables):
				parsed, columns = parse_table(table, page_number, table_index, columns)
				rows.extend(parsed)
				if len(rows) > 200:
					frappe.throw(_("Select a PDF with no more than 200 item rows."))
	return {
		"rows": rows,
		"status": "read" if rows else ("unrecognised_table" if text_found else "unreadable"),
	}
