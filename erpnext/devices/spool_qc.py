"""Optical spool QC: turn an uploaded SOR measurement into a Quality Inspection + a label.

Called from the `measuring` state of the `Spool QC` Workplace Script, which receives the
measurement event from `otdr_measurement_api.submit_measurement`:

    from erpnext.devices.spool_qc import handle_measurement

    def on_measurement(e):
        return handle_measurement(e)

The logic lives here rather than in the DB-stored script so it is versioned, linted and
identical on every site; the script stays a two-line call. The reviewed copy of both script
bodies is `erpnext/devices/scripts/spool_qc_workplace_v1.py`.

### Which spool was measured

The operator picks or scans the spool serial in the app and it arrives as `e.serial_no`.
That replaced reading the serial out of the SOR's **Fiber ID** field, which required the
operator to type it into the reflectometer's own menus before measuring — a step real
device dumps showed was never actually performed (`fiber_id` came back empty). The SOR
fields are still consulted as a fallback so a client that omits the serial degrades to the
old behaviour rather than failing.

### Grading

Pass/fail is **not** reimplemented here. Readings are filled from the measurement and the
stock `Quality Inspection.inspect_and_set_status()` applies the template's min/max,
acceptance values and formulas. `Serial No.inspection_status` is then set by the existing
`Quality Inspection.on_submit` hook (see `erpnext/stock/doctype/serial_no/inspection.py`).

Two stock behaviours shape the code below:

* `min_max_criteria_passed` returns `has_reading`, so a numeric reading left **empty is
  rejected**, not ignored. Any reading this module cannot fill is therefore marked
  `manual_inspection` so it neither auto-passes nor auto-fails.
* `validate` overwrites every reading from the item's template when `inspection_type` is
  `In Process` **and** `reference_type` is `Job Card`, which would discard the per-spool
  length limits computed here. So the Job Card is linked the other way round — by setting
  `Job Card.quality_inspection` — and `reference_type` is left unset.
"""

import json
import re

import frappe
from frappe.utils import cint, flt

from erpnext.devices.label_resolution import PURPOSE_FAILED, PURPOSE_PASSED, resolve_label_template

# Specification name -> where to read it from in the measurement payload.
# `limits: "length"` marks the reading whose min/max are derived per spool from the
# variant's winding-length attribute instead of being taken from the template.
DEFAULT_READINGS = {
	"Загасання волокна (дБ)": {"path": "loss_db"},
	"Довжина волокна (км)": {"path": "distance_km", "limits": "length"},
	"Зворотні втрати ORL (дБ)": {"path": "sor.Summary.optical_return_loss_db"},
	"Довжина хвилі (нм)": {"path": "wavelength_nm"},
}

DEFAULT_CONFIG = {
	"readings": DEFAULT_READINGS,
	"serial_fields": ["sor.General.fiber_id", "sor.General.cable_id"],
	"length_attribute": "Довжина намотки",
	"length_tolerance_pct": 1.0,
	"print_label": True,
}


def _noop(message, level="INFO", **extra):
	pass


def _get_config(otdr_configuration):
	"""Defaults overlaid with `OTDR Configuration.extra_config.spool_qc`, so the reading
	map and tolerances can be retuned per site without a deploy.

	Takes the configuration name directly — the workplace names it now, where the OTDR
	device record used to.
	"""
	cfg = dict(DEFAULT_CONFIG)
	if not otdr_configuration:
		return cfg

	extra = frappe.db.get_value("OTDR Configuration", otdr_configuration, "extra_config")
	if not extra:
		return cfg

	try:
		parsed = json.loads(extra)
	except Exception:
		return cfg

	overrides = (parsed or {}).get("spool_qc") or {}
	if isinstance(overrides, dict):
		cfg.update(overrides)

	return cfg


def _event_logger(e):
	"""Adapt the Workplace Script logger to the `log(message, level=..., **extra)` shape
	this module already uses everywhere."""
	logger = e.get("logger") if hasattr(e, "get") else None
	if logger is None:
		return _noop

	def log(message, level="INFO", **extra):
		text = message
		if extra:
			try:
				text += " " + json.dumps(extra, ensure_ascii=False, default=str)
			except Exception:
				text += f" {extra!r}"
		if str(level).upper() in ("WARN", "WARNING"):
			logger.warn(text)
		elif str(level).upper() == "ERROR":
			logger.error(text)
		else:
			logger.info(text)

	return log


