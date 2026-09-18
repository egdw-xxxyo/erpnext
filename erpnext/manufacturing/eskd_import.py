"""Import the ЄСКД workbook (`ЄСКД.xlsx`) into Specification.

MANUAL TOOL — never wire this into a hook, a patch or the scheduler. Every designation in
the workbook becomes one flat Specification keyed on its code; Items point at it through
`Item.specification`. Defaults to a dry run.

Run from the container console:

	bench --site frontend execute erpnext.manufacturing.eskd_import.run \
		--kwargs "{'path': '/tmp/ЄСКД.xlsx', 'dry_run': True}"

The import is idempotent: specifications are matched on their code and only blank fields
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

ROLE_COIL = "Котушка"
ROLE_BATTERY = "Батарея"
ROLE_BOARD = "Борт"
ROLE_GROUND_STATION = "НСУ"
ROLE_MODIFICATION_LIST = "Відомість"

COMPONENT_ROLES = {
	ROLE_COIL: "Coil",
	ROLE_BATTERY: "Battery",
	ROLE_BOARD: "Board",
	ROLE_GROUND_STATION: "Ground Station",
	ROLE_MODIFICATION_LIST: "Modification List",
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


def _ensure_parameter(parameter, dry_run):
	if frappe.db.exists("Quality Inspection Parameter", parameter):
		return True
	if dry_run:
		return False
	frappe.get_doc({"doctype": "Quality Inspection Parameter", "parameter": parameter}).insert(
		ignore_permissions=True
	)
	return True


CYRILLIC_ES = "С"
LATIN_ES = "C"


def _parameter_rows(parameters, dry_run):
	rows = []
	for parameter, value, uom in parameters or []:
		if value in (None, ""):
			continue
		if not _ensure_parameter(parameter, dry_run):
			continue
		row = {"parameter": parameter, "value": str(value), "uom": uom or ""}
		numeric = _num(value)
		if numeric is not None:
			row["calculated_value"] = numeric
		rows.append(row)
	return rows


def upsert_specification(code, name, summary, dry_run, parameters=None, components=None, **values):
	code = _norm(code)
	name = _norm(name) or code
	if not code:
		return None
	if _is_placeholder(code):
		summary.hit("specifications skipped (placeholder code)")
		return None

	values = {k: v for k, v in values.items() if v not in (None, "")}
	values["organization_code"] = values.get("organization_code") or _org_code(code)
	rows = _parameter_rows(parameters, dry_run)
	component_rows = [{"role": role, "specification": spec} for role, spec in components or [] if spec]

	existing = _specification_by_code(code)
	if existing:
		# First writer wins: the authoritative sheets are imported first, so a later
		# draft listing of the same designation only fills in what is still blank.
		summary.hit("specifications updated")
		if dry_run:
			return existing
		doc = frappe.get_doc("Specification", existing)
		doc.update({k: v for k, v in values.items() if not doc.get(k)})
		if not doc.specification_name:
			doc.specification_name = name
		if rows and not doc.get("parameters"):
			doc.set("parameters", rows)
		if component_rows and not doc.get("components"):
			doc.set("components", component_rows)
		doc.save(ignore_permissions=True)
		return doc.name

	summary.hit("specifications created")
	if dry_run:
		return None
	doc = frappe.get_doc(
		{
			"doctype": "Specification",
			"specification_code": code,
			"specification_name": name[:140],
			**values,
		}
	)
	doc.set("parameters", rows)
	doc.set("components", component_rows)
	doc.insert(ignore_permissions=True)
	return doc.name


# --------------------------------------------------------------------------------------
# sheet readers
# --------------------------------------------------------------------------------------


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
			description=purpose,
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
			description=note,
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
				description=purpose,
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
			description=purpose,
		)


# `Сперцифікація на FPV` blocks. The two ПЕРЕЛІК blocks at the bottom of the sheet carry
# the names and parameters that ship with the ТУ, so they are read first and win; the
# working blocks above them only contribute designations the ПЕРЕЛІК lists do not have.
FPV_BLOCKS = (
	{"start": 174, "end": 221, "code": 2, "name": 3, "note": 7, "params": True},
	{"start": 139, "end": 169, "code": 2, "name": 3, "note": 7, "params": True},
	{"start": 84, "end": 134, "code": 2, "name": 4, "note": 3, "params": False},
	{"start": 14, "end": 45, "code": 2, "name": 4, "note": 3, "params": False},
	{"start": 49, "end": 80, "code": 2, "name": None, "note": 3, "params": False},
)


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
	return frappe.db.get_value(
		"Specification",
		{
			"specification_kind": kind,
			"organization_code": organization_code,
			"ordinal": cint(ordinal),
		},
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
	modification_list = upsert_specification(
		list_code,
		f"Відомість модифікацій БпАК {product}",
		summary,
		dry_run,
		specification_kind="Modification List",
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
			list_code,
			product,
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


def upsert_modification(
	modification_list, list_code, product, number, board_code, board_name, gs_code, summary, dry_run
):
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

	return upsert_specification(
		f"{board_code} / {gs_code} ({list_code})",
		f"{product} — модифікація {number}",
		summary,
		dry_run,
		specification_kind="BpAK",
		ordinal=number,
		description=board_name,
		components=[
			(ROLE_BOARD, board),
			(ROLE_GROUND_STATION, ground_station),
			(ROLE_MODIFICATION_LIST, modification_list),
		],
	)


def _specification_by_code(code):
	"""Look up a designation, tolerating the workbook's mixed Cyrillic `С` / Latin `C`."""
	code = _norm(code)
	if not code:
		return None
	found = frappe.db.get_value("Specification", {"specification_code": code}, "name")
	if found:
		return found
	swapped = code.replace(LATIN_ES, CYRILLIC_ES)
	if swapped != code:
		found = frappe.db.get_value("Specification", {"specification_code": swapped}, "name")
	return found


SHEET_IMPORTERS = {
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
