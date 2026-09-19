"""Import the ЄСКД workbook (`ЄСКД.xlsx`) into Technical Documentation.

MANUAL TOOL — never wire this into a hook, a patch or the scheduler. Every designation in
the catalog sheets becomes a Product Modification of the «Специфікація» document that stands
for its prefix (УКРП.563562.003-01С under УКРП.563562.003-ХХС); Items point at the
modification through `Item.specification`. The document register (`Сводная`,
`Сводная таблиця ТУ`, `Технологічні карти`) becomes Technical Documents keyed on code +
product. A modification list becomes a «Відомість модифікацій» document and each of its
rows a Product Modification. Defaults to a dry run.

Run from the container console:

	bench --site frontend execute erpnext.manufacturing.eskd_import.run \
		--kwargs "{'path': '/tmp/ЄСКД.xlsx', 'dry_run': True}"

The import is idempotent: records are matched on their natural key and only blank fields
are filled in, so re-running after the workbook changes only applies the delta.
"""

import re

import frappe
from frappe.utils import cint, flt

PLACEHOLDER_RE = re.compile(r"[?ХX]{2,}")
ORG_PREFIX_RE = re.compile(r"^([А-ЯІЇЄҐA-Z]{4})[.\s]")

# "125 0,25 5 км" / "150 0,2 30 км" -> spool diameter, fibre diameter, winding length
COIL_PURPOSE_RE = re.compile(r"^(\d+)\s+([\d.,]+)\s+([\d.,]+)\s*км")
# "ДШВ 1.5 км"
COIL_SHORT_RE = re.compile(r"([\d.,]+)\s*км")

PARAM_WINDING_LENGTH = "Довжина намотування, км"
PARAM_SPOOL_DIAMETER = "Діаметр шпулі, мм"
PARAM_FIBRE_DIAMETER = "Діаметр волокна, мм"
PARAM_CAMERA_CHANNEL = "Тип каналу камери"
PARAM_CAMERA_SIGNAL = "Тип сигналу камери"
PARAM_BATTERY_LAYOUT = "Конфігурація батареї"
PARAM_PREVIOUS_CODE = "Попередній шифр"
PARAM_OLD_NAME = "Стара назва"

# Catalog parameters become modification attributes, declared on the product type.
NUMERIC_PARAMETERS = {PARAM_WINDING_LENGTH, PARAM_SPOOL_DIAMETER, PARAM_FIBRE_DIAMETER}
ATTRIBUTES_BY_PRODUCT_TYPE = {
	"Котушка": (PARAM_WINDING_LENGTH, PARAM_SPOOL_DIAMETER, PARAM_FIBRE_DIAMETER),
	"БпЛА": (
		PARAM_WINDING_LENGTH,
		PARAM_CAMERA_CHANNEL,
		PARAM_CAMERA_SIGNAL,
		PARAM_PREVIOUS_CODE,
		PARAM_OLD_NAME,
	),
	"Батарея": (PARAM_BATTERY_LAYOUT,),
}

DESIGNATION_RE = re.compile(r"^[А-ЯІЇЄҐA-Z]{4}\.\d{6}\.")

DOCUMENT_DOCTYPE = "Technical Document"
DESIGN_SECTION = "Конструкторська документація"
DESIGN_SECTION_PREFIX = "КД-.YYYY.-"
TU_SECTION = "Технічні умови"
TYPE_TU = "Технічні умови"
TYPE_SPECIFICATION = "Специфікація"
TYPE_ASSEMBLY_DRAWING = "Складальний кресленик"
TYPE_WIRING_DIAGRAM = "Схема електрична"
TYPE_PROCESS_CARD = "Технологічна карта"
TYPE_PART = "Деталь"
TYPE_USER_MANUAL = "Інструкція користувача"
TYPE_PASSPORT = "Паспорт"
TYPE_MODIFICATION_LIST = "Відомість модифікацій"
MODIFICATION_DOCTYPE = "Product Modification"

# What the catalog calls a kind, the modification calls a product type.
PRODUCT_TYPE_BY_KIND = {
	"Board": "БпЛА",
	"Coil": "Котушка",
	"Battery": "Батарея",
	"Ground Station": "НСУ",
}
CATALOG_TITLES = {
	"Board": "Специфікація на борт",
	"Coil": "Специфікація на котушку",
	"Battery": "Специфікація на батарею",
	"Ground Station": "Специфікація на наземну станцію керування",
}
# `УКРП.563562.003-01С` -> prefix `УКРП.563562.003`, number 1
NUMBERED_CODE_RE = re.compile(r"^(?P<prefix>.+)-(?P<number>\d{2})[СC]?$")