def _dig(payload, path):
	"""Value at a dotted path, or None if any hop is missing."""
	node = payload
	for key in path.split("."):
		if not isinstance(node, dict):
			return None
		node = node.get(key)
		if node is None:
			return None
	return node


def resolve_serial_no(payload, cfg):
	"""The Serial No named by the SOR's Fiber ID, or None.

	Returns (serial_no, raw_value) so the caller can report a value that looked like an
	identifier but matched no Serial No — the common operator typo.
	"""
	for path in cfg.get("serial_fields") or []:
		raw = _dig(payload, path)
		if raw is None:
			continue
		candidate = str(raw).strip()
		if not candidate:
			continue
		if frappe.db.exists("Serial No", candidate):
			return candidate, candidate
		return None, candidate
	return None, None


def _format_reading(value):
	"""Reading as a string in the site's number format.

	`Quality Inspection Reading.reading_#` is a Data field parsed with the user's number
	format, and `validate_reading_number_format` refuses anything else — so a locale using
	a comma decimal separator needs the comma here.
	"""
	from erpnext.stock.doctype.quality_inspection.quality_inspection import (
		get_reading_number_format,
		get_reading_separators,
	)

	decimal_str, _comma_str = get_reading_separators(get_reading_number_format())
	text = f"{flt(value):g}"
	return text.replace(".", decimal_str) if decimal_str != "." else text


def _nominal_length_km(item_code, attribute_name):
	"""Winding length declared by the variant's attribute.

	Attribute values carry their unit — "25 км", not "25" — so only the leading number is
	read.
	"""
	value = frappe.db.get_value(
		"Item Variant Attribute",
		{"parent": item_code, "attribute": attribute_name},
		"attribute_value",
	)
	if not value:
		return None

	match = re.match(r"\s*([-+]?\d+(?:[.,]\d+)?)", str(value))
	if not match:
		return None
	return float(match.group(1).replace(",", "."))


def _apply_length_limits(reading, item_code, cfg, log):
	"""Set this reading's min/max from the spool's nominal length ± tolerance.

	One template serves every length variant this way; without it each of the ten
	variants would need its own Quality Inspection Template.
	"""
	nominal = _nominal_length_km(item_code, cfg.get("length_attribute"))
	if nominal is None:
		log(
			"Nominal winding length not found, keeping template limits",
			level="WARN",
			item_code=item_code,
			attribute=cfg.get("length_attribute"),
		)
		return

	tolerance = flt(cfg.get("length_tolerance_pct")) / 100.0
	reading.min_value = nominal * (1 - tolerance)
	reading.max_value = nominal * (1 + tolerance)
	log(
		"Length limits set from nominal",
		nominal_km=nominal,
		min_km=reading.min_value,
		max_km=reading.max_value,
	)


def _resolve_qi_template(item_code):
	"""The item's Quality Inspection Template.

	There used to be a per-device override table (`OTDR QC Item`) consulted first. It went
	with the OTDR doctype: the item is now derived from the scanned serial rather than
	picked from a device-scoped dropdown, so the item's own template is the only answer.
	"""
	return frappe.db.get_value("Item", item_code, "quality_inspection_template")


def _source_batch(serial_no):
	"""Fiber reel this spool was wound from, if lineage has been stamped."""
	return frappe.db.get_value("Serial No", serial_no, "source_batch_no")


OPEN_JOB_CARD_STATUSES = ("Open", "Work In Progress", "Material Transferred")


def _workplace_operations(workplace):
	"""The (operations, workstations) this bench is allowed to run.

	Read from `Workplace.allowed_operations`, which is how a bench is already tied to the
	shop floor — the alternative would be a second mapping to keep in step.
	"""
	rows = (workplace.get("allowed_operations") or []) if workplace else []
	operations = [r.get("operation") for r in rows if r.get("operation")]
	workstations = [r.get("workstation") for r in rows if r.get("workstation")]
	return operations, workstations


