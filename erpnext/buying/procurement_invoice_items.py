"""Read invoice tables conservatively. Unrecognised layouts remain manual."""

import io
import re
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _

from erpnext.buying.doctype.supplier_item_alias.supplier_item_alias import normalize_alias

# Compare header keywords in a common alphabet, never rewrite supplier data.
HEADER_LOOKALIKES = str.maketrans(
	{
		"а": "a",
		"в": "b",
		"е": "e",
		"к": "k",
		"м": "m",
		"н": "h",
		"о": "o",
		"р": "p",
		"с": "c",
		"т": "t",
		"у": "y",
		"х": "x",
		"і": "i",
		"ј": "j",
		"ѕ": "s",
	}
)


def normalize_header(value):
	return normalize_alias(value).translate(HEADER_LOOKALIKES).replace("–", "-").replace("−", "-")


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
	"qty": (
		"кількість",
		"количество",
		"к-сть",
		"к-во",
		"к-ть",
		"кіл-ть",
		"кіл-сть",
		"кол-во",
		"quantity",
		"qty",
	),
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
		label = normalize_header(cell)
		compact = re.sub(r"[\s.]", "", label)
		# "Код товару" is an article, not the name; "unit price" is not a UOM.
		for key in ("supplier_part_no", "qty", "rate", "amount", "uom", "supplier_item_name"):
			patterns = [normalize_header(pattern) for pattern in HEADERS[key]]
			if any(pattern in label for pattern in patterns) or (
				key == "uom" and any(normalize_header(pattern) in compact for pattern in ("одвим", "едизм"))
			):
				columns.setdefault(key, index)
				if key == "rate":
					basis = price_basis(label)
					if basis != "unknown":
						columns[f"rate_{basis}"] = index
				break
	if "rate_inclusive" in columns:
		columns["rate"] = columns["rate_inclusive"]
	return columns if "supplier_item_name" in columns and "qty" in columns else None


def price_basis(label):
	label = normalize_header(label)
	if re.search(normalize_header(r"без\s*(пдв|ндс)|excl(?:uding)?\.?\s*vat|without\s+vat"), label):
		return "exclusive"
	if re.search(normalize_header(r"(?:із|зі|з|с)\s*(пдв|ндс)|incl(?:uding)?\.?\s*vat|with\s+vat"), label):
		return "inclusive"
	return "unknown"


def _header_cells(table, index):
	"""Join split header lines only, never consume a numeric item row."""
	cells = list(table[index])
	for offset in (-1, 1):
		adjacent = index + offset
		if not 0 <= adjacent < len(table):
			continue
		other = table[adjacent]
		if len(other) != len(cells) or any(parse_number(cell) is not None for cell in other):
			continue
		if not any(
			re.search(normalize_header(r"ціна|цена|price|сума|amount|пдв|ндс|vat"), normalize_header(c))
			for c in other
		):
			continue
		cells = [
			" ".join(str(part) for part in (left, right) if part)
			for left, right in (
				zip(other, cells, strict=True) if offset < 0 else zip(cells, other, strict=True)
			)
		]
	return cells


def invoice_rate(row, is_vat_payer, unknown_price_basis=""):
	"""CPO rates are gross. Ambiguous VAT-payer prices require explicit confirmation."""
	rate = row.get("rate")
	if rate is None or not is_vat_payer:
		return rate
	basis = row.get("price_basis", "unknown")
	if basis == "unknown":
		basis = unknown_price_basis
	if basis == "exclusive":
		return float(Decimal(str(rate)) * Decimal("1.2"))
	return rate if basis == "inclusive" else None


def parse_table(table, page, table_index, previous_columns=None):
	columns = previous_columns
	rows = []
	for index, cells in enumerate(table):
		found = header_columns(cells)
		if found:
			columns = header_columns(_header_cells(table, index)) or found
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
				"price_basis": next(
					(
						basis
						for basis in ("inclusive", "exclusive")
						if columns.get(f"rate_{basis}") == columns.get("rate") and "rate" in columns
					),
					"unknown",
				),
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