DESIGN_DOCUMENT_TYPES = (
	{
		"document_type": TYPE_SPECIFICATION,
		"abbreviation": "С",
		"default_section": DESIGN_SECTION,
		"has_specification_data": 1,
		"has_modifications": 1,
	},
	{
		"document_type": TYPE_MODIFICATION_LIST,
		"abbreviation": "ВМ",
		"default_section": DESIGN_SECTION,
		"has_modifications": 1,
	},
	{"document_type": TYPE_ASSEMBLY_DRAWING, "abbreviation": "СК", "default_section": DESIGN_SECTION},
	{"document_type": TYPE_WIRING_DIAGRAM, "abbreviation": "ЕХ", "default_section": DESIGN_SECTION},
	{"document_type": TYPE_PROCESS_CARD, "abbreviation": "ТК", "default_section": DESIGN_SECTION},
	{"document_type": TYPE_PART, "abbreviation": "Д", "default_section": DESIGN_SECTION},
	{"document_type": TYPE_USER_MANUAL, "abbreviation": "ІК", "default_section": "Інструкції"},
)

ROLE_COIL = "Котушка"
ROLE_BATTERY = "Батарея"
ROLE_BOARD = "Борт"
ROLE_GROUND_STATION = "НСУ"

COMPONENT_ROLES = {
	ROLE_COIL: "Coil",
	ROLE_BATTERY: "Battery",
	ROLE_BOARD: "Board",
	ROLE_GROUND_STATION: "Ground Station",
}


class Summary:
	def __init__(self):
		self.rows = {}

	def hit(self, key, delta=1):
		self.rows[key] = self.rows.get(key, 0) + delta

	def as_dict(self):
		return dict(sorted(self.rows.items()))

	def show(self):
		for key, count in sorted(self.rows.items()):
			print(f"  {key}: {count}")


def _norm(value):
	if value is None:
		return ""
	return str(value).strip()


def _is_placeholder(code):
	"""`УКРП.430103.ХХХ ЭХ` / `УКРП.200121.1001??0021С` are slots, not designations."""
	return bool(PLACEHOLDER_RE.search(code.upper()))


def _org_code(code, default="УКРП"):
	match = ORG_PREFIX_RE.match(code)
	return match.group(1) if match else default


def _num(value):
	text = _norm(value).replace(",", ".")
	if not text:
		return None
	try:
		return flt(text)
	except (ValueError, TypeError):
		return None


# --------------------------------------------------------------------------------------
# writers
# --------------------------------------------------------------------------------------


def ensure_roles(summary, dry_run):
	for role, kind in COMPONENT_ROLES.items():
		if frappe.db.exists("Specification Component Role", role):
			continue
		summary.hit("component roles created")
		if dry_run:
			continue
		frappe.get_doc(
			{"doctype": "Specification Component Role", "role_name": role, "specification_kind": kind}
		).insert(ignore_permissions=True)


def ensure_attributes(summary, dry_run):
	"""Product attributes the catalog parameters land in, declared on their product types."""
	for product_type, attributes in ATTRIBUTES_BY_PRODUCT_TYPE.items():
		for attribute in attributes:
			if not frappe.db.exists("Product Attribute", attribute):
				summary.hit("product attributes created")
				if not dry_run:
					frappe.get_doc(
						{
							"doctype": "Product Attribute",
							"attribute_name": attribute,
							"numeric_values": int(attribute in NUMERIC_PARAMETERS),
						}
					).insert(ignore_permissions=True)
			if not frappe.db.exists("Product Type", product_type):
				continue
			if frappe.db.exists(
				"Product Attribute Assignment",
				{"parent": product_type, "parenttype": "Product Type", "attribute": attribute},
			):
				continue
			summary.hit("product attributes declared")
			if not dry_run:
				doc = frappe.get_doc("Product Type", product_type)
				doc.append("attributes", {"attribute": attribute})
				doc.save(ignore_permissions=True)


CYRILLIC_ES = "С"
LATIN_ES = "C"