def _find_job_card(serial_no, item_code, workplace, log):
	"""The Job Card this measurement belongs to.

	First by serial: a spool measured twice must land on the same card. Otherwise the open
	card for this item at this bench, which is what the operator is standing at — the serial
	is then written onto it, so nobody has to type it in twice.
	"""
	by_serial = frappe.get_all(
		"Job Card",
		filters=[["serial_no", "like", f"%{serial_no}%"], ["docstatus", "<", 2]],
		fields=["name", "serial_no", "quality_inspection"],
		order_by="creation desc",
		limit=1,
	)
	if by_serial:
		return by_serial[0], False

	if not item_code:
		return None, False

	filters = {
		"docstatus": 0,
		"status": ["in", OPEN_JOB_CARD_STATUSES],
		"production_item": item_code,
	}
	operations, workstations = _workplace_operations(workplace)
	if operations:
		filters["operation"] = ["in", operations]
	if workstations:
		filters["workstation"] = ["in", workstations]

	candidates = frappe.get_all(
		"Job Card",
		filters=filters,
		fields=["name", "serial_no", "quality_inspection", "for_quantity"],
		order_by="creation asc",
		limit=20,
	)
	if not candidates:
		log(
			"No open Job Card for this spool at this workplace, inspection not linked",
			level="WARN",
			item_code=item_code,
			workplace=workplace.get("name") if workplace else None,
		)
		return None, False

	# A Work Order for a serialised item already splits into one card per spool with the
	# serial filled in, so a card that is full belongs to a different spool — taking it would
	# put two serials on a card that produces one.
	with_room = [c for c in candidates if not _job_card_is_full(c)]
	if not with_room:
		log(
			"Every open Job Card already has its spool, inspection not linked",
			level="WARN",
			job_cards=[c.name for c in candidates],
		)
		return None, False

	if len(with_room) > 1:
		log(
			"Several open Job Cards have room, taking the oldest",
			level="WARN",
			job_cards=[c.name for c in with_room],
		)
	return with_room[0], True


def _job_card_is_full(job_card):
	"""True when the card already names as many spools as it plans to produce."""
	for_quantity = job_card.get("for_quantity") or 0
	if not for_quantity:
		return False
	recorded = len([s for s in (job_card.get("serial_no") or "").splitlines() if s.strip()])
	return recorded >= for_quantity


def _append_serial(job_card, serial_no, log):
	"""Add this spool to the card's serial list, keeping any already recorded."""
	existing = [s.strip() for s in (job_card.serial_no or "").splitlines() if s.strip()]
	if serial_no in existing:
		return
	existing.append(serial_no)

	for_quantity = job_card.get("for_quantity") or 0
	if for_quantity and len(existing) > for_quantity:
		log(
			"More spools measured than the Job Card plans to produce",
			level="WARN",
			job_card=job_card.name,
			measured=len(existing),
			for_quantity=for_quantity,
		)

	frappe.db.set_value("Job Card", job_card.name, "serial_no", "\n".join(existing))
	log("Spool serial recorded on Job Card", job_card=job_card.name, serial_no=serial_no)


def _link_job_card(qi_name, serial_no, log, item_code=None, workplace=None):
	"""Point the spool's Job Card at this inspection so completion is gated by it.

	Done from this side on purpose: setting `Quality Inspection.reference_type` to
	`Job Card` makes stock `validate` reload every reading from the item template and
	discard the per-spool length limits.
	"""
	job_card, claimed = _find_job_card(serial_no, item_code, workplace, log)
	if not job_card:
		return None

	if claimed:
		_append_serial(job_card, serial_no, log)

	if job_card.quality_inspection:
		return job_card.name

	frappe.db.set_value("Job Card", job_card.name, "quality_inspection", qi_name)
	log("Job Card linked to inspection", job_card=job_card.name)
	return job_card.name


def make_quality_inspection(serial_no, item_code, payload, cfg, log, workplace=None):
	"""Create and submit the Quality Inspection for one measured spool."""
	template = _resolve_qi_template(item_code)
	if not template:
		log(
			"No Quality Inspection Template for item, skipping inspection",
			level="WARN",
			item_code=item_code,
		)
		return None

	qi = frappe.new_doc("Quality Inspection")
	qi.inspection_type = "In Process"
	qi.report_date = frappe.utils.nowdate()
	# Mandatory on Quality Inspection; one spool is measured per trace.
	qi.sample_size = 1
	qi.item_code = item_code
	qi.item_serial_no = serial_no
	qi.quality_inspection_template = template
	# `inspected_by` defaults to the literal string "user", which is not a User and fails
	# link validation outside a desk session. The measurement arrives over the API, so the
	# inspector is whoever the device authenticated as.
	qi.inspected_by = frappe.session.user

	batch_no = _source_batch(serial_no)
	if batch_no:
		qi.batch_no = batch_no

	qi.get_item_specification_details()
	if not qi.readings:
		log("Template has no readings, skipping inspection", level="WARN", template=template)
		return None

	readings_cfg = cfg.get("readings") or {}
	filled = {}
	for reading in qi.readings:
		spec = readings_cfg.get(reading.specification)
		value = _dig(payload, spec["path"]) if spec else None

		if value is None:
			# An empty numeric reading is treated as a failure by
			# `min_max_criteria_passed`, so anything unmeasured must opt out of grading.
			if cint(reading.numeric):
				reading.manual_inspection = 1
			continue

		reading.reading_1 = _format_reading(value)
		reading.manual_inspection = 0
		if spec.get("limits") == "length":
			_apply_length_limits(reading, item_code, cfg, log)
		filled[reading.specification] = reading.reading_1

	if not filled:
		log(
			"Measurement matched no template reading, skipping inspection",
			level="WARN",
			template=template,
			known_specifications=list(readings_cfg),
		)
		return None

	qi.flags.ignore_permissions = True
	qi.insert()
	qi.submit()
	log("Quality Inspection submitted", quality_inspection=qi.name, status=qi.status, readings=filled)

	_link_job_card(qi.name, serial_no, log, item_code=item_code, workplace=workplace)
	return qi


def print_qc_label(
	serial_no,
	item_code,
	qi,
	payload,
	otdr_configuration,
	cfg,
	log,
	workplace=None,
	label_printer=None,
):
	"""Queue the Passed or Failed label for the inspected spool.

	Printer precedence, most specific first: the printer the operator picked in the app,
	the workplace's default printer, the printer named on the matching label row, then any
	printer the item names at all. The workplace sits above the item because the label has
	to come out at the bench where the spool physically is.
	"""
	if not cfg.get("print_label"):
		log("Label printing disabled by configuration")
		return None

	purpose = PURPOSE_PASSED if qi.status == "Accepted" else PURPOSE_FAILED
	resolved = resolve_label_template(item_code, purpose, otdr_configuration=otdr_configuration)
	if not resolved:
		log(
			"No label template configured for purpose, nothing printed",
			level="WARN",
			item_code=item_code,
			purpose=purpose,
		)
		return None

	printer = (
		label_printer
		or _workplace_printer(workplace)
		or resolved.get("label_printer")
		or _any_printer_for(item_code)
	)
	if not printer:
		log(
			"Label template has no printer, nothing printed",
			level="WARN",
			label_template=resolved["label_template"],
			purpose=purpose,
		)
		return None

	raw_data = {
		"serial_no": serial_no,
		"coil_code": serial_no,
		"item_code": item_code,
		"item_name": frappe.db.get_value("Item", item_code, "item_name"),
		"quality_inspection": qi.name,
		"qi_status": qi.status,
		"purpose": purpose,
		"fiber_length": _dig(payload, "distance_km"),
		"loss_db": _dig(payload, "loss_db"),
		"wavelength": _dig(payload, "wavelength_nm"),
		"source_batch_no": _source_batch(serial_no),
		"label_date": frappe.utils.nowdate(),
	}

	from erpnext.devices.doctype.label_printer.label_printer import create_print_job

	result = create_print_job(
		label_template=resolved["label_template"],
		printer_name=printer,
		reference_name=serial_no,
		raw_data=raw_data,
	)
	log(
		"Label queued",
		print_job=result.get("print_job"),
		label_template=resolved["label_template"],
		printer=printer,
		purpose=purpose,
		template_source=resolved.get("source"),
	)
	return result.get("print_job")