def _attribute_rows(parameters, product_type):
	declared = ATTRIBUTES_BY_PRODUCT_TYPE.get(product_type, ())
	rows, seen = [], set()
	for attribute, value, _uom in parameters or []:
		if value in (None, "") or attribute not in declared or attribute in seen:
			continue
		seen.add(attribute)
		if attribute in NUMERIC_PARAMETERS:
			number = _num(value)
			if number is None:
				continue
			value = f"{number:g}"
		rows.append({"attribute": attribute, "attribute_value": str(value)})
	return rows


def _new_document(document_type, code, title, product=None, **values):
	doc = frappe.get_doc(
		{
			"doctype": DOCUMENT_DOCTYPE,
			"document_type": document_type,
			"document_title": (title or code)[:140],
			"document_code": code,
			"company": frappe.defaults.get_global_default("company")
			or frappe.db.get_value("Company", {}, "name"),
			"section": frappe.db.get_value("Technical Document Type", document_type, "default_section")
			or DESIGN_SECTION,
			"status": "Чинний",
			"responsible": frappe.session.user,
			"product_model": product,
			**values,
		}
	)
	if frappe.db.get_value("Technical Document Type", document_type, "has_product_classification"):
		doc.product_type = _product_type(product or "")
	return doc


def _catalog_prefix(code, kind):
	"""The designation of the catalog a code belongs to, and its position in it."""
	match = NUMBERED_CODE_RE.match(code)
	if match:
		return f"{match.group('prefix')}-ХХС", cint(match.group("number"))
	head = ".".join(code.split(".")[:2])
	return f"{head}.YYQQWWEEС", None