def _any_printer_for(item_code):
	"""Printer from any of the item's label rows, when the matching row names none."""
	return frappe.db.get_value(
		"Item Label Template",
		{"parent": item_code, "parenttype": "Item", "label_printer": ["is", "set"]},
		"label_printer",
	)


def _workplace_printer(workplace):
	"""The workplace's default printer, if it declares one.

	`Workplace.printers` allows several — a bench with a spool printer and a box printer —
	with at most one marked default (enforced in `Workplace._validate_printers`). Only the
	default is chosen automatically; when there is none the app offers the list.
	"""
	if not workplace:
		return None

	name = workplace if isinstance(workplace, str) else workplace.get("name")
	if not name:
		return None

	return frappe.db.get_value(
		"Workplace Printer",
		{"parent": name, "parenttype": "Workplace", "is_default": 1},
		"label_printer",
	)


def printers_for_workplace(workplace):
	"""Every printer a workplace declares, for the app's picker."""
	if not workplace:
		return []

	name = workplace if isinstance(workplace, str) else workplace.get("name")
	if not name:
		return []

	return frappe.get_all(
		"Workplace Printer",
		filters={"parent": name, "parenttype": "Workplace"},
		fields=["label_printer", "printer_model", "ip_address", "is_default"],
		order_by="is_default desc, idx",
	)


def handle_measurement(e):
	"""Entry point for the `Spool QC` Workplace Script's `measuring` state.

	Returns a summary dict which `submit_measurement` stamps onto the OTDR Measurement and
	hands back to the phone. Problems are logged rather than raised: the log lines travel
	with the response, so a misidentified spool shows up at the workbench instead of
	surfacing as a stack trace.
	"""
	log = _event_logger(e)
	payload = e.get("payload")
	if not isinstance(payload, dict):
		log("Measurement payload is not a dict, nothing to do", level="WARN")
		return {"status": "skipped", "reason": "bad_payload"}

	workplace = e.get("workplace")
	otdr_configuration = workplace.get("otdr_configuration") if workplace else None
	cfg = _get_config(otdr_configuration)

	# The serial the operator chose in the app wins; the SOR's own Fiber ID is the fallback
	# for a client that did not send one.
	serial_no = (e.get("serial_no") or "").strip() or None
	raw_identifier = serial_no
	if serial_no and not frappe.db.exists("Serial No", serial_no):
		log("Serial No sent by the app does not exist", level="WARN", serial_no=serial_no)
		serial_no = None
	if not serial_no:
		serial_no, raw_identifier = resolve_serial_no(payload, cfg)

	if not serial_no:
		if raw_identifier:
			log(
				"Measurement identifier does not match any Serial No",
				level="WARN",
				identifier=raw_identifier,
			)
			return {"status": "skipped", "reason": "unknown_serial", "identifier": raw_identifier}
		log("No spool serial supplied — scan the spool in the app before measuring", level="WARN")
		return {"status": "skipped", "reason": "no_serial"}

	item_code = frappe.db.get_value("Serial No", serial_no, "item_code")
	log("Spool identified", serial_no=serial_no, item_code=item_code)

	qi = make_quality_inspection(serial_no, item_code, payload, cfg, log, workplace=workplace)
	if not qi:
		return {"status": "skipped", "reason": "no_inspection", "serial_no": serial_no}

	print_job = None
	if cint(e.get("auto_print")):
		print_job = print_qc_label(
			serial_no,
			item_code,
			qi,
			payload,
			otdr_configuration,
			cfg,
			log,
			workplace=workplace,
			label_printer=e.get("label_printer"),
		)
	else:
		log("Auto-print off, label not queued", serial_no=serial_no)

	return {
		"status": "ok",
		"serial_no": serial_no,
		"item_code": item_code,
		"quality_inspection": qi.name,
		"qi_status": qi.status,
		"verdict": "Pass" if qi.status == "Accepted" else "Fail",
		"print_job": print_job,
	}