def upsert_catalog(prefix, kind, organization_code, summary, dry_run):
	"""The «Специфікація» document a family of designations hangs from."""
	existing = frappe.db.get_value(
		DOCUMENT_DOCTYPE, {"document_type": TYPE_SPECIFICATION, "document_code": prefix}, "name"
	)
	if existing:
		return existing
	summary.hit(f"catalogs created: {kind}")
	if dry_run:
		return None
	doc = _new_document(
		TYPE_SPECIFICATION,
		prefix,
		f"{CATALOG_TITLES.get(kind, TYPE_SPECIFICATION)} {prefix}",
		specification_kind=kind,
		organization_code=organization_code,
		product_type=PRODUCT_TYPE_BY_KIND.get(kind),
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def upsert_specification(code, name, summary, dry_run, parameters=None, components=None, **values):
	"""A catalog designation: a modification of the «Специфікація» document of its prefix."""
	code = _norm(code)
	name = _norm(name) or code
	if not code:
		return None
	if _is_placeholder(code):
		summary.hit("specifications skipped (placeholder code)")
		return None

	kind = values.get("specification_kind")
	product_type = PRODUCT_TYPE_BY_KIND.get(kind)
	fields = {
		"purpose": values.get("purpose"),
		"note": values.get("description"),
	}
	fields = {k: v for k, v in fields.items() if v not in (None, "")}
	attribute_rows = _attribute_rows(parameters, product_type)
	component_rows = [{"role": role, "specification": spec} for role, spec in components or [] if spec]

	existing = _specification_by_code(code)
	if existing:
		# First writer wins: the authoritative sheets are imported first, so a later
		# draft listing of the same designation only fills in what is still blank.
		summary.hit("specifications updated")
		if dry_run:
			return existing
		doc = frappe.get_doc(MODIFICATION_DOCTYPE, existing)
		doc.update({k: v for k, v in fields.items() if not doc.get(k)})
		present = {row.attribute for row in doc.get("attributes") or []}
		for row in attribute_rows:
			if row["attribute"] not in present:
				doc.append("attributes", row)
		if component_rows and not doc.get("components"):
			doc.set("components", component_rows)
		doc.save(ignore_permissions=True)
		return doc.name

	summary.hit("specifications created")
	prefix, number = _catalog_prefix(code, kind)
	catalog = upsert_catalog(
		prefix, kind, values.get("organization_code") or _org_code(code), summary, dry_run
	)
	if dry_run:
		return None
	doc = frappe.get_doc(
		{
			"doctype": MODIFICATION_DOCTYPE,
			"technical_document": catalog,
			"modification_code": code,
			"modification_number": number,
			"full_name": name[:140],
			"company": frappe.db.get_value(DOCUMENT_DOCTYPE, catalog, "company"),
			"product_type": product_type,
			"status": "Чинна",
			"attributes": attribute_rows,
			"components": component_rows,
			**fields,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_document_setup(summary, dry_run):
	"""Section, naming rule and ЄСКД document types the register needs."""
	if not frappe.db.exists("DocType", DOCUMENT_DOCTYPE):
		frappe.throw("Technical Documentation module is not installed")
	if not frappe.db.exists("Technical Document Section", DESIGN_SECTION):
		summary.hit("document sections created")
		if not dry_run:
			frappe.get_doc(
				{
					"doctype": "Technical Document Section",
					"section_name": DESIGN_SECTION,
					"is_group": 1,
					"naming_prefix": DESIGN_SECTION_PREFIX,
				}
			).insert(ignore_permissions=True)
			frappe.get_doc(
				{
					"doctype": "Document Naming Rule",
					"document_type": DOCUMENT_DOCTYPE,
					"prefix": DESIGN_SECTION_PREFIX,
					"prefix_digits": 5,
					"priority": 1,
					"conditions": [{"field": "section", "condition": "=", "value": DESIGN_SECTION}],
				}
			).insert(ignore_permissions=True)
	for row in DESIGN_DOCUMENT_TYPES:
		if frappe.db.exists("Technical Document Type", row["document_type"]):
			flags = {
				k: v
				for k, v in row.items()
				if k.startswith("has_")
				and not frappe.db.get_value("Technical Document Type", row["document_type"], k)
			}
			if flags and not dry_run:
				frappe.db.set_value("Technical Document Type", row["document_type"], flags)
			continue
		summary.hit("document types created")
		if not dry_run:
			frappe.get_doc({"doctype": "Technical Document Type", **row}).insert(ignore_permissions=True)


def _document_type(title, code, category):
	title_l = title.lower()
	if title_l.startswith(("специфікац", "спеціфікац")):
		return TYPE_SPECIFICATION
	if title_l.startswith("ту"):
		return TYPE_TU
	if title_l.startswith("інструкція користувача"):
		return TYPE_USER_MANUAL
	if title_l.startswith("паспорт"):
		return TYPE_PASSPORT
	if title_l.startswith("складальн") or code.replace(" ", "").endswith("СК"):
		return TYPE_ASSEMBLY_DRAWING
	if "схем" in category.lower() or code.endswith("ЭХ") or code.endswith("ЕХ"):
		return TYPE_WIRING_DIAGRAM
	return TYPE_PART


def _product_type(product):
	text = product.lower()
	if "станці" in text or "нсу" in text or "нск" in text:
		return "НСУ"
	if "катушк" in text or "котушк" in text or text == "укропчик fo":
		return "Котушка"
	return "БпЛА"


def upsert_document(code, title, document_type, product, summary, dry_run, note=None):
	code = _norm(code)
	product = _norm(product)
	if not code:
		return None
	if _is_placeholder(code):
		summary.hit("documents skipped (placeholder code)")
		return None

	existing = frappe.db.get_value(
		DOCUMENT_DOCTYPE, {"document_code": code, "product_model": product or ("is", "not set")}, "name"
	)
	if existing:
		summary.hit("documents updated")
		if not dry_run and note and not frappe.db.get_value(DOCUMENT_DOCTYPE, existing, "note"):
			frappe.db.set_value(DOCUMENT_DOCTYPE, existing, "note", note)
		return existing

	summary.hit(f"documents created: {document_type}")
	if dry_run:
		return None
	doc = _new_document(document_type, code, title, product, note=note)
	doc.insert(ignore_permissions=True)
	return doc.name


def import_register(wb, summary, dry_run):
	"""`Сводная` — the per-product document register, laid out as 3-column blocks."""
	ws = wb["Сводная"]
	grid = [[_norm(c) for c in row] for row in ws.iter_rows(values_only=True)]
	if not grid:
		return
	width = max(len(r) for r in grid)
	for row in grid:
		row.extend([""] * (width - len(row) + 3))

	for block_start in range(0, width, 3):
		product = grid[0][block_start]
		if not any(row[block_start + 2] for row in grid[1:]):
			continue
		category = ""
		for row in grid[1:]:
			title, code = row[block_start], row[block_start + 2]
			if not title and not code:
				continue
			if title and not code:
				category = title
				continue
			upsert_document(
				code,
				title or category,
				_document_type(title or category, code, category),
				product,
				summary,
				dry_run,
				note=category,
			)


def import_tu_table(wb, summary, dry_run):
	"""`Сводная таблиця ТУ` — one ТУ number per product."""
	ws = wb["Сводная таблиця ТУ"]
	for row in ws.iter_rows(min_row=2, values_only=True):
		cells = [_norm(c) for c in row]
		cells.extend([""] * (4 - len(cells)))
		product, number, note = cells[1], cells[2], cells[3]
		if not product or not number:
			continue
		upsert_document(number, f"Технічні умови {product}", TYPE_TU, product, summary, dry_run, note=note)


def import_process_cards(wb, summary, dry_run):
	"""`Технологічні карти` — ТК codes grouped by a product heading row."""
	ws = wb["Технологічні карти"]
	product = ""
	for row in ws.iter_rows(min_row=3, values_only=True):
		cells = [_norm(c) for c in row]
		cells.extend([""] * (5 - len(cells)))
		label, code, note = cells[1], cells[2], cells[4]
		if label and not code:
			product = label
			continue
		if not code:
			continue
		upsert_document(
			code,
			note or f"Технологічна карта {code}",
			TYPE_PROCESS_CARD,
			product,
			summary,
			dry_run,
		)


def import_coils(wb, summary, dry_run):
	"""`Специфікація на котушку` — УКРП.200121.002-ХХС catalog."""
	ws = wb["Специфікація на котушку"]
	for row in ws.iter_rows(min_row=5, max_row=64, values_only=True):
		cells = [_norm(c) for c in row]
		cells.extend([""] * (5 - len(cells)))
		ordinal, purpose, code, name = cells[0], cells[1], cells[3], cells[4]
		if not code or not name:
			# reserved-but-unassigned slot
			continue
		upsert_specification(
			code,
			name,
			summary,
			dry_run,
			specification_kind="Coil",
			ordinal=cint(ordinal),
			purpose=purpose,
			parameters=_coil_parameters(purpose),
		)


def _coil_parameters(purpose):
	match = COIL_PURPOSE_RE.match(purpose)
	if match:
		spool, fibre, length = match.groups()
		return [
			(PARAM_WINDING_LENGTH, _num(length), "км"),
			(PARAM_SPOOL_DIAMETER, _num(spool), "мм"),
			(PARAM_FIBRE_DIAMETER, _num(fibre), "мм"),
		]
	short = COIL_SHORT_RE.search(purpose)
	if short:
		return [(PARAM_WINDING_LENGTH, _num(short.group(1)), "км")]
	return []


def import_varnex(wb, summary, dry_run):
	"""`ВАРНЕКС` — the ВРНК-branded coil and ground-station lists."""
	ws = wb["ВАРНЕКС"]
	for row in ws.iter_rows(min_row=3, max_row=12, values_only=True):
		cells = [_norm(c) for c in row]
		cells.extend([""] * (6 - len(cells)))
		ordinal, code, name, length, spool, fibre = cells[:6]
		if not code:
			continue
		upsert_specification(
			code,
			name,
			summary,
			dry_run,
			specification_kind="Coil",
			organization_code="ВРНК",
			ordinal=cint(ordinal),
			parameters=[
				(PARAM_WINDING_LENGTH, _num(length), "км"),
				(PARAM_SPOOL_DIAMETER, _num(spool), "мм"),
				(PARAM_FIBRE_DIAMETER, _num(fibre), "мм"),
			],
		)

	for row in ws.iter_rows(min_row=23, max_row=27, values_only=True):
		cells = [_norm(c) for c in row]
		cells.extend([""] * (4 - len(cells)))
		ordinal, code, name, note = cells[:4]
		if not code:
			continue
		upsert_specification(
			code,
			name,
			summary,
			dry_run,
			specification_kind="Ground Station",
			organization_code="ВРНК",
			ordinal=cint(ordinal),
			purpose=note,
		)

	# `БпАК - Укропчик Штурм` and the coil / battery it is built from
	coil_code, coil_purpose, coil_name = (_norm(ws.cell(43, c).value) for c in (10, 8, 11))
	if coil_code:
		upsert_specification(
			coil_code,
			coil_name,
			summary,
			dry_run,
			specification_kind="Coil",
			ordinal=cint(ws.cell(43, 7).value),
			purpose=coil_purpose,
			parameters=_coil_parameters(coil_purpose),
		)
	battery_code, battery_layout = _norm(ws.cell(47, 9).value), _norm(ws.cell(47, 8).value)
	if battery_code:
		upsert_specification(
			battery_code,
			f"УКРП {battery_layout}",
			summary,
			dry_run,
			specification_kind="Battery",
			ordinal=cint(ws.cell(47, 7).value),
			purpose=battery_layout,
			parameters=[(PARAM_BATTERY_LAYOUT, battery_layout, "")],
		)
	tu = _norm(ws.cell(37, 4).value)
	for row in ws.iter_rows(min_row=39, max_row=41, values_only=True):
		cells = [_norm(c) for c in row]
		cells.extend([""] * (4 - len(cells)))
		code, note, name = cells[1], cells[2], cells[3]
		if not DESIGNATION_RE.match(code):
			continue
		upsert_specification(
			code,
			name or note,
			summary,
			dry_run,
			specification_kind="Board",
			description=f"{note}; {tu}" if tu else note,
			components=_board_components(code),
		)


def import_batteries(wb, summary, dry_run):
	"""`Специфікація на батарею` — two side-by-side blocks, УКРП and ВРНК."""
	ws = wb["Специфікація на батарею "]
	blocks = ((0, 1, 4, "УКРП"), (6, 7, 10, "ВРНК"))
	for row in ws.iter_rows(min_row=4, max_row=63, values_only=True):
		cells = [_norm(c) for c in row]
		cells.extend([""] * (11 - len(cells)))
		for ordinal_col, purpose_col, code_col, org in blocks:
			ordinal, purpose, code = cells[ordinal_col], cells[purpose_col], cells[code_col]
			if not code or not purpose:
				# unassigned slot in the reserved range
				continue
			upsert_specification(
				code,
				f"{org} {purpose}",
				summary,
				dry_run,
				specification_kind="Battery",
				organization_code=org,
				ordinal=cint(ordinal),
				purpose=purpose,
				parameters=[(PARAM_BATTERY_LAYOUT, purpose, "")],
			)


def import_ground_stations(wb, summary, dry_run):
	"""`Специфікація НСУ FO` — УКРП.563562.003-ХХС catalog."""
	ws = wb["Специфікація НСУ FO"]
	for row in ws.iter_rows(min_row=5, max_row=64, values_only=True):
		cells = [_norm(c) for c in row]
		cells.extend([""] * (5 - len(cells)))
		ordinal, purpose, code = cells[0], cells[1], cells[4]
		if not code or not purpose:
			continue
		upsert_specification(
			code,
			purpose,
			summary,
			dry_run,
			specification_kind="Ground Station",
			ordinal=cint(ordinal),
			purpose=purpose,
		)


# `Сперцифікація на FPV` blocks. The two ПЕРЕЛІК blocks at the bottom of the sheet carry
# the names and parameters that ship with the ТУ, so they are read first and win; the
# working blocks above them only contribute designations the ПЕРЕЛІК lists do not have.
FPV_BLOCKS = (
	{
		"start": 174,
		"end": 221,
		"code": 2,
		"name": 3,
		"note": 7,
		"params": True,
		"aliases": (7, 8),
		"export": {"code": 10, "tu": (171, 13)},
	},
	{
		"start": 139,
		"end": 169,
		"code": 2,
		"name": 3,
		"note": 7,
		"params": True,
		"aliases": (7,),
		"export": {"code": 9, "tu": (137, 12)},
	},
	{"start": 84, "end": 134, "code": 2, "name": 4, "note": 3, "params": False, "aliases": (5, 6)},
	{"start": 14, "end": 45, "code": 2, "name": 4, "note": 3, "params": False},
	{"start": 49, "end": 80, "code": 2, "name": None, "note": 3, "params": False},
)

# Radio boards listed beside the `Укропчик 10 FO` draft block: name, designation.
RADIO_BOARDS = {"start": 51, "end": 80, "name": 10, "code": 11}


# `УКРП.200121.` + frame(2) + camera(2) + battery ordinal(2) + coil ordinal(4) + `С`
BOARD_CODE_RE = re.compile(
	r"^(?P<org>[А-ЯІЇЄҐA-Z]{4})\.(?P<drone_class>\d{6})\."
	r"(?P<frame>\d{2})(?P<camera>\d{2})(?P<battery>\d{2})(?P<coil>\d{4})[СC]$"
)


def _board_components(code):
	"""Battery and coil a board designation is built from, found by their catalog position."""
	match = BOARD_CODE_RE.match(_norm(code))
	if not match:
		return None
	return [
		(role, _catalog_entry(kind, match.group("org"), ordinal))
		for role, kind, ordinal in (
			(ROLE_BATTERY, "Battery", match.group("battery")),
			(ROLE_COIL, "Coil", match.group("coil")),
		)
	]


def _catalog_entry(kind, organization_code, ordinal):
	catalogs = frappe.get_all(
		DOCUMENT_DOCTYPE,
		filters={
			"document_type": TYPE_SPECIFICATION,
			"specification_kind": kind,
			"organization_code": organization_code,
		},
		pluck="name",
	)
	if not catalogs:
		return None
	return frappe.db.get_value(
		MODIFICATION_DOCTYPE,
		{"technical_document": ("in", catalogs), "modification_number": cint(ordinal)},
		"name",
	)


def import_boards(wb, summary, dry_run):
	"""`Сперцифікація на FPV` — the per-airframe board specification lists."""
	ws = wb["Сперцифікація на FPV"]
	grid = [[_norm(c) for c in row] for row in ws.iter_rows(values_only=True)]
	width = max(len(r) for r in grid)
	for row in grid:
		row.extend([""] * (width - len(row)))

	for block in FPV_BLOCKS:
		for row in grid[block["start"] - 1 : block["end"]]:
			code = row[block["code"]]
			if not code:
				continue
			note = row[block["note"]] if block["note"] is not None else ""
			name = row[block["name"]] if block["name"] is not None else ""
			parameters = []
			if block["params"]:
				parameters = [
					(PARAM_WINDING_LENGTH, _num(row[4]), "км"),
					(PARAM_CAMERA_CHANNEL, row[5], ""),
					(PARAM_CAMERA_SIGNAL, row[6], ""),
				]
			parameters += _alias_parameters(row, block.get("aliases") or ())
			upsert_specification(
				code,
				name or note,
				summary,
				dry_run,
				specification_kind="Board",
				description=note,
				parameters=parameters,
				components=_board_components(code),
			)
			if block.get("export"):
				_import_export_board(grid, row, code, block["export"], summary, dry_run)

	for row in grid[RADIO_BOARDS["start"] - 1 : RADIO_BOARDS["end"]]:
		code, name = row[RADIO_BOARDS["code"]], row[RADIO_BOARDS["name"]]
		if not DESIGNATION_RE.match(code):
			continue
		upsert_specification(
			code, name, summary, dry_run, specification_kind="Board", description="Для радіо"
		)


def _alias_parameters(row, columns):
	"""Earlier designations and names of a board, kept next to the current one."""
	parameters = []
	for col in columns:
		value = row[col] if col < len(row) else ""
		if not value:
			continue
		if DESIGNATION_RE.match(value):
			parameters.append((PARAM_PREVIOUS_CODE, value, ""))
		else:
			parameters.append((PARAM_OLD_NAME, value.strip("*«» ").replace("»", "").replace("«", ""), ""))
	return parameters


def _import_export_board(grid, row, source_code, export, summary, dry_run):
	"""`Для нового ТУ` columns: the board re-issued under a new ТУ with an English name."""
	col = export["code"]
	code = row[col] if col < len(row) else ""
	if not DESIGNATION_RE.match(code):
		return
	tu_row, tu_col = export["tu"]
	tu = grid[tu_row - 1][tu_col]
	upsert_specification(
		code,
		row[col + 1],
		summary,
		dry_run,
		specification_kind="Board",
		description=f"Для нового ТУ {tu}; відповідає {source_code}",
		parameters=[
			(PARAM_WINDING_LENGTH, _num(row[col + 2]), "км"),
			(PARAM_CAMERA_CHANNEL, row[col + 3], ""),
			(PARAM_CAMERA_SIGNAL, row[col + 4], ""),
			(PARAM_PREVIOUS_CODE, source_code, ""),
		],
		components=_board_components(code),
	)


def import_modifications(wb, summary, dry_run):
	"""`Відомість модифікацій ТУ14` — the numbered modification list of a БпАК.

	The row axis is text (modification number -> board specification); the intersections
	are **cell fills**, not values — a solid-filled cell under a ground-station column is
	the pairing. Reading only values silently loses all of them.
	"""
	ws = wb["Відомість модифікацій ТУ14"]
	grid = [[_norm(c) for c in row] for row in ws.iter_rows(values_only=True)]
	if len(grid) < 5:
		return

	product, list_code = _modification_list(grid[2][0])
	if not product or not list_code:
		summary.hit("modification sheets skipped (no list designation)")
		return
	modification_list = upsert_document(
		list_code,
		f"Відомість модифікацій БпАК {product}",
		TYPE_MODIFICATION_LIST,
		product,
		summary,
		dry_run,
	)
	header_row = 4
	columns = {
		col: grid[header_row - 1][col - 1]
		for col in range(1, len(grid[header_row - 1]) + 1)
		if grid[header_row - 1][col - 1]
	}

	for row_index in range(header_row + 1, len(grid) + 1):
		row = grid[row_index - 1]
		number = _modification_number(row[0])
		board_code = row[2] if len(row) > 2 else ""
		if not number or not board_code:
			continue
		upsert_modification(
			modification_list,
			number,
			board_code,
			row[1],
			_marked_ground_station(ws, row_index, columns),
			summary,
			dry_run,
		)


def _marked_ground_station(ws, row_index, columns):
	"""Return the ground-station designation whose cell is filled on this row."""
	for col, code in columns.items():
		if ws.cell(row_index, col).fill.patternType == "solid":
			return code
	return ""


def _modification_list(title):
	"""`Відомість модифікацій БпАК Укропчик 15 FO УКРП.463145.006ВМ` -> (`Укропчик 15 FO`, `УКРП.463145.006ВМ`)."""
	text = _norm(title)
	marker = "БпАК "
	if marker not in text:
		return "", ""
	tail = text.split(marker, 1)[1]
	match = re.search(r"\s+([А-ЯІЇЄҐA-Z]{4}\.\S+)$", tail)
	if not match:
		return tail.strip(), ""
	return tail[: match.start()].strip(), match.group(1)


def _modification_number(label):
	match = re.search(r"(\d+)", _norm(label))
	return cint(match.group(1)) if match else 0


def upsert_modification(modification_list, number, board_code, board_name, gs_code, summary, dry_run):
	board = _specification_by_code(board_code)
	if not board:
		summary.hit("modifications skipped (board specification not in catalog)")
		return None

	if not gs_code:
		summary.hit("modifications skipped (no ground station marked)")
		return None
	ground_station = _specification_by_code(gs_code)
	if not ground_station:
		summary.hit("modifications skipped (ground station not in catalog)")
		return None

	existing = modification_list and frappe.db.get_value(
		MODIFICATION_DOCTYPE,
		{"technical_document": modification_list, "modification_number": number},
		"name",
	)
	if existing:
		summary.hit("modifications updated")
		return existing
	summary.hit("modifications created")
	if dry_run:
		return None
	doc = frappe.get_doc(
		{
			"doctype": MODIFICATION_DOCTYPE,
			"technical_document": modification_list,
			"modification_code": f"Модифікація {number}",
			"modification_number": number,
			"full_name": _norm(board_name) or board_code,
			"company": frappe.db.get_value(DOCUMENT_DOCTYPE, modification_list, "company"),
			"status": "Чинна",
			"components": [
				{"role": ROLE_BOARD, "specification": board},
				{"role": ROLE_GROUND_STATION, "specification": ground_station},
			],
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _specification_by_code(code):
	"""Look up a designation, tolerating the workbook's mixed Cyrillic `С` / Latin `C`."""
	code = _norm(code)
	if not code:
		return None
	for candidate in dict.fromkeys(
		(code, code.replace(LATIN_ES, CYRILLIC_ES), code.replace(CYRILLIC_ES, LATIN_ES))
	):
		found = frappe.db.get_value(MODIFICATION_DOCTYPE, {"modification_code": candidate}, "name")
		if found:
			return found
	return None


SHEET_IMPORTERS = {
	"register": import_register,
	"tu": import_tu_table,
	"process_cards": import_process_cards,
	"coils": import_coils,
	"varnex": import_varnex,
	"batteries": import_batteries,
	"ground_stations": import_ground_stations,
	"boards": import_boards,
	"modifications": import_modifications,
}


def run(path, dry_run=True, only=None):
	"""Import the ЄСКД workbook. Pass dry_run=False to actually write."""
	import openpyxl

	dry_run = bool(dry_run)
	wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
	summary = Summary()

	ensure_roles(summary, dry_run)
	ensure_document_setup(summary, dry_run)
	ensure_attributes(summary, dry_run)

	names = [only] if isinstance(only, str) else (only or list(SHEET_IMPORTERS))
	for key in names:
		importer = SHEET_IMPORTERS.get(key)
		if not importer:
			frappe.throw(f"Unknown ЄСКД importer: {key}")
		importer(wb, summary, dry_run)

	if not dry_run:
		frappe.db.commit()

	print(("DRY RUN — nothing written" if dry_run else "IMPORT COMMITTED") + f" ({path})")
	summary.show()
	return summary.as_dict()
